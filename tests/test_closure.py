# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/closure.py (milestone M6), on a fake GN tree laid out like fuchsia.git."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import closure
import gn_eval
import regen

REV = "c" * 40

CARGO_LOCK = '''\
version = 4

[[package]]
name = "anyhow"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "1111111111111111111111111111111111111111111111111111111111111111"

[[package]]
name = "unix-dep"
version = "0.1.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "2222222222222222222222222222222222222222222222222222222222222222"

[[package]]
name = "mac-dep"
version = "0.1.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "3333333333333333333333333333333333333333333333333333333333333333"

[[package]]
name = "syn"
version = "2.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "4444444444444444444444444444444444444444444444444444444444444444"

[[package]]
name = "cond"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "5555555555555555555555555555555555555555555555555555555555555555"

[[package]]
name = "libc"
version = "0.2.1"
'''


def crate_build(name: str, version: str, deps_select: str = "", macro: bool = False,
                license: str = "MIT") -> str:
    rule = "rust_proc_macro" if macro else "rust_library"
    return f'''\
load("@rules_rust//rust:defs.bzl", "{rule}")

package_info(
    name = "package_info",
    package_name = "{name}",
    package_version = "{version}",
)

license(
    name = "license",
    license_kinds = ["@rules_license//licenses/spdx:{license}"],
)

{rule}(
    name = "{name}",
    deps = {deps_select or "[]"},
)
'''


