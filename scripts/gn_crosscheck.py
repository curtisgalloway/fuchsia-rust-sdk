#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""GN parity check: each vendored in-tree crate compiles as its BUILD.gn says (M9b).

For every closure target (docs/closure/pilot1.json) of the given vendor/crates.txt
paths, it compares what Bazel compiles with the target of fuchsia.git's BUILD.gn at the
lock's revision, evaluated by closure.py's GN evaluator in the same context (fuchsia for
fuchsia_x64 and fuchsia_arm64; host for proc macros):

  crate name, crate type, edition     rustc's --crate-name, --crate-type, --edition (aquery)
  features                            rustc's --cfg feature="..." (aquery)
  Rust deps                           rustc's --extern names (aquery), against GN's deps,
                                      public_deps and proc_macro_deps as crate names
                                      (in-tree targets by their BUILD.gn, crates.io
                                      aliases by upstream's alias targets, FIDL bindings
                                      by flavor, groups expanded)
  crate root and sources              CrateInfo.root and .srcs (cquery), against GN's
                                      source_root (default src/lib.rs) and sources
  C deps                              each GN dep on a C library in NATIVE_DEPS must put
                                      that library in the target's CcInfo (cquery)

A GN dep it cannot resolve (not a Rust crate, FIDL binding, group, known C library or
known removed label) fails the check, as does a difference not in the allowlists below.

Not compared: GN configs and rustflags (optimization, lints, -Z flags) and Bazel's
rustc_flags; API-level and other non-feature cfgs; visibility, version and test targets
(with_unit_tests, test_deps); how dependents link a crate. Overlay fields such as
visibility are reviewed by hand (see the overlay headers).

Usage:
  gn_crosscheck.py <path>...   check these vendor/crates.txt paths
  gn_crosscheck.py --all       check every in-tree closure crate vendor/crates.txt lists
Exit status: 0 all agree, 1 a difference, 2 the check could not run.
Git access as regen.py (C1): one anonymous depth-1 blobless fetch, then blobs by ID.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import closure
import regen

ROOT = Path(__file__).resolve().parent.parent
BAZEL = ROOT / "scripts/bazel"
CLOSURE_FILE = "docs/closure/pilot1.json"
ALIAS_FILE = "third_party/crates/BUILD.vendor.bazel"

# GN template kind -> rustc crate type.
CRATE_TYPES = {"rustc_library": "rlib", "rustc_macro": "proc-macro", "rustc_dylib": "dylib"}
# Known deviations: "<path>:<GN target>" -> (GN crate type, Bazel crate type, why).
CRATE_TYPE_DEVIATIONS = {
    "src/storage/lib/vfs/rust:vfs": ("dylib", "rlib", "rules_rust has no dylib crate type (M9b)"),
}
# Upstream's Bazel target where its name differs from GN's (same crate).
BAZEL_NAMES = {"sdk/lib/c/rust:zx-libc": "rust"}
# GN C libraries -> the library file the IDK's prebuilt package links (in CcInfo).
NATIVE_DEPS = {
    "//sdk/lib/async": "libasync.a",
    "//sdk/lib/async-default": "libasync-default.so",
    "//sdk/lib/fdio": "libfdio.so",
    "//src/devices/bin/driver_runtime": "libdriver_runtime.so",
    "//src/devices/lib/driver:driver_runtime": "libdriver_runtime.so",
    "//zircon/system/ulib/sync": "libsync.a",
    "//zircon/system/ulib/trace-engine": "libtrace-engine.so",
}
# GN deps the overlay removes on purpose, with the reason.
REMOVED_DEPS = {
    "//sdk/lib/syslog:client_includes":
        "expect_includes (a manifest check), removed by patches/fuchsia/src/lib/diagnostics/log/rust (M9b)",
}
# FIDL binding flavor -> crate name, from the library name with "." -> "_".
FIDL_CRATES = {
    "rust": "fidl_{}", "rust_common": "fidl_{}_common", "rust_flex": "flex_{}",
    "rust_next": "fidl_next_{}", "rust_next_common": "fidl_next_common_{}",
}
CONFIGS = {"fuchsia": ("fuchsia_x64", "fuchsia_arm64"), "host": (None,)}
DEP_VARS = ("deps", "public_deps", "proc_macro_deps", "non_rust_deps")


class CheckError(Exception):
    """The check cannot run or cannot resolve an input; the message says which."""


@dataclass(frozen=True)
class Facts:
    crate: str
    crate_type: str
    edition: str | None
    features: tuple[str, ...]
    externs: frozenset[str]
    root: str
    srcs: tuple[str, ...]
    native: frozenset[str] = field(default_factory=frozenset)  # expected / present C libraries


