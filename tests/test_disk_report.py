# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/disk_report.py (sizes, budgets, cache policy) and the pure parts of
scripts/check_sdk_files.py."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

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
    assert paths["uv_cache"] == [Path("/h/.cache/uv")]
    assert paths["checkout"] == [dr.ROOT]
    assert set(paths) == set(dr.BUCKETS)


def test_bucket_paths_uv_cache_dir_and_worktree_git(tmp_path):
    paths = dr.bucket_paths({}, {"HOME": "/h", "UV_CACHE_DIR": "/uvc"}, [],
                            git_common_dir=tmp_path / "main" / ".git")
    assert paths["uv_cache"] == [Path("/uvc")]
    assert paths["checkout"] == [dr.ROOT, tmp_path / "main" / ".git"]
    # A plain clone's .git is inside the checkout and is not added twice.
    paths = dr.bucket_paths({}, {"HOME": "/h"}, [], git_common_dir=dr.ROOT / ".git")
    assert paths["checkout"] == [dr.ROOT]


def test_bucket_paths_without_emulator_or_scratch():
    paths = dr.bucket_paths({}, {"XDG_CACHE_HOME": "/x", "HOME": "/h"}, [])
    assert paths["scratch"] == []
    assert paths["bazel_install"] == [Path("/x/fuchsia-rust-sdk/bazel")]
    # The emulator bucket defaults to scripts/emu's own default directory.
    assert paths["emulator"] == [Path("/h/.local/state/fuchsia-rust-sdk/emulator")]


def test_bucket_paths_emulator_follows_the_harness_settings():
    env = {"HOME": "/h", "OVERLAY_STATE_DIR": "/state"}
    assert dr.bucket_paths({}, env, [])["emulator"] == [Path("/state/emulator")]
    env["OVERLAY_FFX_ISOLATE_DIR"] = "/ffx"
    assert dr.bucket_paths({}, env, [])["emulator"] == [Path("/state/emulator"), Path("/ffx")]


def sizes(**kw: int) -> dict[str, int]:
    return {b: kw.get(b, 0) for b in dr.BUCKETS}


