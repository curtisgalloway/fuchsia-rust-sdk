# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/disk_report.py (sizes, budgets, cache policy) and the pure parts of
scripts/check_sdk_files.py."""

from __future__ import annotations

import os
from pathlib import Path

import check_sdk_files as cs
import disk_report as dr
import overlay_profile as op

SHA = "043104bab236c808c3d53bfa7d36dc8d2150a662fb8a6f772693529c5a7078f6"


def blob(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    return path


def test_tree_size_counts_hardlinks_once_and_skips_symlinks(tmp_path):
    a = blob(tmp_path / "a" / "f", 64 * 1024)
    os.link(a, tmp_path / "a" / "g")
    (tmp_path / "a" / "link").symlink_to(tmp_path / "elsewhere")
    blob(tmp_path / "elsewhere" / "big", 1024 * 1024)
    seen: set = set()
    size = dr.tree_size([tmp_path / "a"], seen)
    assert 64 * 1024 <= size < 1024 * 1024
    # A second measurement with the same inode set counts nothing again.
    assert dr.tree_size([tmp_path / "a"], seen) == 0


def test_tree_size_of_missing_path_is_zero(tmp_path):
    assert dr.tree_size([tmp_path / "nope"], set()) == 0


def test_bucket_paths(tmp_path):
    info = {
        "output_base": "/c/bazel/_bazel_root/abc",
        "repository_cache": "/c/bazel/_bazel_root/cache/repos/v1",
        "install_base": "/c/bazel/_bazel_root/install/123",
    }
    env = {"HOME": "/h", "OVERLAY_SCRATCH": "/s1:/s2", "OVERLAY_EMULATOR_DIR": "/emu"}
    paths = dr.bucket_paths(info, env, ["/s0"])
    assert paths["output_base"] == [Path("/c/bazel/_bazel_root/abc")]
    assert paths["bazel_install"] == [
        Path("/c/bazel/_bazel_root/install"), Path("/h/.cache/fuchsia-rust-sdk/bazel")]
    assert paths["emulator"] == [Path("/emu")]
    assert paths["scratch"] == [Path("/s0"), Path("/s1"), Path("/s2")]
    assert set(paths) == set(dr.BUCKETS)


def test_bucket_paths_without_emulator_or_scratch():
    paths = dr.bucket_paths({}, {"XDG_CACHE_HOME": "/x"}, [])
    assert paths["emulator"] == [] and paths["scratch"] == []
    assert paths["bazel_install"] == [Path("/x/fuchsia-rust-sdk/bazel")]


def sizes(**kw: int) -> dict[str, int]:
    return {b: kw.get(b, 0) for b in dr.BUCKETS}


def test_hosted_budget_ok_and_over():
    hosted = op.PROFILES["hosted"]
    ok = {g.name: g for g in dr.evaluate(sizes(output_base=7 * op.GIB,
                                               repository_cache=1 * op.GIB), hosted)}
    assert ok["bazel"].used == 8 * op.GIB and not ok["bazel"].over
    assert not ok["total"].over
    over = {g.name: g for g in dr.evaluate(sizes(output_base=11 * op.GIB,
                                                 repository_cache=2 * op.GIB), hosted)}
    assert over["bazel"].over and not over["total"].over
    total = {g.name: g for g in dr.evaluate(sizes(output_base=8 * op.GIB,
                                                  emulator=18 * op.GIB), hosted)}
    assert total["total"].over and not total["bazel"].over


def test_large_disk_has_no_budget():
    groups = dr.evaluate(sizes(output_base=500 * op.GIB), op.PROFILES["large-disk"])
    assert all(g.budget is None and not g.over for g in groups)


def test_prune_hosted_removes_only_the_idk_entry(tmp_path):
    idk = blob(dr.idk_cache_entry(tmp_path, SHA) / "file", 1024)
    other = blob(dr.idk_cache_entry(tmp_path, "d" * 64) / "file", 1024)
    msg = dr.prune(tmp_path, SHA, op.PROFILES["hosted"])
    assert "removed" in msg
    assert not idk.exists() and other.exists()
    assert "not in the repository cache" in dr.prune(tmp_path, SHA, op.PROFILES["hosted"])


def test_prune_large_disk_is_skipped(tmp_path):
    idk = blob(dr.idk_cache_entry(tmp_path, SHA) / "file", 1024)
    msg = dr.prune(tmp_path, SHA, op.PROFILES["large-disk"])
    assert msg.startswith("prune: skipped") and idk.exists()


def test_render_names_every_bucket_and_group(tmp_path):
    hosted = op.PROFILES["hosted"]
    s = sizes(output_base=13 * op.GIB)
    text = dr.render(hosted, "default", dr.bucket_paths({}, {"HOME": str(tmp_path)}, []),
                     s, dr.evaluate(s, hosted))
    for name in (*dr.BUCKETS, *dr.GROUPS):
        assert name in text
    assert "OVER BUDGET" in text and "profile: hosted (default)" in text


# check_sdk_files.py


def test_parse_files_dedupes_and_sorts():
    out = "external/b/x.h\nexamples/a.rs\n\nexternal/b/x.h\n"
    assert cs.parse_files(out) == ["examples/a.rs", "external/b/x.h"]


def test_parse_analysis_errors():
    err = (
        "WARNING: errors encountered while analyzing target '@@r//p:t', it will not be built.\n"
        "WARNING: errors encountered while analyzing target '@@r//q:u', it will not be built.\n"
        "INFO: other\n"
    )
    assert cs.parse_analysis_errors(err) == ["@@r//p:t", "@@r//q:u"]


def test_find_missing_reports_dangling_symlinks(tmp_path):
    ws, ob = tmp_path / "ws", tmp_path / "ob"
    blob(ws / "examples" / "a.rs", 1)
    repo = ob / "external" / "+fuchsia_repos+fuchsia_sdk"
    blob(tmp_path / "idk" / "arch" / "x64" / "lib.so", 1)
    (repo / "arch" / "x64").mkdir(parents=True)
    (repo / "arch" / "x64" / "lib.so").symlink_to(tmp_path / "idk" / "arch" / "x64" / "lib.so")
    (repo / "obj").mkdir()
    (repo / "obj" / "gone.so").symlink_to(tmp_path / "idk" / "obj" / "gone.so")
    files = [
        "examples/a.rs",
        "external/+fuchsia_repos+fuchsia_sdk/arch/x64/lib.so",
        "external/+fuchsia_repos+fuchsia_sdk/obj/gone.so",
        "examples/missing.rs",
    ]
    assert cs.find_missing(files, ws, ob) == [
        "external/+fuchsia_repos+fuchsia_sdk/obj/gone.so", "examples/missing.rs"]


def test_sdk_scope_excludes_whole_sdk_globs():
    assert "rdeps(@fuchsia_sdk//..., @fuchsia_sdk//:all_files)" in cs.SDK_SCOPE
    assert "_EXPORT_SUBPACKAGE_FILEGROUP" in cs.SDK_SCOPE
    assert cs.CONFIGS["host"] == (None, "//...")


def test_unexpected_analysis_errors():
    known = "@@+fuchsia_repos+fuchsia_sdk//pkg/vulkan_layers/riscv64:vulkan_layers"
    new = "@@+fuchsia_repos+fuchsia_sdk//pkg/fdio:fdio"
    assert cs.unexpected_errors([known, new]) == [new]
    assert cs.unexpected_errors([known]) == []
