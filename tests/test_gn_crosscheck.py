# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""scripts/gn_crosscheck.py: GN evaluation, rustc argument parsing, comparison (M9b).

The Bazel side is stubbed; the live run over the vendored crates is recorded in
docs/evidence/M9b.md and M9c.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import closure
import gn_crosscheck as gc
import regen

REV = "0" * 40
ALIASES = {"futures": "//vendor/futures-0.3.31:futures", "paste": "//vendor/paste-1.0.15:paste"}

A_GN = '''
rustc_library("a") {
  name = "a_crate"
  edition = "2024"
  features = [ "x" ]
  sources = [ "src/lib.rs", "src/m.rs" ]
  deps = [
    ":g",
    "//sdk/fidl/fuchsia.x:fuchsia.x_rust_flex",
    "//sdk/lib/fdio",
    "//sdk/lib/syslog:client_includes",
    "//src/b",
    "//third_party/rust_crates:futures",
    "//src/m:the-macro",
  ]
}
group("g") {
  public_deps = [ "//src/c:c" ]
}
'''
TREE = {
    "src/a/BUILD.gn": A_GN,
    "src/b/BUILD.gn": 'rustc_library("b") {\n  edition = "2024"\n  sources = [ "src/lib.rs" ]\n}\n',
    "src/c/BUILD.gn": 'rustc_library("c") {\n  crate_name = "see"\n  edition = "2024"\n}\n',
    # Defined only for the host toolchain, as some proc macros are upstream.
    "src/m/BUILD.gn": 'if (is_host) {\n  rustc_macro("the-macro") {\n    edition = "2024"\n  }\n}\n',
    "sdk/fidl/fuchsia.x/BUILD.gn": 'fidl("fuchsia.x") {\n  sources = [ "x.fidl" ]\n}\n',
    "sdk/lib/fdio/BUILD.gn": 'zx_library("fdio") {\n}\n',
    "sdk/lib/syslog/BUILD.gn": 'expect_includes("client_includes") {\n}\n',
    "src/bad/BUILD.gn": 'rustc_library("bad") {\n  edition = "2024"\n  deps = [ "//src/cc:lib" ]\n}\n',
    "src/cc/BUILD.gn": 'source_set("lib") {\n}\n',
}


@pytest.fixture
def ev(tmp_path: Path) -> closure.Evaluated:
    for rel, text in TREE.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return closure.Evaluated(closure.Tree(regen.DirSource(tmp_path, REV)), "fuchsia")


def test_gn_facts_resolve_every_kind_of_dep(ev):
    f = gc.gn_facts(ev, gc.Target("src/a", "a", "fuchsia"), ALIASES)
    assert (f.crate, f.crate_type, f.edition, f.features) == ("a_crate", "rlib", "2024", ("x",))
    # In-tree crates by their BUILD.gn crate name, a group expanded, a FIDL flex crate,
    # a crates.io alias by its target, a host-only proc macro; fdio is a C library and
    # syslog:client_includes a known removal.
    assert f.externs == {"b", "see", "flex_fuchsia_x", "futures", "the_macro"}
    assert f.native == {"libfdio.so"}
    assert f.root == "vendor/fuchsia/src/a/src/lib.rs"
    assert f.srcs == ("vendor/fuchsia/src/a/src/lib.rs", "vendor/fuchsia/src/a/src/m.rs")


def test_an_unresolvable_dep_fails(ev):
    with pytest.raises(gc.CheckError, match=r"//src/bad:bad: cannot resolve dep //src/cc:lib \(source_set\)"):
        gc.gn_facts(ev, gc.Target("src/bad", "bad", "fuchsia"), ALIASES)
    with pytest.raises(gc.CheckError, match="no such alias"):
        gc.gn_facts(ev, gc.Target("src/a", "a", "fuchsia"), {})


ARGV = ["process_wrapper", "--arg-file", "x", "--", "rustc", "vendor/fuchsia/src/a/src/lib.rs",
        "--crate-name=a_crate", "--crate-type=rlib", "--cfg", 'feature="x"', "--edition=2024",
        "--extern=b=out/libb.rlib", "--extern=futures=out/libfutures.rlib", "--extern=proc_macro",
        "--cfg=fuchsia_api_level_at_least=\"4\""]