def test_hosted_budget_ok_and_over():
    hosted = op.PROFILES["hosted"]
    ok = {g.name: g for g in dr.evaluate(sizes(output_base=7 * op.GIB,
                                               repository_cache=1 * op.GIB), hosted)}
    assert ok["bazel"].used == 8 * op.GIB and not ok["bazel"].over
    assert not ok["total"].over
    over = {g.name: g for g in dr.evaluate(sizes(output_base=14 * op.GIB,
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


@pytest.mark.parametrize("bad", ["", "../../..", "0" * 63, "A" * 64, "0" * 64 + "/.."])
def test_prune_refuses_malformed_hash(tmp_path, bad):
    idk = blob(dr.idk_cache_entry(tmp_path, SHA) / "file", 1024)
    with pytest.raises(dr.PruneError, match="not 64 lowercase hex"):
        dr.prune(tmp_path, bad, op.PROFILES["hosted"])
    assert idk.exists()


def test_prune_refuses_entry_outside_the_cache(tmp_path):
    # A symlinked entry that resolves elsewhere is not deleted.
    outside = blob(tmp_path / "elsewhere" / "file", 16).parent
    entry = dr.idk_cache_entry(tmp_path / "cache", SHA)
    entry.parent.mkdir(parents=True)
    entry.symlink_to(outside)
    with pytest.raises(dr.PruneError, match="resolves outside"):
        dr.prune(tmp_path / "cache", SHA, op.PROFILES["hosted"])
    assert (outside / "file").exists()


def test_prune_large_disk_is_skipped(tmp_path):
    idk = blob(dr.idk_cache_entry(tmp_path, SHA) / "file", 1024)
    msg = dr.prune(tmp_path, SHA, op.PROFILES["large-disk"])
    assert msg.startswith("prune: skipped") and idk.exists()


def test_render_names_every_bucket_and_group(tmp_path):
    hosted = op.PROFILES["hosted"]
    s = sizes(output_base=16 * op.GIB)
    text = dr.render(hosted, "default", dr.bucket_paths({}, {"HOME": str(tmp_path)}, []),
                     s, dr.evaluate(s, hosted))
    for name in (*dr.BUCKETS, *dr.GROUPS):
        assert name in text
    assert "OVER BUDGET" in text and "profile: hosted (default)" in text


# check_sdk_files.py


def test_parse_files_dedupes_and_sorts():
    out = "external/b/x.h\nexamples/a.rs\n\nexternal/b/x.h\n"
    assert cs.parse_files(out) == ["examples/a.rs", "external/b/x.h"]


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


MAPPING = {"fuchsia_sdk": "+fuchsia_repos+fuchsia_sdk", "": ""}
OB = Path("/ob")
PKG_ERR = ("ERROR: /ob/external/+fuchsia_repos+fuchsia_sdk/packages/vkext-test/BUILD.bazel:586:6: "
           'configurable attribute "actual" in @@+fuchsia_repos+fuchsia_sdk//packages/vkext-test:'
           "vkext-test doesn't match this configuration. Would a default condition help?")
PKG_SKIP = ("WARNING: errors encountered while analyzing target "
            "'@@+fuchsia_repos+fuchsia_sdk//packages/vkext-test:vkext-test', it will not be built.")
SUMMARY = ("ERROR: command succeeded, but not all targets were analyzed\n"
           "ERROR: Build did NOT complete successfully")


def judge(text: str, rc: int = 1):
    return cs.judge(cs.normalize(text, MAPPING, OB), rc)


def test_normalize_uses_apparent_names():
    out = cs.normalize(PKG_ERR, MAPPING, OB)
    assert "@@" not in out and "+fuchsia_repos+" not in out
    assert "@fuchsia_sdk//packages/vkext-test:vkext-test" in out


def test_judge_accepts_expected_errors():
    skipped, problems = judge("\n".join([PKG_ERR, PKG_SKIP, SUMMARY]))
    assert skipped == ["@fuchsia_sdk//packages/vkext-test:vkext-test"] and problems == []
    assert judge("", rc=0) == ([], [])


def test_judge_rejects_unexpected_analysis_failure():
    err = ("ERROR: /ob/external/+fuchsia_repos+fuchsia_sdk/pkg/fdio/BUILD.bazel:25:10: no such "
           "target '@@+fuchsia_repos+fuchsia_sdk//:arch/x64/lib/libfdio.so': gone")
    skip = ("WARNING: errors encountered while analyzing target "
            "'@@+fuchsia_repos+fuchsia_sdk//pkg/fdio:fdio', it will not be built.")
    _, problems = judge("\n".join([err, skip, SUMMARY]))
    assert any(p.startswith("unexpected error: ") for p in problems)
    assert "unexpected skipped target: @fuchsia_sdk//pkg/fdio:fdio" in problems


def test_judge_rejects_expected_target_with_another_reason():
    other = ("ERROR: /ob/external/+fuchsia_repos+fuchsia_sdk/packages/vkext-test/BUILD.bazel:1:1: "
             "no such target '@@+fuchsia_repos+fuchsia_sdk//:obj/x.so'")
    _, problems = judge("\n".join([other, PKG_SKIP, SUMMARY]))
    assert any("not for the expected reason" in p for p in problems)


def test_judge_rejects_loading_errors_and_bad_exit_codes():
    loading = ("ERROR: Skipping '//nope/...': no such package 'nope': BUILD file not found\n"
               "ERROR: command succeeded, but there were loading phase errors")
    _, problems = judge(loading)
    assert "unexpected skipped target: //nope/..." in problems
    assert any("no such package 'nope'" in p for p in problems)
    assert judge("", rc=2)[1] == ["cquery exited with status 2"]
    assert judge("", rc=1)[1] == ["cquery exited with status 1 but reported no error"]


def test_trim_error_is_expected_only_for_riscv64_layers():
    err = ("ERROR: x: no such target '@@+fuchsia_repos+fuchsia_sdk//:arch/riscv64/dist/"
           "VkLayer_khronos_validation.so': t")
    skip = ("WARNING: errors encountered while analyzing target "
            "'@@+fuchsia_repos+fuchsia_sdk//pkg/vulkan_layers/riscv64:vulkan_layers', x")
    assert judge("\n".join([err, skip, SUMMARY]))[1] == []
    x64 = err.replace("riscv64", "x64")
    assert judge("\n".join([x64, skip.replace("riscv64", "x64"), SUMMARY]))[1] != []