@dataclass(frozen=True)
class Target:
    path: str
    gn_name: str
    ctx: str

    @property
    def key(self) -> str:
        return f"{self.path}:{self.gn_name}"

    @property
    def bazel_label(self) -> str:
        return f"//{regen.VENDOR_OUT}/{self.path}:{BAZEL_NAMES.get(self.key, self.gn_name)}"


# --- GN side ---------------------------------------------------------------------------


def _crate_name(scope: dict, name: str) -> str:
    for var in ("crate_name", "name"):
        if isinstance(scope.get(var), str):
            return scope[var]
    return name.replace("-", "_")


def gn_facts(ev: closure.Evaluated, t: Target, aliases: dict[str, str]) -> Facts:
    """What BUILD.gn says the crate is, in t.ctx. Raises CheckError on anything it cannot
    resolve."""
    res = ev.get(t.path, t.ctx)
    if res is None or t.gn_name not in res.targets:
        raise CheckError(f"//{t.key}: no such GN target in {t.ctx}")
    target = res.targets[t.gn_name]
    if target.kind not in CRATE_TYPES:
        raise CheckError(f"//{t.key}: GN template {target.kind} is not a crate kind this check knows")
    if target.unknown_forward:
        raise CheckError(f"//{t.key}: forwards variables from a scope the evaluator does not know")
    s = target.scope
    externs, native = set(), set()
    todo = [(d, t.path) for v in DEP_VARS for d in closure._strings(s.get(v))]
    unknown = sum(closure._unknowns(s.get(v)) for v in DEP_VARS)
    if unknown:
        raise CheckError(f"//{t.key}: {unknown} dep list entries the GN evaluator could not know")
    seen = set()
    while todo:
        dep, cur = todo.pop()
        p, n, _ = closure.parse_label(dep, cur)
        lab = closure.label(p, n)
        if lab in seen:
            continue
        seen.add(lab)
        if p == closure.RUST_CRATES:
            if n not in aliases:
                raise CheckError(f"//{t.key}: {dep}: no such alias in {ALIAS_FILE}")
            externs.add(aliases[n].rpartition(":")[2])
            continue
        if lab in NATIVE_DEPS:
            native.add(NATIVE_DEPS[lab])
            continue
        if lab in REMOVED_DEPS:
            continue
        dres = ev.get(p, t.ctx)
        if dres is None:
            raise CheckError(f"//{t.key}: {dep}: no BUILD.gn at //{p}")
        dt = dres.targets.get(n)
        if dt is None and t.ctx != "host":
            # GN builds proc macros in the host toolchain, and some BUILD.gn files define
            # them only there (`if (is_host)`).
            hres = ev.get(p, "host")
            ht = hres.targets.get(n) if hres else None
            if ht is not None and ht.kind == "rustc_macro":
                dt = ht
        if dt is not None and dt.kind in closure.RUST_KINDS:
            externs.add(_crate_name(dt.scope, n))
        elif dt is not None and dt.kind == "group":
            todo += [(d, p) for v in ("deps", "public_deps") for d in closure._strings(dt.scope.get(v))]
        elif dt is None and (fidl := closure._implicit(dres, n, "fidl")):
            base, flavor = fidl
            flavor = closure.canonical_flavor(flavor)
            if flavor not in FIDL_CRATES:
                raise CheckError(f"//{t.key}: {dep}: FIDL flavor {flavor} is not one this check knows")
            lib = dres.targets[base].scope.get("name")
            lib = lib if isinstance(lib, str) else base
            externs.add(FIDL_CRATES[flavor].format(lib.replace(".", "_")))
        else:
            kind = dt.kind if dt else "no such target"
            raise CheckError(f"//{t.key}: cannot resolve dep {dep} ({kind}); add it to NATIVE_DEPS "
                             "or REMOVED_DEPS with a reason, or teach the check its kind")
    base = f"{regen.VENDOR_OUT}/{t.path}"
    root = s.get("source_root") if isinstance(s.get("source_root"), str) else "src/lib.rs"
    edition = s.get("edition") if isinstance(s.get("edition"), str) else None
    return Facts(crate=_crate_name(s, t.gn_name), crate_type=CRATE_TYPES[target.kind], edition=edition,
                 features=tuple(sorted(closure._strings(s.get("features")))), externs=frozenset(externs),
                 root=posixpath.normpath(f"{base}/{root}"),
                 srcs=tuple(sorted(posixpath.normpath(f"{base}/{x}") for x in closure._strings(s.get("sources")))),
                 native=frozenset(native))


# --- Bazel side ------------------------------------------------------------------------