def test_rustc_facts_and_aquery_parsing():
    f = gc.rustc_facts(ARGV)
    assert f == dict(crate="a_crate", crate_type="rlib", edition="2024", features=("x",),
                     externs=frozenset({"b", "futures"}), root="vendor/fuchsia/src/a/src/lib.rs")
    data = {"targets": [{"id": 1, "label": "@@//vendor/fuchsia/src/a:a"}],
            "actions": [{"targetId": 1, "arguments": ARGV}]}
    assert gc.parse_aquery(data) == {"//vendor/fuchsia/src/a:a": f}
    with pytest.raises(gc.CheckError, match="more than one Rustc action"):
        gc.parse_aquery({**data, "actions": data["actions"] * 2})


def _facts(**kw) -> gc.Facts:
    base = dict(crate="a_crate", crate_type="rlib", edition="2024", features=("x",),
                externs=frozenset({"b"}), root="r.rs", srcs=("r.rs",), native=frozenset({"libfdio.so"}))
    return gc.Facts(**{**base, **kw})


def test_compare_reports_differences_and_allows_only_listed_deviations():
    t = gc.Target("src/a", "a", "fuchsia")
    assert gc.compare(t, _facts(), _facts(native=frozenset({"libfdio.so", "libc.so"}))) == []
    diffs = gc.compare(t, _facts(), _facts(features=(), externs=frozenset({"b", "log"}), native=frozenset()))
    assert any(d.startswith("features:") for d in diffs)
    assert "externs: bazel only ['log'], gn only []" in diffs
    assert "C libraries GN links but CcInfo lacks: ['libfdio.so']" in diffs
    # A dylib built as an rlib differs, except where CRATE_TYPE_DEVIATIONS allows it.
    assert gc.compare(t, _facts(crate_type="dylib"), _facts()) == ["crate_type: bazel rlib gn dylib"]
    vfs = gc.Target("src/storage/lib/vfs/rust", "vfs", "fuchsia")
    assert gc.compare(vfs, _facts(crate_type="dylib"), _facts()) == []
    assert gc.compare(vfs, _facts(crate_type="rlib"), _facts()) == [
        "crate_type: GN has rlib, the allowlisted deviation expects dylib"]
    assert gc.compare(vfs, _facts(crate_type="dylib"), _facts(crate_type="dylib")) == [
        "crate_type: bazel dylib, expected rlib (gn dylib, allowlisted)"]


def test_run_checks_each_fuchsia_config_and_the_host_for_proc_macros(ev, capsys):
    targets = [gc.Target("src/a", "a", "fuchsia"), gc.Target("src/m", "the-macro", "host")]
    gn = {t: gc.gn_facts(ev, t, ALIASES) for t in targets}
    calls = []

    def facts_for(config, labels):
        calls.append((config, labels))
        return {t.bazel_label: gn[t] for t in targets if t.bazel_label in labels}

    assert gc.run(targets, ev, ALIASES, facts_for) == 0
    assert [c for c, _ in calls] == ["fuchsia_x64", "fuchsia_arm64", None]
    out = capsys.readouterr().out
    assert "//vendor/fuchsia/src/a:a [fuchsia_arm64]: OK" in out and "[host]: OK" in out

    def wrong(config, labels):
        return {label: _facts() for label in labels}

    assert gc.run(targets[:1], ev, ALIASES, wrong) == 2  # differs under both Fuchsia configs


def test_targets_come_from_the_closure_and_bazel_names_are_mapped():
    data = {"intree": [{"path": "sdk/lib/c/rust", "targets": [{"target": "zx-libc", "contexts": ["fuchsia"]}]}]}
    (t,) = gc.closure_targets(["sdk/lib/c/rust"], data)
    assert t.bazel_label == "//vendor/fuchsia/sdk/lib/c/rust:rust"
    with pytest.raises(gc.CheckError, match="not an in-tree crate"):
        gc.closure_targets(["src/other"], data)


def test_main_needs_paths_or_all():
    with pytest.raises(SystemExit):
        gc.main([])
    assert gc.main(["src/not/listed"]) == 2


def test_each_removed_dep_names_the_overlay_or_patch_that_removes_it():
    """A GN dep the overlay drops on purpose points at the file that drops it (M9b's
    syslog patch, M9c's inspect/runtime overlay), so the reason can be checked."""
    root = Path(gc.ROOT)
    for label, reason in gc.REMOVED_DEPS.items():
        where = [w.rstrip(",;()") for w in reason.split() if w.startswith(("overlays/", "patches/"))]
        assert where, label
        assert all((root / w).is_dir() for w in where), (label, where)
