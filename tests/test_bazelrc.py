# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""The Fuchsia configs in .bazelrc match what fuchsia_package's transition sets (M10).

rules_fuchsia's transition takes the CPU from --cpu and adds --copt=--debug,
--copt=-ffuchsia-api-level=<u32> and --strip=never; .bazelrc sets the same values so the
transition is a no-op (docs/evidence/M10.md). HEAD's u32 is read from the pinned copy of
the lock's IDK version_history.json (tests/api_level/testdata, M4); the Bazel test
//tests/api_level:bazelrc_head_u32_test checks it against the fetched IDK itself.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDK_HISTORY = ROOT / "tests/api_level/testdata/idk_version_history.json"


def bazelrc_lines() -> list[str]:
    return [line.strip() for line in (ROOT / ".bazelrc").read_text().splitlines()]


def test_api_level_copt_is_heads_u32():
    head = json.loads(IDK_HISTORY.read_text())["data"]["special_api_levels"]["HEAD"]["as_u32"]
    lines = bazelrc_lines()
    assert f"build:fuchsia --copt=-ffuchsia-api-level={head}" in lines
    # The level that number stands for is the one both configs target.
    assert "build:fuchsia --override_fuchsia_api_level=HEAD" in lines
    assert "build --default_fuchsia_api_level=HEAD" in lines


def test_configs_set_the_transitions_options():
    lines = bazelrc_lines()
    for line in [
        "build:fuchsia --copt=--debug",
        "build:fuchsia --strip=never",
        "build:fuchsia_x64 --cpu=x86_64",
        "build:fuchsia_arm64 --cpu=aarch64",
    ]:
        assert line in lines