def _norm_label(label: str) -> str:
    return label.lstrip("@")


def rustc_facts(arguments: list[str]) -> dict:
    """crate, crate_type, edition, features, externs and root from a Rustc action's argv."""
    args = arguments[arguments.index("--") + 1:] if "--" in arguments else arguments

    def value(flag: str) -> str | None:
        return next((a.split("=", 1)[1] for a in args if a.startswith(flag + "=")), None)

    features = sorted(args[i + 1][len('feature="'):-1] for i, a in enumerate(args[:-1])
                      if a == "--cfg" and args[i + 1].startswith('feature="'))
    features += sorted(a[len('--cfg=feature="'):-1] for a in args if a.startswith('--cfg=feature="'))
    externs = {a[len("--extern="):].split("=", 1)[0] for a in args if a.startswith("--extern=")}
    externs.discard("proc_macro")  # rules_rust adds it to every proc macro
    roots = [a for a in args[1:] if a.endswith(".rs") and not a.startswith("-")]
    if len(roots) != 1:
        raise CheckError(f"cannot find the crate root in rustc's arguments ({roots})")
    return dict(crate=value("--crate-name"), crate_type=value("--crate-type"), edition=value("--edition"),
                features=tuple(sorted(features)), externs=frozenset(externs), root=roots[0])


def parse_aquery(data: dict) -> dict[str, dict]:
    """label -> rustc_facts, from `aquery --output=jsonproto` of Rustc actions."""
    labels = {t["id"]: _norm_label(t["label"]) for t in data.get("targets", [])}
    out: dict[str, dict] = {}
    for action in data.get("actions", []):
        label = labels[action["targetId"]]
        if label in out:
            raise CheckError(f"{label}: more than one Rustc action")
        out[label] = rustc_facts(action["arguments"])
    return out


# cquery --output=starlark: one JSON line per target with CrateInfo's sources and the
# C libraries in CcInfo.
_CQUERY = '''
def format(target):
    p = providers(target)
    keys = [k for k in p.keys() if k.endswith("%CrateInfo")]
    if not keys:
        return json.encode({"label": str(target.label), "crate": None})
    ci = p[keys[0]]
    libs = []
    cc = p.get("CcInfo")
    if cc:
        for li in cc.linking_context.linker_inputs.to_list():
            for lib in li.libraries:
                for f in (lib.static_library, lib.pic_static_library, lib.dynamic_library, lib.interface_library):
                    if f:
                        libs.append(f.basename)
    return json.encode({"label": str(target.label), "crate": ci.name, "root": ci.root.short_path,
                        "srcs": sorted([f.short_path for f in ci.srcs.to_list()]),
                        "libs": sorted(libs)})
'''


def parse_cquery(text: str) -> dict[str, dict]:
    out = {}
    for line in text.splitlines():
        if line.startswith("{"):
            d = json.loads(line)
            out[_norm_label(d["label"])] = d
    return out