FILES = {
    # The driver root. test_deps are not followed.
    "drv/BUILD.gn": '''\
fuchsia_rust_driver("driver") {
  deps = [
    "//lib/a",
    "//fidl/fuchsia.foo:fuchsia.foo_rust",
    "//fidl/fuchsia.foo:fuchsia.foo_rust_next",
    "//bind/fuchsia.test:fuchsia.test_rust",
    "//third_party/rust_crates:anyhow",
  ]
  test_deps = [ "//lib/testonly" ]
}
rustc_test("driver_test") {
  deps = [ "//lib/testonly" ]
}
''',
    "lib/a/args.gni": '''\
declare_args() {
  a_use_cond = false
}
''',
    # bazel2gn style: deps in variables; a relative label; a group; proc macros; a
    # host-only dep; a build argument; a condition on something unknown.
    "lib/a/BUILD.gn": '''\
import("//lib/a/args.gni")

A_DEPS = [
  "sub",
  ":helper",
]
if (is_host) {
  A_DEPS += [ "//lib/hostonly" ]
}
if (a_use_cond) {
  A_DEPS += [ "//third_party/rust_crates:cond" ]
}
if (current_cpu == "arm64") {
  A_DEPS += [ "//lib/maybe" ]
}
rustc_library("a") {
  crate_name = "a_crate"
  edition = "2024"
  features = [ "x" ]
  deps = A_DEPS
  proc_macro_deps = [ "//lib/mac" ]
}
group("helper") {
  public_deps = [ "//lib/dylib" ]
}
''',
    "lib/a/sub/BUILD.gn": '''\
rustc_library("sub") {
  non_rust_deps = [ "//native/c" ]
  deps = [ "//lib/missing:nope" ]
}
''',
    "lib/a/sub/src/lib.rs": "fn a() {}\nfn b() {}\n",
    "lib/a/src/lib.rs": "pub fn f() {}\n",
    "lib/a/BUILD.bazel": "# upstream Bazel build\n",
    "lib/dylib/BUILD.gn": '''\
rustc_dylib("dylib") {
  deps = [
    "//third_party/rust_crates:libc",
    "//lib/maybe",
  ]
}
''',
    "lib/mac/BUILD.gn": '''\
rustc_macro("mac") {
  deps = [ "//third_party/rust_crates:syn" ]
  if (is_host) {
    deps += [ "//lib/hostonly" ]
  }
}
''',
    "lib/hostonly/BUILD.gn": 'rustc_library("hostonly") {\n}\n',
    "lib/maybe/BUILD.gn": 'rustc_library("maybe") {\n  deps = [ "$some_dir:x" ]\n}\n',
    "lib/testonly/BUILD.gn": 'rustc_library("testonly") {\n}\n',
    "native/c/BUILD.gn": 'source_set("c") {\n}\n',
    "fidl/fuchsia.foo/BUILD.gn": '''\
fidl("fuchsia.foo") {
  sdk_category = "partner"
  public_deps = [
    "//fidl/fuchsia.bar",
    "//zircon/vdso/zx",
  ]
  contains_drivers = true
  enable_rust_drivers = true
}
''',
    # What the FIDL binding templates add (closure.FIDL_FLAVORS), as small stubs.
    "zircon/vdso/zx/BUILD.gn": 'fidl("zx") {\n}\n',
    "sdk/rust/zx/BUILD.gn": 'rustc_library("zx") {\n}\n',
    "sdk/rust/zx-status/BUILD.gn": 'rustc_library("zx-status") {\n}\n',
    "sdk/rust/zx-types/BUILD.gn": 'rustc_library("zx-types") {\n}\n',
    "src/lib/fidl/rust/fidl/BUILD.gn": 'rustc_library("fidl") {\n}\n',
    "src/lib/fidl/rust/fidl_driver/BUILD.gn": 'rustc_library("fidl_driver") {\n}\n',
    "sdk/lib/driver/runtime/rust/BUILD.gn": 'rustc_library("rust") {\n}\n',
    "sdk/lib/driver/runtime/rust/fidl/BUILD.gn": 'rustc_library("fidl") {\n}\n',
    "src/lib/fidl/rust_next/fidl_next/BUILD.gn": 'rustc_library("fidl_next_internal") {\n}\n',
    "fidl/fuchsia.bar/BUILD.gn": 'fidl("fuchsia.bar") {\n  sdk_category = "host_tool"\n}\n',
    "bind/fuchsia.test/BUILD.gn": 'bind_library("fuchsia.test") {\n}\n',
    "third_party/rust_crates/BUILD.gn": '''\
group("anyhow") {
  public_deps = [ ":anyhow-v1_0_0" ]
}
group("libc") {
  public_deps = [ ":libc-v0_2_1" ]
}
''',
    "third_party/rust_crates/Cargo.lock": CARGO_LOCK,
    "third_party/rust_crates/vendor/BUILD.bazel": '''\
alias(
    name = "anyhow",
    actual = "//third_party/rust_crates/vendor/anyhow-1.0.0:anyhow",
    tags = ["manual"],
)

alias(
    name = "libc",
    actual = "//third_party/rust_crates/forks/libc-0.2.1:libc",
    tags = ["manual"],
)

alias(
    name = "syn",
    actual = "//third_party/rust_crates/vendor/syn-2.0.0:syn",
    tags = ["manual"],
)

alias(
    name = "cond",
    actual = "//third_party/rust_crates/vendor/cond-1.0.0:cond",
    tags = ["manual"],
)
''',
    # select(): the linux-host branch is followed, the macOS branch is not.
    "third_party/rust_crates/vendor/anyhow-1.0.0/BUILD.bazel": crate_build("anyhow", "1.0.0", '''select({
        "@rules_rust//rust/platform:x86_64-unknown-linux-gnu": [
            "//third_party/rust_crates/vendor/unix-dep-0.1.0:unix_dep",
        ],
        "@rules_rust//rust/platform:aarch64-apple-darwin": [
            "//third_party/rust_crates/vendor/mac-dep-0.1.0:mac_dep",
        ],
        "//conditions:default": [],
    })''', license="Apache-2.0"),
    "third_party/rust_crates/vendor/unix-dep-0.1.0/BUILD.bazel": crate_build("unix-dep", "0.1.0"),
    "third_party/rust_crates/vendor/mac-dep-0.1.0/BUILD.bazel": crate_build("mac-dep", "0.1.0"),
    "third_party/rust_crates/vendor/syn-2.0.0/BUILD.bazel": crate_build("syn", "2.0.0", macro=True),
    "third_party/rust_crates/vendor/cond-1.0.0/BUILD.bazel": crate_build("cond", "1.0.0"),
    "third_party/rust_crates/forks/libc-0.2.1/BUILD.bazel": crate_build("libc", "0.2.1"),
}

ROOTS = ["//drv:driver"]

FIDL_TEMPLATE_CRATES = ["sdk/lib/driver/runtime/rust", "sdk/lib/driver/runtime/rust/fidl", "sdk/rust/zx",
                        "sdk/rust/zx-status", "sdk/rust/zx-types", "src/lib/fidl/rust/fidl",
                        "src/lib/fidl/rust/fidl_driver", "src/lib/fidl/rust_next/fidl_next"]


