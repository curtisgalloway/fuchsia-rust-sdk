# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/overlay_profile.py: which profile is active, and what it allows."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import idk_trim as it
import overlay_profile as op

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT = SCRIPTS / "overlay_profile.py"


def write_config(base: Path, text: str) -> Path:
    path = base / "fuchsia-rust-sdk" / "profile"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return path


def test_default_is_hosted(tmp_path):
    profile, source = op.resolve({"HOME": str(tmp_path)})
    assert profile.name == "hosted" and source == "default"


def test_default_without_home_or_xdg():
    profile, source = op.resolve({})
    assert profile.name == "hosted" and source == "default"


def test_hosted_trims_and_does_not_cache():
    hosted = op.PROFILES["hosted"]
    assert hosted.trim_idk and not hosted.cache_idk_archive
    # C6: total <= 25 GB; M2a: output base + repository cache <= 12 GB.
    assert hosted.budgets == {"total": 25 * op.GIB, "bazel": 12 * op.GIB}


def test_large_disk_skips_trim_and_keeps_caches():
    large = op.PROFILES["large-disk"]
    assert not large.trim_idk and large.cache_idk_archive
    assert large.budgets == {"total": None, "bazel": None}


def test_env_var_selects_profile(tmp_path):
    profile, source = op.resolve({"OVERLAY_PROFILE": "large-disk", "HOME": str(tmp_path)})
    assert profile.name == "large-disk" and source == "$OVERLAY_PROFILE"


def test_env_var_wins_over_file(tmp_path):
    write_config(tmp_path / ".config", "large-disk\n")
    profile, _ = op.resolve({"OVERLAY_PROFILE": "hosted", "HOME": str(tmp_path)})
    assert profile.name == "hosted"


def test_empty_env_var_is_unset(tmp_path):
    write_config(tmp_path / ".config", "large-disk\n")
    profile, source = op.resolve({"OVERLAY_PROFILE": " ", "HOME": str(tmp_path)})
    assert profile.name == "large-disk" and source.endswith("fuchsia-rust-sdk/profile")


def test_file_under_home_config(tmp_path):
    path = write_config(tmp_path / ".config", "# this VM has a 500 GB disk\n\nlarge-disk\n")
    profile, source = op.resolve({"HOME": str(tmp_path)})
    assert profile.name == "large-disk" and source == str(path)


def test_xdg_config_home_wins_over_home(tmp_path):
    write_config(tmp_path / "home" / ".config", "hosted\n")
    path = write_config(tmp_path / "xdg", "large-disk\n")
    env = {"HOME": str(tmp_path / "home"), "XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    profile, source = op.resolve(env)
    assert profile.name == "large-disk" and source == str(path)


def test_unknown_name_in_env_fails(tmp_path):
    with pytest.raises(op.ProfileError, match=r"\$OVERLAY_PROFILE: unknown profile 'big'"):
        op.resolve({"OVERLAY_PROFILE": "big", "HOME": str(tmp_path)})


def test_unknown_name_in_file_fails(tmp_path):
    write_config(tmp_path / ".config", "huge\n")
    with pytest.raises(op.ProfileError, match="unknown profile 'huge'"):
        op.resolve({"HOME": str(tmp_path)})


def test_file_without_a_name_fails(tmp_path):
    write_config(tmp_path / ".config", "# nothing here\n\n")
    with pytest.raises(op.ProfileError, match="no profile name"):
        op.resolve({"HOME": str(tmp_path)})


def run_cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                          capture_output=True, text=True, check=False)


def test_cli_json_is_what_the_repository_rule_reads(tmp_path):
    proc = run_cli({"HOME": str(tmp_path), "OVERLAY_PROFILE": "large-disk"}, "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["name"] == "large-disk"
    assert data["trim_idk"] is False and data["cache_idk_archive"] is True
    assert data["source"] == "$OVERLAY_PROFILE"


def test_cli_fails_on_unknown_profile(tmp_path):
    proc = run_cli({"HOME": str(tmp_path), "OVERLAY_PROFILE": "nope"}, "--json")
    assert proc.returncode == 1 and "unknown profile 'nope'" in proc.stderr


def test_profiles_and_trim_spec_agree():
    assert set(op.PROFILES) == set(it.TRIM_BY_PROFILE)
    for name, profile in op.PROFILES.items():
        assert profile.trim_idk == it.TRIM_BY_PROFILE[name]


def test_trim_spec_cli_is_what_the_repository_rule_reads(tmp_path):
    for env, expected in (
        ({"HOME": str(tmp_path)}, {"profile": "hosted", "trim": True, "source": "default"}),
        ({"HOME": str(tmp_path), "OVERLAY_PROFILE": "large-disk"},
         {"profile": "large-disk", "trim": False, "source": "$OVERLAY_PROFILE"}),
    ):
        proc = subprocess.run([sys.executable, str(SCRIPTS / "idk_trim.py"), "--json"],
                              env=env, capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout) == expected


def test_trim_spec_cli_fails_on_unknown_profile(tmp_path):
    proc = subprocess.run([sys.executable, str(SCRIPTS / "idk_trim.py"), "--json"],
                          env={"HOME": str(tmp_path), "OVERLAY_PROFILE": "nope"},
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 1 and "unknown profile 'nope'" in proc.stderr


def test_trim_spec_does_not_import_the_general_profile_module():
    """@fuchsia_idk watches idk_trim.py and idk_extract.py only; if either imported
    overlay_profile.py, an edit there would change the fetch without refetching."""
    for name in ("idk_trim.py", "idk_extract.py"):
        imports = [line for line in (SCRIPTS / name).read_text().splitlines()
                   if line.startswith(("import ", "from "))]
        assert not [line for line in imports if "overlay_profile" in line], name
