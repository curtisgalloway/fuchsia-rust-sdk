# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""The vendored FIDL libraries and runtime crates match pilot 1's closure (milestones M8,
M8b; the driver transport's runtime, M9a).

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

# The driver transport's crates (fidl.gni with enable_rust_drivers; milestone M9a).
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
    """Every patch that marks a target Fuchsia-only (M8a; M9b) is for a crate the closure
    uses in the fuchsia context only (a proc macro beside it, as cm_rust's, is host code)."""
    contexts = {c["path"]: {ctx for t in c["targets"] if t["crate_type"] != "proc-macro" for ctx in t["contexts"]}
                for c in CLOSURE["intree"]}
    marker = '+    target_compatible_with = ["@platforms//os:fuchsia"],'
    patched = sorted({p.parent.relative_to(ROOT / regen.PATCHES).as_posix()
                      for p in (ROOT / regen.PATCHES).rglob("*.patch") if marker in p.read_text()})
    assert patched == ["src/lib/diagnostics/hierarchy/rust", "src/lib/diagnostics/log/types",
                       "src/lib/fdomain/client", "src/lib/fidl/rust/fidl", "src/lib/fuchsia-async",
                       "src/lib/fuchsia-sync", "src/sys/lib/cm_rust", "src/sys/lib/moniker"]
    for path in patched:
        assert contexts[path] == {"fuchsia"}, path
        build = (ROOT / regen.VENDOR_OUT / path / "BUILD.bazel").read_text()
        assert 'target_compatible_with = ["@platforms//os:fuchsia"],' in build, path


# --- rust_next (milestone M8b) --------------------------------------------------------

# rust_next's driver dep (fidl_rust_next.gni with contains_drivers; milestone M9a).
NEXT_DRIVER_TRANSPORT = {"//sdk/lib/driver/runtime/rust/fidl"}


def _rust_next_libraries() -> list[str]:
    return sorted(f["library"] for f in CLOSURE["fidl"] if "rust_next" in f["flavors"])


# fuchsia.power.broker's crates are visible only to upstream's packages (tests/fidl).
_RESTRICTED = {"fuchsia.power.broker"}


def test_rust_next_test_list_is_the_closures():
    text = (ROOT / "tests/fidl/BUILD.bazel").read_text()
    block = text.split("_RUST_NEXT_LIBRARIES = [", 1)[1].split("]", 1)[0]
    libs = re.findall(r'"([^"]+)"', block)
    assert libs == _rust_next_libraries()
    # 17 without contains_drivers (M8b) + fuchsia.driver.framework, fuchsia.power.broker (M9a).
    assert len(libs) == 19
    assert {f["library"] for f in CLOSURE["fidl"] if f["contains_drivers"]} == {
        "fuchsia.driver.framework", "fuchsia.power.broker"}
    # Every rust_next library the closure has uses rust_next_common too.
    assert all("rust_next_common" in f["flavors"] for f in CLOSURE["fidl"] if "rust_next" in f["flavors"])


def test_crate_names_next_names_both_crates_of_each_library():
    text = (ROOT / "tests/fidl/src/crate_names_next.rs").read_text()
    used = re.findall(r"^pub use (\w+);$", text, re.M)
    want = [n for lib in _rust_next_libraries() if lib not in _RESTRICTED
            for n in (f"fidl_next_{lib.replace('.', '_')}", f"fidl_next_common_{lib.replace('.', '_')}")]
    assert used == want
    # The names the closure's GN targets give these crates (fidl_rust_next.gni).
    assert "fidl_next_fuchsia_io" in used and "fidl_next_common_fuchsia_io" in used


def test_rust_next_flavor_runtime_crates_are_vendored():
    """The in-tree crates the rust_next bindings need, without the driver transport: the
    6 rust_next crates plus what M8a vendored (rust_constants, fuchsia-async, zx*)."""
    deps = _intree_deps()
    roots = set()
    for user, ds in deps.items():
        if user.startswith("//sdk/fidl/") and user.endswith(("_rust_next", "_rust_next_common")):
            roots |= {d for d in ds if d.split(":")[0] not in NEXT_DRIVER_TRANSPORT}
    seen, todo = set(), list(roots)
    while todo:
        label = todo.pop()
        if label not in seen:
            seen.add(label)
            todo += deps.get(label, ())
    paths = {label[2:].split(":")[0] for label in seen}
    assert paths == {"sdk/lib/fuchsia-loom", "src/lib/fidl/rust_next/fidl_next",
                     "src/lib/fidl/rust_next/fidl_next_bind", "src/lib/fidl/rust_next/fidl_next_codec",
                     "src/lib/fidl/rust_next/fidl_next_protocol", "src/lib/fidl/rust_next/fidl_next_util",
                     "src/lib/fidl/rust_constants", "src/lib/fuchsia-async", "src/lib/fuchsia-async-macro",
                     "src/lib/fuchsia-sync", "sdk/rust/zx", "sdk/rust/zx-status", "sdk/rust/zx-status-ext",
                     "sdk/rust/zx-sys", "sdk/rust/zx-types"}
    assert paths <= set(LISTED)
    assert all(LISTED[p] == "upstream" for p in paths)


