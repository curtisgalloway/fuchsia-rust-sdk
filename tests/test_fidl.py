# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""The vendored FIDL libraries and runtime crates match pilot 1's closure (milestone M8).

Consistency checks between committed files: vendor/crates.txt and tests/fidl/BUILD.bazel
against docs/closure/pilot1.json, and the Fuchsia-only patches against the closure's
contexts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import regen

ROOT = Path(__file__).resolve().parent.parent
CLOSURE = json.loads((ROOT / "docs/closure/pilot1.json").read_text())
LISTED = {c.path: c.build for c in regen.read_vendor_list((ROOT / regen.VENDOR_LIST).read_text())}

# The driver transport's crates (fidl.gni with enable_rust_drivers; milestone M9).
DRIVER_TRANSPORT = {"//src/lib/fidl/rust/fidl_driver", "//sdk/lib/driver/runtime/rust"}


def _norm(label: str) -> str:
    """"//a/b" -> "//a/b:b" (GN's implicit target name)."""
    return label if ":" in label or not label.startswith("//") else f"{label}:{label.rsplit('/', 1)[1]}"


def _intree_deps() -> dict[str, set[str]]:
    """label -> the in-tree crate labels it depends on (inverting the closure's used_by)."""
    deps: dict[str, set[str]] = {}
    for crate in CLOSURE["intree"]:
        for t in crate["targets"]:
            for user in t["used_by"]:
                deps.setdefault(_norm(user), set()).add(f"//{crate['path']}:{t['target']}")
    return deps


def test_every_closure_library_is_vendored_as_idk_or_upstream():
    fidl = {f"sdk/fidl/{f['library']}": ("idk" if f["in_idk"] else "upstream") for f in CLOSURE["fidl"]}
    listed = {p: b for p, b in LISTED.items() if p.startswith("sdk/fidl/")}
    assert listed == fidl
    # zx: the FIDL library //zircon/vdso/zx, which libraries name as a dep (from the IDK).
    assert LISTED["zircon/vdso/zx"] == "idk"
    assert [p for p, b in LISTED.items() if b == "idk"] == sorted(p for p, b in fidl.items() if b == "idk") + [
        "zircon/vdso/zx"]


def test_fidl_test_package_lists_the_closures_libraries():
    text = (ROOT / "tests/fidl/BUILD.bazel").read_text()
    block = text.split("_LIBRARIES = [", 1)[1].split("]", 1)[0]
    assert re.findall(r'"([^"]+)"', block) == sorted(f["library"] for f in CLOSURE["fidl"])


def test_rust_flavor_runtime_crates_are_vendored():
    """The in-tree crates the `rust` and `rust_common` bindings need, without the driver
    transport, are all listed (fidl, rust_constants, fuchsia-async(-macro), fuchsia-sync, zx*)."""
    deps = _intree_deps()
    roots = set()
    for user, ds in deps.items():
        if user.startswith("//sdk/fidl/") and user.endswith(("_rust", "_rust_common")):
            roots |= {d for d in ds if d.split(":")[0] not in DRIVER_TRANSPORT}
    seen, todo = set(), list(roots)
    while todo:
        label = todo.pop()
        if label not in seen:
            seen.add(label)
            todo += deps.get(label, ())
    paths = {label[2:].split(":")[0] for label in seen}
    assert paths == {"sdk/rust/zx", "sdk/rust/zx-status", "sdk/rust/zx-status-ext", "sdk/rust/zx-sys",
                     "sdk/rust/zx-types", "src/lib/fidl/rust/fidl", "src/lib/fidl/rust_constants",
                     "src/lib/fuchsia-async", "src/lib/fuchsia-async-macro", "src/lib/fuchsia-sync"}
    assert paths <= set(LISTED)


def test_fuchsia_only_patches_are_for_crates_used_only_on_fuchsia():
    contexts = {c["path"]: {ctx for t in c["targets"] for ctx in t["contexts"]} for c in CLOSURE["intree"]}
    patched = sorted(p.parent.relative_to(ROOT / regen.PATCHES).as_posix()
                     for p in (ROOT / regen.PATCHES).rglob("*-fuchsia-only.patch"))
    assert patched == ["src/lib/fidl/rust/fidl", "src/lib/fuchsia-async", "src/lib/fuchsia-sync"]
    for path in patched:
        assert contexts[path] == {"fuchsia"}, path
        build = (ROOT / regen.VENDOR_OUT / path / "BUILD.bazel").read_text()
        assert 'target_compatible_with = ["@platforms//os:fuchsia"],' in build, path