@pytest.fixture
def upstream(tmp_path) -> Path:
    root = tmp_path / "fuchsia"
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


@pytest.fixture
def idk(tmp_path) -> Path:
    d = tmp_path / "idk"
    (d / "fidl" / "fuchsia.foo").mkdir(parents=True)
    (d / "bind" / "fuchsia.test").mkdir(parents=True)
    return d


def run(upstream: Path, idk: Path | None = None) -> dict:
    tree = closure.Tree(regen.DirSource(upstream, REV))
    return closure.report(tree, ROOTS, REV, idk, "test")


def by_path(data: dict) -> dict:
    return {c["path"]: c for c in data["intree"]}


def test_in_tree_crates_and_what_is_left_out(upstream):
    data = run(upstream)
    crates = by_path(data)
    assert sorted(crates) == ["drv", "lib/a", "lib/a/sub", "lib/dylib", "lib/hostonly", "lib/mac",
                              "lib/maybe", *FIDL_TEMPLATE_CRATES]
    # test_deps and test targets are not followed; a build argument's default (false)
    # keeps //third_party/rust_crates:cond out.
    assert "lib/testonly" not in crates
    assert "cond" not in {d["alias"] for d in data["crates_io"]["direct"]}
    a = crates["lib/a"]["targets"][0]
    assert (a["crate_name"], a["edition"], a["features"], a["crate_type"]) == ("a_crate", "2024", ["x"], "lib")
    assert crates["lib/a"]["upstream_bazel"] is True and crates["lib/a/sub"]["upstream_bazel"] is False
    # Lines of .rs, not counting subpackages (lib/a/sub has its own BUILD.gn).
    assert crates["lib/a"]["rs_lines"] == 1 and crates["lib/a/sub"]["rs_lines"] == 2


def test_rustc_dylib_is_followed(upstream):
    crates = by_path(run(upstream))
    t = crates["lib/dylib"]["targets"][0]
    assert (t["gn_template"], t["crate_type"]) == ("rustc_dylib", "dylib")
    # Reached through a group, which is not itself a crate.
    assert t["used_by"] == ["//lib/a"]


def test_used_by_lists_every_requester(upstream):
    crates = by_path(run(upstream))
    maybe = crates["lib/maybe"]["targets"][0]
    assert maybe["used_by"] == ["//lib/a", "//lib/dylib"]
    # A dep the evaluator cannot know is counted, not followed.
    assert maybe["unknown_deps"] == 1 and crates["lib/a"]["targets"][0]["unknown_deps"] == 0


def test_proc_macros_and_their_deps_are_host(upstream):
    data = run(upstream)
    crates = by_path(data)
    assert crates["lib/mac"]["targets"][0]["contexts"] == ["host"]
    assert crates["lib/mac"]["targets"][0]["crate_type"] == "proc-macro"
    # lib/a adds hostonly only under is_host; it is reached through the proc macro.
    assert crates["lib/hostonly"]["targets"][0]["contexts"] == ["host"]
    assert crates["lib/hostonly"]["targets"][0]["used_by"] == ["//lib/mac"]
    assert crates["lib/a"]["targets"][0]["contexts"] == ["fuchsia"]
    syn = next(d for d in data["crates_io"]["direct"] if d["alias"] == "syn")
    assert syn["contexts"] == ["host"]


def test_unknown_conditions_are_followed_and_reported(upstream):
    data = run(upstream)
    assert "lib/maybe" in by_path(data)
    conds = {(c["file"], c["line"]): c for c in data["conditionals"]}
    # The host is linux-x64 (C5), so only the Fuchsia side is unknown.
    assert conds[("lib/a/BUILD.gn", 13)]["outcome"] == {"fuchsia": "unknown", "host": "else"}
    assert conds[("lib/a/BUILD.gn", 13)]["condition"] == 'current_cpu == "arm64"'
    assert conds[("lib/a/BUILD.gn", 7)]["outcome"] == {"fuchsia": "else", "host": "taken"}
    assert conds[("lib/a/BUILD.gn", 10)]["build_args"] == {"fuchsia": {"a_use_cond": False},
                                                           "host": {"a_use_cond": False}}
    assert conds[("lib/mac/BUILD.gn", 3)]["in_target"] == "mac"
    # The test target's file is walked, but conditions inside unwalked targets are not listed.
    assert all(c["in_target"] != "driver_test" for c in data["conditionals"])


