# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Pilot 1's in-tree crates vendored in milestones M9b and M9c match its closure.

Consistency checks between committed files: vendor/crates.txt, overlays/, patches/ and
the generated vendor/fuchsia/ against docs/closure/pilot1.json. The field-by-field
comparison with BUILD.gn (names, features, deps, sources) was run against the build
itself (scripts/gn_crosscheck.py; docs/evidence/M9b.md, M9c.md); these tests keep what
the files can show.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import regen

ROOT = Path(__file__).resolve().parent.parent
CLOSURE = json.loads((ROOT / "docs/closure/pilot1.json").read_text())
INTREE = {c["path"]: c for c in CLOSURE["intree"]}
LISTED = {c.path: c.build for c in regen.read_vendor_list((ROOT / regen.VENDOR_LIST).read_text())}

# The 35 crates of M9b: 28 with upstream's BUILD.bazel and 7 overlays.
M9B_OVERLAYS = {
    "src/lib/detect-stall", "src/lib/fuchsia-component", "src/lib/fuchsia-component/escrow",
    "src/lib/fuchsia-component/runtime", "src/lib/fuchsia-component/server", "src/storage/lib/trace",
    "src/storage/lib/vfs/rust",
}
M9B_UPSTREAM = {
    "sdk/lib/c/rust", "src/lib/buf-read-ext", "src/lib/diagnostics/hierarchy/rust",
    "src/lib/diagnostics/inspect/contrib/rust", "src/lib/diagnostics/inspect/derive",
    "src/lib/diagnostics/inspect/derive/macro", "src/lib/diagnostics/inspect/format/rust",
    "src/lib/diagnostics/inspect/rust", "src/lib/diagnostics/log/encoding/rust",
    "src/lib/diagnostics/log/rust", "src/lib/diagnostics/log/types", "src/lib/diagnostics/selectors",
    "src/lib/directed_graph", "src/lib/fdio/rust", "src/lib/fdomain/client", "src/lib/from-enum",
    "src/lib/fuchsia-component/client", "src/lib/fuchsia-component/directory", "src/lib/fuchsia-fs",
    "src/lib/fuchsia-runtime", "src/lib/injectable-time", "src/lib/trace/rust",
    "src/storage/lib/vfs/rust/name", "src/sys/lib/cm_fidl_validator", "src/sys/lib/cm_graph",
    "src/sys/lib/cm_rust", "src/sys/lib/cm_types", "src/sys/lib/moniker",
}
# M9c's six overlays (none has an upstream BUILD.bazel). Not vendored: the pilot driver
# itself (M10).
M9C = {
    "src/lib/elf_parse", "src/lib/process_builder", "src/sys/lib/namespace",
    "src/lib/diagnostics/inspect/runtime/rust", "src/lib/fuchsia-component/config",
    "sdk/lib/driver/component/rust",
}
PILOT_DRIVER = "examples/drivers/simple/rust"


def test_m9b_set_is_listed_with_its_mode():
    assert len(M9B_UPSTREAM) == 28 and len(M9B_OVERLAYS) == 7
    assert {p: LISTED.get(p) for p in M9B_UPSTREAM} == dict.fromkeys(M9B_UPSTREAM, "upstream")
    assert {p: LISTED.get(p) for p in M9B_OVERLAYS} == dict.fromkeys(M9B_OVERLAYS, "overlay")


def test_m9c_set_is_listed_as_overlays():
    assert len(M9C) == 6
    assert {p: LISTED.get(p) for p in M9C} == dict.fromkeys(M9C, "overlay")
    assert not any(INTREE[p]["upstream_bazel"] for p in M9C)


def test_every_closure_crate_but_the_driver_is_listed():
    """After M9c, pilot 1's in-tree set is complete but for the driver (M10)."""
    assert PILOT_DRIVER in INTREE and PILOT_DRIVER not in LISTED
    assert set(INTREE) - {PILOT_DRIVER} <= set(LISTED)
    assert len(set(INTREE) - {PILOT_DRIVER}) == 68  # 16 (M5-M8b) + 11 (M9a) + 35 (M9b) + 6


def test_upstream_mode_only_where_upstream_has_bazel():
    """closure.py recorded which directories have a BUILD.bazel. fuchsia-component has one,
    but it is an empty stub filegroup, so it is an overlay: regen.py checks on every run
    that upstream's file there still builds no Rust (check_upstream_stub; test_regen.py)."""
    for path in M9B_UPSTREAM:
        assert INTREE[path]["upstream_bazel"], path
    assert {p for p in M9B_OVERLAYS if INTREE[p]["upstream_bazel"]} == {"src/lib/fuchsia-component"}


# select() keys that match under a Fuchsia target configuration; any other key but
# //conditions:default (e.g. //rules:is_host_os) does not.
_FUCHSIA_KEYS = ("@platforms//os:fuchsia",)


def _value(node: ast.AST, variables: dict[str, ast.AST]):
    """A BUILD expression's value under a Fuchsia configuration: literals, top-level
    variables, list concatenation, and select() (the Fuchsia key, else the default)."""
    if isinstance(node, ast.Name) and node.id in variables:
        return _value(variables[node.id], variables)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _value(node.left, variables) + _value(node.right, variables)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "select":
        branches = {ast.literal_eval(k): v for k, v in zip(node.args[0].keys, node.args[0].values)}
        key = next((k for k in _FUCHSIA_KEYS if k in branches), "//conditions:default")
        return _value(branches[key], variables)
    return ast.literal_eval(node)