def _bazel(*args: str) -> str:
    r = subprocess.run([str(BAZEL), *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join(r.stderr.splitlines()[-15:])
        raise CheckError(f"scripts/bazel {' '.join(args[:2])} failed:\n{tail}")
    return r.stdout


def bazel_facts(config: str | None, labels: list[str]) -> dict[str, Facts]:
    flags = ["--lockfile_mode=error"] + ([f"--config={config}"] if config else [])
    expr = " + ".join(labels)
    aq = parse_aquery(json.loads(_bazel("aquery", *flags, f'mnemonic("Rustc", {expr})', "--output=jsonproto")))
    with tempfile.TemporaryDirectory(prefix="gn-crosscheck-") as tmp:
        bzl = Path(tmp) / "format.cquery.bzl"
        bzl.write_text(_CQUERY)
        cq = parse_cquery(_bazel("cquery", *flags, expr, "--output=starlark", f"--starlark:file={bzl}"))
    out = {}
    for label in labels:
        if label not in aq or label not in cq or cq[label]["crate"] is None:
            raise CheckError(f"{label}: no Rustc action or CrateInfo under {config or 'host'}")
        a, c = aq[label], cq[label]
        out[label] = Facts(crate=a["crate"], crate_type=a["crate_type"], edition=a["edition"],
                           features=a["features"], externs=a["externs"], root=c["root"],
                           srcs=tuple(c["srcs"]), native=frozenset(c["libs"]))
    return out


# --- comparison ------------------------------------------------------------------------


def compare(t: Target, gn: Facts, bz: Facts) -> list[str]:
    """Differences, each a line; known deviations are not differences."""
    diffs = []
    for name in ("crate", "edition", "features", "root", "srcs"):
        if getattr(gn, name) != getattr(bz, name):
            diffs.append(f"{name}: bazel {getattr(bz, name)} gn {getattr(gn, name)}")
    want_type = gn.crate_type
    if t.key in CRATE_TYPE_DEVIATIONS:
        gn_type, bz_type, _ = CRATE_TYPE_DEVIATIONS[t.key]
        if gn.crate_type != gn_type:
            diffs.append(f"crate_type: GN has {gn.crate_type}, the allowlisted deviation expects {gn_type}")
        want_type = bz_type
    if bz.crate_type != want_type:
        diffs.append(f"crate_type: bazel {bz.crate_type} gn {gn.crate_type}")
    if gn.externs != bz.externs:
        diffs.append(f"externs: bazel only {sorted(bz.externs - gn.externs)}, gn only {sorted(gn.externs - bz.externs)}")
    if missing := sorted(gn.native - bz.native):
        diffs.append(f"C libraries GN links but CcInfo lacks: {missing}")
    return diffs


def closure_targets(paths: list[str], closure_data: dict) -> list[Target]:
    by_path = {c["path"]: c for c in closure_data["intree"]}
    out = []
    for path in paths:
        if path not in by_path:
            raise CheckError(f"{path}: not an in-tree crate of {CLOSURE_FILE}")
        for t in by_path[path]["targets"]:
            for ctx in t["contexts"]:
                out.append(Target(path, t["target"], ctx))
    return out


def run(targets: list[Target], ev: closure.Evaluated, aliases: dict[str, str], facts_for) -> int:
    """Compare and print one line per (target, config); returns the number that differ.
    `facts_for(config, labels)` gives the Bazel side (bazel_facts, or a stub in tests)."""
    gn = {t: gn_facts(ev, t, aliases) for t in targets}
    bad = 0
    for ctx, configs in CONFIGS.items():
        group = [t for t in targets if t.ctx == ctx]
        if not group:
            continue
        for config in configs:
            bz = facts_for(config, sorted({t.bazel_label for t in group}))
            for t in group:
                diffs = compare(t, gn[t], bz[t.bazel_label])
                note = f" (allowed: {CRATE_TYPE_DEVIATIONS[t.key][2]})" if t.key in CRATE_TYPE_DEVIATIONS else ""
                f = bz[t.bazel_label]
                print(f"{t.bazel_label} [{config or 'host'}]: {'OK' if not diffs else 'DIFF'} "
                      f"crate={f.crate} type={f.crate_type}{note} externs={len(f.externs)} "
                      f"srcs={len(f.srcs)} features={list(f.features)} c_libs={sorted(gn[t].native)}"
                      + "".join(f"\n    {d}" for d in diffs))
                bad += bool(diffs)
    return bad


def main(argv: list[str] | None = None, make_source=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*", help="vendor/crates.txt paths to check")
    parser.add_argument("--all", action="store_true", help="every in-tree closure crate listed")
    args = parser.parse_args(argv)
    try:
        closure_data = json.loads((ROOT / CLOSURE_FILE).read_text())
        listed = {c.path for c in regen.read_vendor_list((ROOT / regen.VENDOR_LIST).read_text())}
        if args.all == bool(args.paths):
            parser.error("give paths or --all")
        paths = sorted(p for p in (c["path"] for c in closure_data["intree"]) if p in listed) if args.all else args.paths
        unlisted = [p for p in paths if p not in listed]
        if unlisted:
            raise CheckError(f"not listed in {regen.VENDOR_LIST}: {', '.join(unlisted)}")
        targets = closure_targets(paths, closure_data)
        aliases = regen.parse_aliases((ROOT / ALIAS_FILE).read_text())
        revision, _ = regen.read_lock(ROOT)
        with tempfile.TemporaryDirectory(prefix="gn-crosscheck-") as tmp:
            source = (make_source(revision) if make_source
                      else regen.GitSource(regen.FUCHSIA_GIT, revision, Path(tmp) / "git"))
            ev = closure.Evaluated(closure.Tree(source), "fuchsia")
            # One batched read of the BUILD.gn files the deps mostly live in (every listed
            # directory) and their imports; the rest are read as needed.
            ev.tree.fetch(f"{p}/BUILD.gn" for p in sorted(listed))
            ev.prefetch(sorted(listed))
            bad = run(targets, ev, aliases, bazel_facts)
    except (CheckError, closure.ClosureError, regen.RegenError) as e:
        print(f"gn_crosscheck.py: {e}", file=sys.stderr)
        return 2
    print(f"gn_crosscheck.py: {len(paths)} crate directories, {len(targets)} targets: "
          + ("all agree with BUILD.gn" if not bad else f"{bad} (target, config) pairs differ"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