def test_overlay_args_override_upstream_defaults(upstream, monkeypatch):
    monkeypatch.setattr(closure, "OVERLAY_ARGS", {"a_use_cond": True})
    data = run(upstream)
    assert "cond" in {d["alias"] for d in data["crates_io"]["direct"]}
    assert data["overlay_args"] == {"a_use_cond": True}


def test_upper_bound_follows_every_condition(upstream):
    data = run(upstream)
    up = data["upper_bound_counts"]
    assert up["only_in_upper_bound"]["crates_io_direct"] == ["cond"]
    assert up["intree_crates"] == data["counts"]["intree_crates"]
    assert up["crates_io_transitive"] == data["counts"]["crates_io_transitive"] + 1


def test_fidl_and_bind_libraries(upstream, idk):
    data = run(upstream, idk)
    fidl = {f["library"]: f for f in data["fidl"]}
    # Each flavor brings its common sibling (M6a review finding 2).
    assert fidl["fuchsia.foo"]["flavors"] == ["rust", "rust_common", "rust_next", "rust_next_common"]
    assert fidl["fuchsia.foo"]["direct_flavors"] == ["rust", "rust_next"]
    assert fidl["fuchsia.foo"]["sdk_category"] == "partner"
    assert fidl["fuchsia.foo"]["contains_drivers"] is True
    # A FIDL dependency of a FIDL library gets the same flavors, but is not direct.
    assert fidl["fuchsia.bar"]["flavors"] == ["rust", "rust_common", "rust_next", "rust_next_common"]
    assert fidl["fuchsia.bar"]["direct_flavors"] == []
    assert fidl["fuchsia.bar"]["contains_drivers"] is False
    assert fidl["fuchsia.bar"]["used_by"] == ["fidl:fuchsia.bar", "fidl:fuchsia.foo"]
    # A public_dep on //zircon/vdso/zx is the zx-types crate, not a binding.
    assert "zx" not in fidl
    assert (fidl["fuchsia.foo"]["in_idk"], fidl["fuchsia.bar"]["in_idk"]) == (True, False)
    assert data["counts"]["fidl_libraries_not_in_idk"] == 1
    assert [(b["library"], b["in_idk"]) for b in data["bind"]] == [("fuchsia.test", True)]
    assert run(upstream)["fidl"][0]["in_idk"] is None  # no --idk: unknown


def test_native_and_unresolved(upstream):
    data = run(upstream)
    assert [(n["label"], n["gn_template"]) for n in data["native"]] == [("//native/c", "source_set")]
    assert [(u["label"], u["reason"], u["used_by"]) for u in data["unresolved"]] == [
        ("//lib/missing:nope", "no BUILD.gn", ["//lib/a/sub"])]


def test_fidl_binding_template_deps(upstream):
    """What build/rust/fidl_rust.gni and fidl_rust_next.gni add (M6a review finding 2)."""
    crates = by_path(run(upstream))
    used = {p: crates[p]["targets"][0]["used_by"] for p in FIDL_TEMPLATE_CRATES}
    foo = "//fidl/fuchsia.foo:fuchsia.foo_"
    # contains_drivers and enable_rust_drivers: fidl_driver and the runtime, for fuchsia.foo only.
    assert used["src/lib/fidl/rust/fidl_driver"] == [foo + "rust", foo + "rust_common"]
    assert used["sdk/lib/driver/runtime/rust/fidl"] == [foo + "rust_next", foo + "rust_next_common"]
    assert used["sdk/rust/zx-types"] == [foo + f for f in ("rust", "rust_common", "rust_next", "rust_next_common")]
    assert "//fidl/fuchsia.bar:fuchsia.bar_rust_next" in used["src/lib/fidl/rust_next/fidl_next"]
    assert "//fidl/fuchsia.bar:fuchsia.bar_rust" in used["sdk/rust/zx"]