def _rust_calls(path: str) -> dict[str, dict]:
    """name -> keyword arguments of each rustc_* call in a vendored BUILD file, evaluated
    as a Fuchsia build sees them (_value)."""
    tree = ast.parse((ROOT / regen.VENDOR_OUT / path / "BUILD.bazel").read_text())
    variables = {n.targets[0].id: n.value for n in tree.body
                 if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.startswith("rustc_"):
            kw = {k.arg: _value(k.value, variables) for k in node.keywords
                  if k.arg not in ("visibility", "target_compatible_with")}
            out[kw["name"]] = kw
    return out


def test_overlays_are_copied_verbatim_and_fuchsia_only():
    for path in M9B_OVERLAYS | M9C:
        overlay = (ROOT / regen.OVERLAYS / path / "BUILD.bazel").read_text()
        assert (ROOT / regen.VENDOR_OUT / path / "BUILD.bazel").read_text() == overlay, path
        assert overlay.count('target_compatible_with = ["@platforms//os:fuchsia"],') == 1, path
        assert {ctx for t in INTREE[path]["targets"] for ctx in t["contexts"]} == {"fuchsia"}, path


def test_overlays_name_the_closures_crates_and_features():
    """Target name, crate name, edition and features as GN gives them (closure.py's
    evaluation, including storage_trace's same-file template: feature "tracing")."""
    for path in M9B_OVERLAYS | M9C:
        (target,) = INTREE[path]["targets"]
        (kw,) = _rust_calls(path).values()
        assert (kw["name"], kw["crate_name"], kw["edition"]) == \
               (target["target"], target["crate_name"], target["edition"]), path
        assert kw.get("crate_features", []) == target["features"], path
    assert INTREE["src/storage/lib/trace"]["targets"][0]["features"] == ["tracing"]


def test_vfs_is_a_gn_dylib_built_as_an_rlib():
    """Decision (M9b): rules_rust has no dylib crate type; the overlay documents it."""
    (target,) = INTREE["src/storage/lib/vfs/rust"]["targets"]
    assert (target["gn_template"], target["crate_type"]) == ("rustc_dylib", "dylib")
    overlay = (ROOT / regen.OVERLAYS / "src/storage/lib/vfs/rust/BUILD.bazel").read_text()
    assert "rustc_library(" in overlay and "builds an rlib" in overlay


def test_upstream_crates_define_the_closures_targets():
    """Each closure target of an upstream-mode crate exists with GN's crate name and
    features, select()s evaluated for Fuchsia (hierarchy, log/types, cm_rust and moniker
    select their features). zx-libc is the one whose Bazel target name differs from GN's."""
    renamed = {("sdk/lib/c/rust", "zx-libc"): "rust"}
    for path in M9B_UPSTREAM:
        calls = _rust_calls(path)
        for t in INTREE[path]["targets"]:
            kw = calls[renamed.get((path, t["target"]), t["target"])]
            assert kw.get("crate_name", t["target"].replace("-", "_")) == t["crate_name"], (path, t["target"])
            assert kw.get("crate_features", []) == t["features"], (path, t["target"])


def test_m9b_crates_have_no_test_deps():
    """Unit tests are M16: patches empty test_deps, so regen.py fetches no crate outside
    the closure for them (the crate set is checked in test_crates_closure.py)."""
    for path in M9B_UPSTREAM:
        for name, kw in _rust_calls(path).items():
            assert kw.get("test_deps", []) == [], (path, name)


def test_m9b_patches_are_for_upstream_crates():
    patched = {p.parent.relative_to(ROOT / regen.PATCHES).as_posix()
               for p in (ROOT / regen.PATCHES).rglob("*.patch")}
    m9b = patched & (M9B_UPSTREAM | M9B_OVERLAYS)
    assert m9b <= M9B_UPSTREAM
    assert len(m9b) == 17


def test_inspect_runtime_group_is_an_alias_without_client_includes():
    """GN's group("rust") is :lib (visibility ":*") plus //sdk/lib/inspect:client_includes,
    an expect_includes manifest check the overlay does not translate (M9c); dependents
    name the group, which is an alias here."""
    path = "src/lib/diagnostics/inspect/runtime/rust"
    (target,) = INTREE[path]["targets"]
    assert (target["target"], target["crate_name"]) == ("lib", "inspect_runtime")
    tree = ast.parse((ROOT / regen.OVERLAYS / path / "BUILD.bazel").read_text())
    aliases = {kw["name"]: kw for kw in (
        {k.arg: ast.literal_eval(k.value) for k in n.keywords}
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "alias")}
    assert aliases == {"rust": {"name": "rust", "actual": ":lib", "visibility": ["//visibility:public"]}}
    overlay = (ROOT / regen.OVERLAYS / path / "BUILD.bazel").read_text()
    assert "client_includes" in overlay  # documented in the header
    assert '"//vendor/fuchsia/sdk/lib/inspect' not in overlay


def test_m9c_overlays_need_no_patch():
    patched = {p.parent.relative_to(ROOT / regen.PATCHES).as_posix()
               for p in (ROOT / regen.PATCHES).rglob("*.patch")}
    assert not patched & M9C