# --- The driver transport's runtime (milestone M9a) -----------------------------------

DRIVER_RUNTIME = {
    "sdk/lib/async/rust", "sdk/lib/async/rust/dispatcher", "sdk/lib/async/rust/fidl",
    "sdk/lib/async/rust/sys", "sdk/lib/driver/runtime/rust", "sdk/lib/driver/runtime/rust/channel",
    "sdk/lib/driver/runtime/rust/core", "sdk/lib/driver/runtime/rust/env",
    "sdk/lib/driver/runtime/rust/fdf_sys", "sdk/lib/driver/runtime/rust/fidl",
    "src/lib/fidl/rust/fidl_driver",
}


def _closure_from(roots: set[str]) -> set[str]:
    deps = _intree_deps()
    seen, todo = set(), list(roots)
    while todo:
        label = todo.pop()
        if label not in seen:
            seen.add(label)
            todo += deps.get(label, ())
    return {label[2:].split(":")[0] for label in seen}


def test_driver_transport_runtime_crates_are_vendored_as_overlays():
    """What the driver transport adds to the bindings' closure (fidl_driver and fdf for
    the rust flavor, fdf_fidl for rust_next) is the 11 driver runtime crates, each an
    overlay; the rest of its closure was vendored by M8a/M8b."""
    driver = DRIVER_TRANSPORT | NEXT_DRIVER_TRANSPORT
    bindings = [ds for user, ds in _intree_deps().items() if user.startswith("//sdk/fidl/")]
    transport = _closure_from({d for ds in bindings for d in ds if d.split(":")[0] in driver})
    before = _closure_from({d for ds in bindings for d in ds if d.split(":")[0] not in driver})
    assert len(transport) > len(DRIVER_TRANSPORT | NEXT_DRIVER_TRANSPORT)
    env = "sdk/lib/driver/runtime/rust/env"
    assert transport - before == DRIVER_RUNTIME - {env}
    assert transport <= set(LISTED)
    assert {p for p in DRIVER_RUNTIME if LISTED[p] == "overlay"} == DRIVER_RUNTIME
    # fdf_env is in the closure through fdf_component (M9b) only, not the transport; M9a
    # vendors it with the other fdf* crates.
    (env_target,) = next(c["targets"] for c in CLOSURE["intree"] if c["path"] == env)
    assert env_target["used_by"] == ["//sdk/lib/driver/component/rust"]


def test_driver_runtime_overlays_are_fuchsia_only_like_their_closure_context():
    contexts = {c["path"]: {ctx for t in c["targets"] for ctx in t["contexts"]} for c in CLOSURE["intree"]}
    for path in DRIVER_RUNTIME:
        assert contexts[path] == {"fuchsia"}, path
        overlay = (ROOT / regen.OVERLAYS / path / "BUILD.bazel").read_text()
        assert overlay.count('target_compatible_with = ["@platforms//os:fuchsia"],') == 1, path
        assert (ROOT / regen.VENDOR_OUT / path / "BUILD.bazel").read_text() == overlay, path


def test_driver_runtime_overlays_name_the_closures_crates():
    """Each overlay's rustc_library has the crate name and target name GN gives it."""
    crates = {c["path"]: c["targets"] for c in CLOSURE["intree"]}
    for path in DRIVER_RUNTIME:
        (target,) = crates[path]
        overlay = (ROOT / regen.OVERLAYS / path / "BUILD.bazel").read_text()
        assert f'    name = "{target["target"]}",\n    crate_name = "{target["crate_name"]}",\n' in overlay, path
        assert f'    edition = "{target["edition"]}",' in overlay, path
        assert target["features"] == [] and "crate_features" not in overlay, path