def test_fidl_flavor_table_covers_host_and_unknown_flavors(upstream):
    # For the host, no zx and no driver crates.
    (upstream / "drv/BUILD.gn").write_text('''\
rustc_macro("driver") {
  deps = [ "//fidl/fuchsia.foo:fuchsia.foo_rust", "//fidl/fuchsia.foo:fuchsia.foo_rust_weird" ]
}
''')
    data = run(upstream)
    crates = by_path(data)
    assert "sdk/rust/zx" not in crates and "src/lib/fidl/rust/fidl_driver" not in crates
    assert [g["what"] for g in data["evaluation_gaps"]] == [
        "binding flavor 'rust_weird' is not modelled: its template deps are not followed"]


def test_forwarded_scope_and_same_file_template_in_the_walk(upstream):
    """The M6a review's vfs case: deps forwarded from a scope literal, a local template."""
    (upstream / "lib/dylib/BUILD.gn").write_text('''\
template("local_rust") {
  rustc_library(target_name) {
    deps = invoker.extra
  }
}
common = {
  deps = [ "//third_party/rust_crates:libc" ]
}
rustc_dylib("dylib") {
  forward_variables_from(common, "*")
  deps += [ "//lib/maybe", ":tmpl" ]
}
local_rust("tmpl") {
  extra = [ "//lib/hostonly" ]
}
rustc_library("opaque") {
  forward_variables_from(invoker, "*")
}
''')
    (upstream / "lib/a/BUILD.gn").write_text((upstream / "lib/a/BUILD.gn").read_text().replace(
        'public_deps = [ "//lib/dylib" ]', 'public_deps = [ "//lib/dylib", "//lib/dylib:opaque" ]'))
    data = run(upstream)
    crates = by_path(data)
    assert {t["target"] for t in crates["lib/dylib"]["targets"]} == {"dylib", "tmpl", "opaque"}
    tmpl = next(t for t in crates["lib/dylib"]["targets"] if t["target"] == "tmpl")
    assert tmpl["same_file_template"] == "local_rust"
    assert "fuchsia" in crates["lib/hostonly"]["targets"][0]["contexts"]
    assert "libc" in {d["alias"] for d in data["crates_io"]["direct"]}
    opaque = next(t for t in crates["lib/dylib"]["targets"] if t["target"] == "opaque")
    assert opaque["unknown_deps"] == 1
    assert data["counts"]["unknown_deps"] == 2  # opaque + lib/maybe's "$some_dir:x"
    assert any(g["in_target"] == "opaque" and "unknown scope" in g["what"]
               for g in data["evaluation_gaps"])


def test_real_vfs_build_file():
    """src/storage/lib/vfs/rust and src/storage/lib/trace at the release, unchanged."""
    root = Path(__file__).parent / "testdata" / "gn"
    vfs = (root / "vfs.BUILD.gn").read_text()
    args = gn_eval.evaluate(vfs, closure.ENVS["fuchsia"], "vfs").args
    r = gn_eval.evaluate(vfs, closure.ENVS["fuchsia"], "vfs", args)
    t = r.targets["vfs"]
    assert t.kind == "rustc_dylib" and t.scope["output_name"] == "vfs_rust"
    deps = t.scope["deps"]
    for d in ("//src/storage/lib/trace", "//third_party/rust_crates:itertools", "//src/lib/fuchsia-sync",
              "//sdk/fidl/fuchsia.io:fuchsia.io_rust_flex", "//src/lib/fdomain/client:flex_fidl"):
        assert d in deps
    assert "//third_party/rust_crates:log" not in deps  # vfs_rust_uses_log = is_host
    assert t.scope["public_deps"] == ["//zircon/system/ulib/trace-engine"]
    cond = [c for c in r.conditionals if c.text == "vfs_rust_uses_log"]
    assert [(c.outcome, c.target, c.args) for c in cond] == [("else", None, {"vfs_rust_uses_log": False})]
    host = gn_eval.evaluate(vfs, closure.ENVS["host"], "vfs", gn_eval.evaluate(vfs, closure.ENVS["host"], "vfs").args)
    assert host.targets["vfs"].kind == "rustc_library"
    assert "//third_party/rust_crates:log" in host.targets["vfs"].scope["deps"]
    trace = gn_eval.evaluate((root / "storage_trace.BUILD.gn").read_text(), closure.ENVS["fuchsia"], "trace")
    assert trace.targets["trace"].kind == "rustc_library"
    assert trace.targets["trace"].scope["deps"] == ["//src/lib/trace/rust:trace"]
    assert trace.targets["trace"].scope["name"] == "storage_trace"
    assert r.gaps == [] and trace.gaps == []


