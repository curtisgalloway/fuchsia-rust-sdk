#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Measure a driver's dependency closure in fuchsia.git (design D8, R12; milestone M6).

Usage:
  closure.py [--out FILE] [--idk DIR] [--name NAME] LABEL...

Walks GN deps from each root LABEL (for example //examples/drivers/simple/rust:driver)
at the lock's fuchsia_revision, the way the brief's App. B walker does, and writes a JSON
report: the in-tree Rust crates, the crates.io crates (direct, and the transitive set
through upstream's crate_universe BUILD files), the FIDL libraries and bind libraries
whose Rust bindings are needed, the native (non-Rust) targets reached, and every GN
conditional in the files walked with how it was decided.

Differences from the brief's walker:
  * BUILD.gn files are evaluated (scripts/gn_eval.py), not matched with regexes, so deps
    held in variables (`deps = LIB_DEPS`, as bazel2gn writes them), relative labels
    ("core") and proc_macro_deps are followed.
  * rustc_dylib targets are followed (the brief missed src/storage/lib/vfs/rust).
  * Conditionals are evaluated per toolchain: a crate built for Fuchsia sees
    is_fuchsia = true, current_os = "fuchsia"; proc macros and their deps, and labels
    with an explicit toolchain, are evaluated for the host (linux). A condition on
    anything else (current_cpu, imported variables) is UNKNOWN: both branches are
    followed (an upper bound) and the report lists it as "unknown". A build argument has
    the default its declare_args() gives (read from the file's imports); conditions that
    read one list it. The report also has `upper_bound_counts`, from a second walk that
    treats every condition as UNKNOWN, as the brief's walker did.
  * FIDL dependencies of FIDL libraries are followed, per binding flavor.
  * test_deps and test targets are not followed (D5: production builds only).
  * A target made by an imported template other than the Rust and FIDL ones is a leaf
    ("native"); its deps are not followed but counted (`deps_not_followed`, and
    `native_deps_not_followed` in counts), so nothing is dropped silently.

Inputs: overlay.lock.json (fuchsia_revision); fuchsia.git over anonymous HTTPS through
regen.py's GitSource (C1; depth-1 blobless fetch, blobs by ID). --idk names an
extracted IDK (its fidl/ and bind/ directories) to mark which libraries it has.
"""

from __future__ import annotations

import argparse
import ast
import json
import posixpath
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import gn_eval
import regen
from regen import RegenError

ROOT = Path(__file__).resolve().parent.parent

# GN templates that build a Rust crate (followed, and listed as in-tree crates).
RUST_KINDS = {
    "rustc_library": "lib",
    "rustc_macro": "proc-macro",
    "rustc_dylib": "dylib",
    "rustc_staticlib": "staticlib",
    "rustc_cdylib": "cdylib",
    "rustc_binary": "bin",
    "fuchsia_rust_driver": "driver",
}
# GN templates whose deps are followed but that are not crates themselves.
GROUP_KINDS = ("group",)
# Dep variables followed, and the toolchain context each one's deps are built in.
DEP_VARS = ("deps", "public_deps", "non_rust_deps")
PROC_MACRO_VARS = ("proc_macro_deps",)

RUST_CRATES = "third_party/rust_crates"
CRATE_KINDS = ("vendor", "forks", "ask2patch")

# Toolchain contexts and the GN variables known in each. Anything else is UNKNOWN.
# current_build_target_api_level follows the overlay's toolchains: HEAD for Fuchsia
# (C3, R3), PLATFORM for the host (M4). is_kernel is false: nothing here is kernel code.
ENVS = {
    "fuchsia": {"is_fuchsia": True, "is_host": False, "is_linux": False, "is_mac": False,
                "is_win": False, "is_android": False, "is_chromeos": False, "is_kernel": False,
                "current_os": "fuchsia", "target_os": "fuchsia", "host_os": "linux",
                "host_cpu": "x64", "current_build_target_api_level": "HEAD"},
    "host": {"is_fuchsia": False, "is_host": True, "is_linux": True, "is_mac": False,
             "is_win": False, "is_android": False, "is_chromeos": False, "is_kernel": False,
             "current_os": "linux", "target_os": "fuchsia", "host_os": "linux",
             "host_cpu": "x64", "current_cpu": "x64", "current_build_target_api_level": "PLATFORM"},
    "any": {},
}
# crate_universe select() keys kept when following crates.io deps: the platforms the
# overlay builds (both Fuchsia targets, and the linux-amd64 host, C5).
PLATFORMS = (
    "@rules_rust//rust/platform:aarch64-unknown-fuchsia",
    "@rules_rust//rust/platform:x86_64-unknown-fuchsia",
    "@rules_rust//rust/platform:x86_64-unknown-linux-gnu",
    "//conditions:default",
)


class ClosureError(Exception):
    """The walk cannot continue; the message names the label or file."""


# --- labels -------------------------------------------------------------------------


def parse_label(dep: str, cur: str) -> tuple[str, str, bool]:
    """(path, target name, explicit toolchain) of a GN label written in package `cur`."""
    toolchain = False
    m = re.fullmatch(r"(.*)\(([^()]*)\)", dep)
    if m:
        dep, toolchain = m.group(1), True
    if dep.startswith("//"):
        path, _, name = dep[2:].partition(":")
    elif dep.startswith(":"):
        path, name = cur, dep[1:]
    else:
        rel, _, name = dep.partition(":")
        path = posixpath.normpath(posixpath.join(cur, rel))
        if path.startswith(".."):
            raise ClosureError(f"{dep!r} in //{cur} leaves the source tree")
    path = path.rstrip("/")
    return path, name or posixpath.basename(path), toolchain


def label(path: str, name: str) -> str:
    return f"//{path}" if name == posixpath.basename(path) else f"//{path}:{name}"


# --- upstream access -------------------------------------------------------------------


class Tree:
    """Cached, batched reads of fuchsia.git files (None for a missing file)."""

    def __init__(self, source):
        self.source = source
        self.cache: dict[str, bytes | None] = {}

    def fetch(self, paths) -> None:
        want = sorted({p for p in paths if p not in self.cache})
        if not want:
            return
        have = self.source.existing(want)
        data = self.source.read(sorted(have)) if have else {}
        for p in want:
            self.cache[p] = data.get(p)

    def get(self, path: str) -> bytes | None:
        self.fetch([path])
        return self.cache[path]


# --- the walk ----------------------------------------------------------------------------


# Build arguments whose value the overlay decides instead of taking upstream's default.
# fuchsia_sync_detect_lock_cycles: upstream's default is `compilation_mode == "debug"`;
# the overlay builds production code, so false (decided by the orchestrator after the
# M6a review; M9 maps upstream's @fuchsia_build_info load to the same value).
OVERLAY_ARGS = {"fuchsia_sync_detect_lock_cycles": False}


class Evaluated:
    """BUILD.gn results per (path, context), with build-argument defaults from imports."""

    def __init__(self, tree: Tree, mode: str):
        self.tree = tree
        self.mode = mode
        self.results: dict[tuple[str, str], gn_eval.FileResult | None] = {}
        self.gni: dict[tuple[str, str], dict] = {}
        self.import_errors: dict[str, str] = {}

    def _imports(self, path: str, text: str) -> list[str]:
        out = []
        for imp in gn_eval.imports(text, f"{path}/BUILD.gn"):
            p = imp[2:] if imp.startswith("//") else posixpath.normpath(posixpath.join(path, imp))
            out.append(p)
        return out

    def prefetch(self, paths: list[str]) -> None:
        """Fetch the imports of already-fetched BUILD.gn files, in one request."""
        if self.mode == "all":
            return
        want = []
        for path in paths:
            text = self.tree.cache.get(f"{path}/BUILD.gn")
            if text:
                try:
                    want += self._imports(path, text.decode())
                except gn_eval.GnError:
                    pass
        self.tree.fetch(want)

    def args(self, path: str, text: str, ctx: str) -> dict:
        """Build arguments the file's imports declare, with their defaults in `ctx`."""
        out = {}
        for gni in self._imports(path, text):
            if (gni, ctx) not in self.gni:
                raw = self.tree.get(gni)
                try:
                    args = gn_eval.evaluate(raw.decode(), ENVS[ctx], gni).args if raw is not None else {}
                    self.gni[(gni, ctx)] = {k: OVERLAY_ARGS.get(k, v) for k, v in args.items()}
                    if raw is None:
                        self.import_errors[gni] = "missing at the revision"
                except gn_eval.GnError as e:
                    self.gni[(gni, ctx)] = {}
                    self.import_errors[gni] = str(e)
            out.update(self.gni[(gni, ctx)])
        return out

    def get(self, path: str, ctx: str) -> gn_eval.FileResult | None:
        key = (path, ctx)
        if key not in self.results:
            raw = self.tree.get(f"{path}/BUILD.gn")
            if raw is None:
                self.results[key] = None
            else:
                text = raw.decode()
                try:
                    if ctx == "any":
                        res = gn_eval.evaluate(text, ENVS[ctx], f"{path}/BUILD.gn", arg_defaults=False)
                    else:
                        res = gn_eval.evaluate(text, ENVS[ctx], f"{path}/BUILD.gn", self.args(path, text, ctx))
                except gn_eval.GnError as e:
                    raise ClosureError(str(e)) from None
                self.results[key] = res
        return self.results[key]


@dataclass
class Report:
    crates: dict[str, dict] = field(default_factory=dict)  # label -> record
    third: dict[str, dict] = field(default_factory=dict)  # GN alias -> record
    fidl: dict[str, dict] = field(default_factory=dict)  # library -> record
    bind: dict[str, dict] = field(default_factory=dict)
    native: dict[str, dict] = field(default_factory=dict)
    unresolved: dict[str, dict] = field(default_factory=dict)
    files: set[str] = field(default_factory=set)  # BUILD.gn files a walked target is in
    targets: dict[str, set[str]] = field(default_factory=dict)  # path -> walked target names
    evaluated: Evaluated | None = None
    gaps: list[dict] = field(default_factory=list)  # what the walker could not follow


def _strings(value) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _unknowns(value) -> int:
    if value is gn_eval.UNKNOWN:
        return 1
    if isinstance(value, list):
        return sum(1 for v in value if not isinstance(v, str))
    return 0


def _add(rec: dict, key: str, value: str) -> None:
    if value not in rec[key]:
        rec[key].append(value)
        rec[key].sort()


def walk(tree: Tree, roots: list[str], mode: str = "fuchsia") -> Report:
    """Walk GN deps from `roots`. mode "fuchsia": per-toolchain conditions; "all": none."""
    rep = Report()
    ev = rep.evaluated = Evaluated(tree, mode)
    # (path, name, context, fidl flavor or None, the label that asked for it)
    frontier = [(*parse_label(r, "")[:2], "fuchsia" if mode == "fuchsia" else "any", None, "<root>")
                for r in roots]
    seen = set()

    def ctx_for(ctx: str, host: bool) -> str:
        return "any" if mode == "all" else ("host" if host else ctx)

    while frontier:
        paths = sorted({p for p, _, _, _, _ in frontier if not p.startswith(RUST_CRATES)})
        tree.fetch(f"{p}/BUILD.gn" for p in paths)
        ev.prefetch(paths)
        nxt = []
        for path, name, ctx, flavor, via in frontier:
            # Once per requester, so every record's used_by is complete; a target's own
            # deps are pushed with the same requester (itself) each time, so this ends.
            key = (path, name, ctx, flavor, via)
            if key in seen:
                continue
            seen.add(key)
            lab = label(path, name)
            if path == RUST_CRATES:
                rec = rep.third.setdefault(name, {"contexts": [], "used_by": []})
                _add(rec, "contexts", ctx)
                _add(rec, "used_by", via)
                continue
            if path.startswith(RUST_CRATES + "/"):
                rep.unresolved.setdefault(lab, {"reason": f"under {RUST_CRATES}/ but not an alias", "used_by": []})
                _add(rep.unresolved[lab], "used_by", via)
                continue
            gn_path = f"{path}/BUILD.gn"
            res = ev.get(path, ctx)
            if res is None:
                rep.unresolved.setdefault(lab, {"reason": "no BUILD.gn", "used_by": []})
                _add(rep.unresolved[lab], "used_by", via)
                continue
            target = res.targets.get(name)

            if flavor is not None:
                # A dependency of a FIDL library: another FIDL library, same flavor.
                if target is None or target.kind != "fidl":
                    rep.unresolved.setdefault(lab, {"reason": f"FIDL dep that is not a fidl() target "
                                                              f"({target.kind if target else 'no such target'})",
                                                    "used_by": []})
                    _add(rep.unresolved[lab], "used_by", via)
                    continue
                nxt += _fidl(rep, res, path, name, target, flavor, ctx, via, lab)
                continue

            if target is None:
                # Targets a template defines implicitly: FIDL and bind library bindings.
                fidl = _implicit(res, name, "fidl")
                bind = _implicit(res, name, "bind_library")
                if fidl:
                    base, fl = fidl
                    nxt += _fidl(rep, res, path, base, res.targets[base], fl, ctx, via, label(path, base))
                elif bind and bind[1] == "rust":
                    lib = res.targets[bind[0]].scope.get("name")
                    lib = lib if isinstance(lib, str) else bind[0]
                    rec = rep.bind.setdefault(lib, {"label": label(path, bind[0]), "contexts": [], "used_by": []})
                    _add(rec, "contexts", ctx)
                    _add(rec, "used_by", via)
                else:
                    why = "no such target"
                    if name in (ev.get(path, "any") or gn_eval.FileResult()).targets:
                        why = "defined only under a condition that is false here"
                    rep.unresolved.setdefault(lab, {"reason": why, "used_by": []})
                    _add(rep.unresolved[lab], "used_by", via)
                continue

            rep.files.add(gn_path)
            rep.targets.setdefault(path, set()).add(name)
            if target.kind in RUST_KINDS:
                s = target.scope
                crate_name = s.get("crate_name") if isinstance(s.get("crate_name"), str) else s.get("name")
                rec = rep.crates.setdefault(lab, {
                    "path": path, "target": name, "gn_template": target.kind,
                    "crate_type": RUST_KINDS[target.kind],
                    "crate_name": crate_name if isinstance(crate_name, str) else name.replace("-", "_"),
                    "edition": s.get("edition") if isinstance(s.get("edition"), str) else None,
                    "features": _strings(s.get("features")),
                    "same_file_template": res.template_calls.get(name),
                    "contexts": [], "used_by": [],
                    # Dep list entries the evaluator could not know (never followed), plus
                    # one if variables were forwarded from an unknown scope.
                    "unknown_deps": (sum(_unknowns(s.get(v)) for v in DEP_VARS + PROC_MACRO_VARS)
                                     + int(target.unknown_forward)),
                })
                _add(rec, "contexts", ctx)
                _add(rec, "used_by", via)
                host = target.kind == "rustc_macro"
                for var in DEP_VARS + PROC_MACRO_VARS:
                    value = s.get(var)
                    for dep in _strings(value):
                        p, n, tc = parse_label(dep, path)
                        nxt.append((p, n, ctx_for(ctx, host or tc or var in PROC_MACRO_VARS), None, lab))
            elif target.kind in GROUP_KINDS:
                for var in ("deps", "public_deps"):
                    for dep in _strings(target.scope.get(var)):
                        p, n, tc = parse_label(dep, path)
                        nxt.append((p, n, ctx_for(ctx, tc), None, via))
            elif target.kind == "fidl":
                nxt += _fidl(rep, res, path, name, target, None, ctx, via, lab)
            else:
                # A leaf: an imported template (C/C++ library, or anything else the walk
                # does not treat as Rust). Its deps are not followed; say how many there
                # were, so an imported template wrapping Rust cannot lose deps silently.
                rec = rep.native.setdefault(lab, {
                    "gn_template": target.kind, "contexts": [], "used_by": [],
                    "deps_not_followed": sum(len(_strings(target.scope.get(v))) + _unknowns(target.scope.get(v))
                                             for v in ("deps", "public_deps")),
                })
                _add(rec, "contexts", ctx)
                _add(rec, "used_by", via)
        frontier = nxt
    return rep


def _implicit(res: gn_eval.FileResult, name: str, kind: str) -> tuple[str, str] | None:
    """(base, flavor) when `name` is <base>_<flavor> for a `kind` target <base>, flavor rust*."""
    best = None
    for base, t in res.targets.items():
        if t.kind == kind and name.startswith(base + "_rust"):
            if best is None or len(base) > len(best[0]):
                best = (base, name[len(base) + 1:])
    return best


# What the FIDL binding templates add to each binding crate, per flavor (the target
# suffix after "<library>_"; "_internal" dropped). Transcribed from fuchsia.git at the
# release: build/fidl/fidl.gni (which flavors exist, contains_drivers only when
# `!is_host && enable_rust_drivers` for `rust`, `!is_host` for rust_next),
# build/rust/fidl_rust.gni (_fidl_rust_crate, _flex_crate) and
# build/rust/fidl_rust_next.gni (fidl_rust_next, fidl_rust_next_convert). Each entry:
#   deps      Rust crates every binding crate of the flavor depends on
#   fuchsia   more crates when built for Fuchsia (`if (is_fuchsia)`)
#   drivers   more crates when the library sets contains_drivers (see driver_gate)
#   siblings  other flavors of the same library it depends on
#   fidl_deps the flavor its FIDL public_deps are taken in (None: not followed)
# The `//sdk/categories:marker-*` dep every binding has is a GN bookkeeping group and
# is left out. A FIDL public_dep on //zircon/vdso/zx becomes //sdk/rust/zx-types.
_FIDL_RUST_DEPS = ["//sdk/rust/zx-status", "//src/lib/fidl/rust/fidl",
                   "//third_party/rust_crates:bitflags", "//third_party/rust_crates:futures"]
_FIDL_RUST_DRIVERS = ["//src/lib/fidl/rust/fidl_driver", "//sdk/lib/driver/runtime/rust"]
_FIDL_NEXT_DEPS = ["//src/lib/fidl/rust_next/fidl_next:fidl_next_internal",
                   "//third_party/rust_crates:static_assertions"]
_FDOMAIN = ["//src/lib/fdomain/client"]
FIDL_FLAVORS = {
    "rust": dict(deps=_FIDL_RUST_DEPS, fuchsia=["//sdk/rust/zx"], drivers=_FIDL_RUST_DRIVERS,
                 driver_gate="rust", siblings=["rust_common"], fidl_deps="rust"),
    "rust_common": dict(deps=_FIDL_RUST_DEPS, fuchsia=["//sdk/rust/zx"], drivers=_FIDL_RUST_DRIVERS,
                        driver_gate="rust", siblings=[], fidl_deps="rust_common"),
    "rust_fdomain": dict(deps=_FIDL_RUST_DEPS + _FDOMAIN, fuchsia=["//sdk/rust/zx"],
                         drivers=_FIDL_RUST_DRIVERS, driver_gate="rust", siblings=["rust_common"],
                         fidl_deps="rust_fdomain"),
    "rust_flex": dict(deps=[], fuchsia=[], drivers=[], driver_gate=None, siblings=["rust"], fidl_deps=None),
    "rust_fdomain_flex": dict(deps=[], fuchsia=[], drivers=[], driver_gate=None,
                              siblings=["rust_fdomain"], fidl_deps=None),
    "rust_next": dict(deps=_FIDL_NEXT_DEPS, fuchsia=[], drivers=["//sdk/lib/driver/runtime/rust/fidl"],
                      driver_gate="rust_next", siblings=["rust_next_common"], fidl_deps="rust_next"),
    "rust_next_common": dict(deps=_FIDL_NEXT_DEPS, fuchsia=[], drivers=["//sdk/lib/driver/runtime/rust/fidl"],
                             driver_gate="rust_next", siblings=[], fidl_deps="rust_next_common"),
    "rust_fdomain_next": dict(deps=_FIDL_NEXT_DEPS + _FDOMAIN, fuchsia=[], drivers=[], driver_gate=None,
                              siblings=["rust_next_common"], fidl_deps="rust_fdomain_next"),
    "rust_next_convert": dict(deps=[], fuchsia=[], drivers=[], driver_gate=None,
                              siblings=["rust_next", "rust"], fidl_deps=None),
}
ZX_FIDL = ("zircon/vdso/zx", "zx")


def canonical_flavor(flavor: str) -> str:
    return flavor[: -len("_internal")] if flavor.endswith("_internal") else flavor


def _truthy(value) -> bool | None:
    return value if isinstance(value, bool) else None


def _fidl(rep: Report, res, path: str, base: str, target, flavor: str | None, ctx: str, via: str,
          lab: str) -> list:
    """Record a FIDL library (with a binding flavor, or none for a bare fidl() dep).

    Returns the frontier entries the binding crate adds: its FIDL deps (same library
    flavor rules), sibling flavors, and the Rust crates the binding templates add.
    """
    lib = target.scope.get("name")
    lib = lib if isinstance(lib, str) else base
    rec = rep.fidl.setdefault(lib, {"label": lab, "flavors": [], "direct_flavors": [],
                                    "sdk_category": None, "contains_drivers": None,
                                    "contexts": [], "used_by": []})
    cat = target.scope.get("sdk_category")
    if isinstance(cat, str):
        rec["sdk_category"] = cat
    _add(rec, "contexts", ctx)
    _add(rec, "used_by", via)
    if flavor is None:
        return []
    flavor = canonical_flavor(flavor)
    _add(rec, "flavors", flavor)
    if not via.startswith("fidl:"):
        _add(rec, "direct_flavors", flavor)
    spec = FIDL_FLAVORS.get(flavor)
    binding = label(path, f"{base}_{flavor}")
    if spec is None:
        rep.gaps.append({"file": f"{path}/BUILD.gn", "line": target.line, "in_target": base,
                         "what": f"binding flavor {flavor!r} is not modelled: its template deps are not followed"})
        return []
    out = []
    if spec["fidl_deps"]:
        for dep in _strings(target.scope.get("public_deps")):
            p, n, _ = parse_label(dep, path)
            if (p, n) == ZX_FIDL:
                out.append(("sdk/rust/zx-types", "zx-types", ctx, None, binding))
            else:
                out.append((p, n, ctx, spec["fidl_deps"], f"fidl:{lib}"))
    for sib in spec["siblings"]:
        out.append((path, base, ctx, sib, f"fidl:{lib}"))
    crates = list(spec["deps"])
    if ctx in ("fuchsia", "any"):
        crates += spec["fuchsia"]
    if spec["driver_gate"] and ctx != "host":
        def flag(name: str) -> bool | None:  # fidl() parameters default to false
            return _truthy(target.scope[name]) if name in target.scope else False
        gates = [flag("contains_drivers")]
        if spec["driver_gate"] == "rust":  # fidl.gni: `!is_host && enable_rust_drivers`
            gates.append(flag("enable_rust_drivers"))
        if None in gates:
            rep.gaps.append({"file": f"{path}/BUILD.gn", "line": target.line, "in_target": base,
                             "what": "contains_drivers or enable_rust_drivers unknown: driver deps followed"})
        drivers = all(g is not False for g in gates)
        if drivers:
            crates += spec["drivers"]
            rec["contains_drivers"] = True
        elif rec["contains_drivers"] is None:
            rec["contains_drivers"] = False
    for dep in crates:
        p, n, _ = parse_label(dep, "")
        out.append((p, n, ctx, None, binding))
    return out


def conditionals(rep: Report, mode: str) -> list[dict]:
    """Every `if` in a walked file, at file level or inside a walked target, per context."""
    out = []
    for gn_path in sorted(rep.files):
        path = gn_path[: -len("/BUILD.gn")]
        walked = rep.targets.get(path, set())
        seen = {}
        for ctx in (("fuchsia", "host") if mode == "fuchsia" else ("any",)):
            for c in rep.evaluated.get(path, ctx).conditionals:
                if c.target is not None and c.target not in walked:
                    continue
                rec = seen.setdefault((c.line, c.target), {
                    "file": gn_path, "line": c.line, "condition": c.text, "in_target": c.target,
                    "build_args": {}, "outcome": {}})
                rec["outcome"][ctx] = c.outcome
                if c.args:
                    rec["build_args"][ctx] = c.args
        out += [seen[k] for k in sorted(seen, key=lambda k: (k[0], k[1] or ""))]
    return out


def evaluation_gaps(rep: Report) -> list[dict]:
    """What the walk could not follow in walked files (evaluator gaps, FIDL flavor gaps)."""
    out = {}
    for gn_path in sorted(rep.files):
        path = gn_path[: -len("/BUILD.gn")]
        walked = rep.targets.get(path, set())
        for ctx in ("fuchsia", "host", "any"):
            res = rep.evaluated.results.get((path, ctx))
            for line, target, what in (res.gaps if res else []):
                if target is not None and target not in walked:
                    continue
                out.setdefault((gn_path, line, what), {"file": gn_path, "line": line, "in_target": target,
                                                       "what": what})
    for g in rep.gaps:
        out.setdefault((g["file"], g["line"], g["what"]), g)
    return [out[k] for k in sorted(out)]


# --- crates.io: direct aliases to crate directories, then the transitive set ----------------


def _select_filtered_strings(text: str, where: str, platforms=PLATFORMS) -> tuple[set[str], set[str]]:
    """(strings kept, strings in select() branches for other platforms) of a BUILD file."""
    tree = ast.parse(text, filename=where)
    dropped_nodes: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "select"
                and node.args and isinstance(node.args[0], ast.Dict)):
            for k, v in zip(node.args[0].keys, node.args[0].values):
                if isinstance(k, ast.Constant) and k.value not in platforms:
                    dropped_nodes.update(id(n) for n in ast.walk(v))
    kept, dropped = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            (dropped if id(node) in dropped_nodes else kept).add(node.value)
    return kept, dropped


def _crate_dir(lab: str) -> str | None:
    """"//third_party/rust_crates/vendor/foo-1.0:foo" -> "vendor/foo-1.0"."""
    if not lab.startswith(f"//{RUST_CRATES}/"):
        return None
    pkg = lab[2:].partition(":")[0][len(RUST_CRATES) + 1:]
    parts = pkg.split("/")
    if len(parts) == 2 and parts[0] in CRATE_KINDS:
        return pkg
    return None


def crates_io(tree: Tree, rep: Report) -> dict:
    """Resolve direct GN aliases through upstream's Bazel aliases; follow crate BUILD files."""
    aliases = regen.parse_aliases(tree.get(f"{RUST_CRATES}/vendor/BUILD.bazel").decode())
    gn_text = tree.get(f"{RUST_CRATES}/BUILD.gn").decode()
    lock = regen.cargo_lock_checksums(tree.get(f"{RUST_CRATES}/Cargo.lock").decode())
    direct = []
    todo: dict[str, set[str]] = {}
    for alias in sorted(rep.third):
        rec = rep.third[alias]
        actual = aliases.get(alias)
        m = re.search(r'group\("%s"\)\s*\{\s*public_deps = \[ ":([^"]+)" \]' % re.escape(alias), gn_text)
        entry = {"alias": alias, "gn_target": m.group(1) if m else None, "bazel_actual": actual,
                 "crate_dir": _crate_dir(actual) if actual else None,
                 "contexts": rec["contexts"], "used_by": rec["used_by"]}
        direct.append(entry)
        if entry["crate_dir"]:
            todo.setdefault(entry["crate_dir"], set()).update(rec["contexts"])
    crates: dict[str, dict] = {}
    frontier = sorted(todo)
    all_labels_dirs: set[str] = set()
    while frontier:
        tree.fetch(f"{RUST_CRATES}/{d}/BUILD.bazel" for d in frontier)
        nxt = set()
        for d in frontier:
            where = f"{RUST_CRATES}/{d}/BUILD.bazel"
            raw = tree.get(where)
            if raw is None:
                raise ClosureError(f"{where}: missing at the revision")
            text = raw.decode()
            name, version = regen._package_info(text, where)
            kept, dropped = _select_filtered_strings(text, where)
            deps = {c for c in map(_crate_dir, kept) if c} - {d}
            all_labels_dirs |= {c for c in map(_crate_dir, kept | dropped) if c}
            licenses = sorted(s.rsplit(":", 1)[1] for s in kept if s.startswith("@rules_license//licenses/spdx:"))
            crates[d] = {
                "dir": d, "kind": d.split("/")[0], "name": name, "version": version,
                "patched": d.split("/")[0] != "vendor",
                "proc_macro": "rust_proc_macro(" in text,
                "build_script": "cargo_build_script(" in text,
                "licenses": licenses,
                "in_cargo_lock": (name, version) in lock,
            }
            nxt |= deps
        frontier = sorted(nxt - set(crates))
    return {"direct": direct, "transitive": [crates[k] for k in sorted(crates)],
            "unfiltered_select_count": len(all_labels_dirs | set(crates))}


# --- lines and upstream Bazel ---------------------------------------------------------------


def crate_facts(tree: Tree, paths: list[str]) -> dict[str, dict]:
    """For each crate directory: .rs line count (not in subpackages) and upstream BUILD.bazel."""
    source = tree.source
    files = {}
    for p in paths:
        try:
            files[p] = regen._files_of(source, regen.Crate(p, "upstream"))
        except RegenError:
            files[p] = {}
    rs = sorted(f for fs in files.values() for f in fs if f.endswith(".rs"))
    tree.fetch(rs)
    out = {}
    for p in paths:
        lines = sum(tree.cache[f].count(b"\n") for f in files[p] if f.endswith(".rs") and tree.cache.get(f))
        out[p] = {"rs_lines": lines, "upstream_bazel": f"{p}/BUILD.bazel" in files[p]}
    return out


# --- report -----------------------------------------------------------------------------


def report(tree: Tree, roots: list[str], revision: str, idk: Path | None, name: str) -> dict:
    rep = walk(tree, roots, "fuchsia")
    upper = walk(tree, roots, "all")
    facts = crate_facts(tree, sorted({c["path"] for c in list(rep.crates.values()) + list(upper.crates.values())}))
    cio = crates_io(tree, rep)
    cio_upper = crates_io(tree, upper)

    def in_idk(kind: str, lib: str):
        return None if idk is None else (idk / kind / lib).is_dir()

    intree = []
    for path in sorted({c["path"] for c in rep.crates.values()}):
        targets = [c for c in rep.crates.values() if c["path"] == path]
        intree.append({"path": path, **facts[path],
                       "targets": sorted(({k: v for k, v in c.items() if k != "path"} for c in targets),
                                         key=lambda t: t["target"])})
    fidl = [{"library": k, **v, "in_idk": in_idk("fidl", k)} for k, v in sorted(rep.fidl.items())]
    bind = [{"library": k, **v, "in_idk": in_idk("bind", k)} for k, v in sorted(rep.bind.items())]
    upper_paths = {c["path"] for c in upper.crates.values()}
    gaps = evaluation_gaps(rep)
    counts = {
        "intree_crates": len(intree),
        "intree_crates_with_upstream_bazel": sum(1 for c in intree if c["upstream_bazel"]),
        "intree_rs_lines": sum(c["rs_lines"] for c in intree),
        "crates_io_direct_aliases": len(cio["direct"]),
        "crates_io_direct_crates": len({d["crate_dir"] for d in cio["direct"] if d["crate_dir"]}),
        # GN aliases upstream's Bazel alias file lacks: their crates are not followed.
        "crates_io_direct_without_bazel_alias": sum(1 for d in cio["direct"] if not d["crate_dir"]),
        "crates_io_transitive": len(cio["transitive"]),
        "crates_io_transitive_patched": sum(1 for c in cio["transitive"] if c["patched"]),
        "crates_io_transitive_proc_macro": sum(1 for c in cio["transitive"] if c["proc_macro"]),
        "crates_io_transitive_unfiltered_select": cio["unfiltered_select_count"],
        "fidl_libraries": len(fidl),
        "fidl_libraries_direct": sum(1 for f in fidl if f["direct_flavors"]),
        "fidl_libraries_not_in_idk": sum(1 for f in fidl if f["in_idk"] is False),
        "bind_libraries": len(bind),
        "native_targets": len(rep.native),
        # deps/public_deps entries of native (imported-template) leaves, not followed.
        "native_deps_not_followed": sum(n["deps_not_followed"] for n in rep.native.values()),
        "unresolved": len(rep.unresolved),
        "unknown_deps": sum(c["unknown_deps"] for c in rep.crates.values()),
        "evaluation_gaps": len(gaps),
    }
    upper_counts = {
        "intree_crates": len(upper_paths),
        "intree_rs_lines": sum(facts[p]["rs_lines"] for p in upper_paths),
        "crates_io_direct_aliases": len(cio_upper["direct"]),
        "crates_io_transitive": len(cio_upper["transitive"]),
        "fidl_libraries": len(upper.fidl),
        "only_in_upper_bound": {
            "intree": sorted(upper_paths - {c["path"] for c in intree}),
            "crates_io_direct": sorted(set(upper.third) - set(rep.third)),
            "fidl": sorted(set(upper.fidl) - set(rep.fidl)),
        },
    }
    return {
        "schema": 1,
        "name": name,
        "fuchsia_revision": revision,
        "roots": roots,
        "generated_by": "scripts/closure.py",
        "method": ("GN deps, public_deps, non_rust_deps and proc_macro_deps (not test_deps) from the "
                   "roots; conditions evaluated per toolchain (fuchsia, host), unknown ones followed both "
                   "ways; build arguments at their defaults except overlay_args; same-file templates "
                   "expanded; FIDL deps and the binding templates' deps followed per flavor "
                   "(closure.FIDL_FLAVORS); crates.io deps followed through upstream's crate_universe "
                   "BUILD files, select() limited to the Fuchsia targets and linux-x64 host; anything "
                   "not followed is listed in evaluation_gaps and counted in unknown_deps"),
        "overlay_args": OVERLAY_ARGS,
        "counts": counts,
        "upper_bound_counts": upper_counts,
        "intree": intree,
        "crates_io": cio,
        "fidl": fidl,
        "bind": bind,
        "native": [{"label": k, **v} for k, v in sorted(rep.native.items())],
        "unresolved": [{"label": k, **v} for k, v in sorted(rep.unresolved.items())],
        "conditionals": conditionals(rep, "fuchsia"),
        "evaluation_gaps": gaps,
        "import_errors": [{"file": k, "error": v} for k, v in sorted(rep.evaluated.import_errors.items())],
    }


def main(argv: list[str] | None = None, root: Path = ROOT, make_source=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("roots", nargs="+", help="GN labels to walk from")
    parser.add_argument("--out", type=Path, help="write the JSON report here (default: stdout)")
    parser.add_argument("--idk", type=Path, help="an extracted IDK, to mark libraries it has")
    parser.add_argument("--name", default="closure", help="the report's name field")
    args = parser.parse_args(argv)
    try:
        revision, _ = regen.read_lock(root)
        with tempfile.TemporaryDirectory(prefix="closure-") as tmp:
            source = (make_source(revision) if make_source
                      else regen.GitSource(regen.FUCHSIA_GIT, revision, Path(tmp) / "git"))
            data = report(Tree(source), args.roots, revision, args.idk, args.name)
    except (ClosureError, RegenError) as e:
        print(f"closure.py: {e}", file=sys.stderr)
        return 2
    text = json.dumps(data, indent=1, sort_keys=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        c = data["counts"]
        print(f"closure.py: {args.out}: {c['intree_crates']} in-tree crates, "
              f"{c['crates_io_direct_aliases']} direct crates.io aliases "
              f"({c['crates_io_transitive']} crates transitively), {c['fidl_libraries']} FIDL libraries")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