def test_crates_io_direct_and_transitive(upstream):
    data = run(upstream)
    direct = {d["alias"]: d for d in data["crates_io"]["direct"]}
    # bitflags, futures, static_assertions come from the FIDL templates; the fake Bazel
    # alias file lacks them, which the report counts instead of dropping.
    assert sorted(direct) == ["anyhow", "bitflags", "futures", "libc", "static_assertions", "syn"]
    assert direct["futures"]["crate_dir"] is None
    assert data["counts"]["crates_io_direct_without_bazel_alias"] == 3
    assert direct["anyhow"]["gn_target"] == "anyhow-v1_0_0"
    assert direct["libc"]["crate_dir"] == "forks/libc-0.2.1"
    trans = {c["dir"]: c for c in data["crates_io"]["transitive"]}
    assert sorted(trans) == ["forks/libc-0.2.1", "vendor/anyhow-1.0.0", "vendor/syn-2.0.0",
                             "vendor/unix-dep-0.1.0"]
    assert trans["forks/libc-0.2.1"]["patched"] and not trans["vendor/anyhow-1.0.0"]["patched"]
    assert trans["vendor/syn-2.0.0"]["proc_macro"] is True
    assert trans["vendor/anyhow-1.0.0"]["licenses"] == ["Apache-2.0"]
    assert trans["forks/libc-0.2.1"]["in_cargo_lock"] is False  # not a crates.io entry
    c = data["counts"]
    assert (c["crates_io_transitive"], c["crates_io_transitive_unfiltered_select"]) == (4, 5)
    assert (c["crates_io_transitive_patched"], c["crates_io_transitive_proc_macro"]) == (1, 1)


def test_labels():
    assert closure.parse_label("//a/b", "x") == ("a/b", "b", False)
    assert closure.parse_label("//a/b:c", "x") == ("a/b", "c", False)
    assert closure.parse_label(":c", "x/y") == ("x/y", "c", False)
    assert closure.parse_label("core", "x/y") == ("x/y/core", "core", False)
    assert closure.parse_label("../z:t", "x/y") == ("x/z", "t", False)
    assert closure.parse_label("//a:b($host_toolchain)", "x") == ("a", "b", True)
    with pytest.raises(closure.ClosureError, match="leaves the source tree"):
        closure.parse_label("../../..", "x")
    assert closure.label("a/b", "b") == "//a/b" and closure.label("a/b", "c") == "//a/b:c"


def test_gn_parse_error_names_the_file(upstream):
    (upstream / "lib/maybe/BUILD.gn").write_text('rustc_library("maybe") {\n  deps = [\n')
    with pytest.raises(closure.ClosureError, match=r"^lib/maybe/BUILD.gn:\d+"):
        run(upstream)


def test_main_writes_a_deterministic_report(upstream, idk, tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "overlay.lock.json").write_text(json.dumps({
        "fuchsia_revision": {"value": REV},
        "cargo_lock_sha256": {"value": hashlib.sha256(CARGO_LOCK.encode()).hexdigest()},
    }))
    out = tmp_path / "out" / "p.json"
    argv = ["--name", "p", "--idk", str(idk), "--out", str(out), *ROOTS]
    src = lambda rev: regen.DirSource(upstream, rev)  # noqa: E731
    assert closure.main(argv, root=root, make_source=src) == 0
    first = out.read_bytes()
    assert closure.main(argv, root=root, make_source=src) == 0
    assert out.read_bytes() == first
    data = json.loads(first)
    assert (data["name"], data["fuchsia_revision"], data["roots"]) == ("p", REV, ROOTS)
    assert "15 in-tree crates, 6 direct crates.io aliases (4 crates transitively)" in capsys.readouterr().out
    assert str(idk) not in first.decode()  # no local paths in the report
    (upstream / "lib/maybe/BUILD.gn").write_text("x = \n")
    assert closure.main(argv, root=root, make_source=src) == 2
    assert "closure.py: lib/maybe/BUILD.gn:" in capsys.readouterr().err
