# Copyright 2026 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# SPDX-FileCopyrightText: 2026 The Fuchsia Authors
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: BSD-3-Clause
#
# Ported from fuchsia.git build/bazel/versioning/rustc_api_level.bzl at the lock's
# fuchsia_revision (b5274053cc0f). The Fuchsia LICENSE is LICENSES/BSD-3-Clause.txt.
# Changes from upstream, all marked "Overlay:" below:
#   - The levels come from @fuchsia_api_levels//:args.bzl, which toolchain/api_levels.bzl
#     generates from the IDK's version_history.json; upstream reads the same two names
#     from @fuchsia_build_info//:args.bzl, which GN generates from the source tree's copy.
#   - The loop body is split out as rustc_api_level_flags_by_target(), unchanged, so the
#     golden test (tests/api_level) can run it on pinned inputs.
#   - The select() keys are rules_fuchsia's API level settings,
#     @fuchsia_sdk//constraints:api_level_<level> (set with --override_fuchsia_api_level),
#     instead of upstream's //build/bazel/versioning:is_api_level_<level>. rules_fuchsia
#     has no PLATFORM level and its flag fails analysis when unset (as on host builds),
#     so the select() is for the Fuchsia toolchains only; the host toolchain takes the
#     PLATFORM flags, which upstream's host code gets from its flag's default, from
#     get_host_rustc_api_level_flags().

"""Provides functions to generate Rust configuration flags based on the target Fuchsia API level."""

load("@fuchsia_api_levels//:args.bzl", "all_numbered_api_levels", "idk_buildable_api_levels")
load("//rules:api_level.bzl", "get_integer_for_api_level")

def rustc_api_level_flags_by_target(all_numbered_api_levels, idk_buildable_api_levels):
    """Returns the rustc fuchsia_api_level config flags for each target API level.

    Args:
        all_numbered_api_levels: Every numbered API level, as strings.
        idk_buildable_api_levels: The API levels the IDK can target, as strings.

    Returns:
        A dict from target API level (a string, including NEXT, HEAD and PLATFORM)
        to its list of flags.
    """
    by_target = {}

    special_levels = ["NEXT", "HEAD", "PLATFORM"]
    all_levels = all_numbered_api_levels + special_levels
    target_levels = list(idk_buildable_api_levels)

    # idk_buildable_api_levels can contain `NEXT`, so dedupe to avoid
    # redundant work below.
    for level in special_levels:
        if level not in target_levels:
            target_levels.append(level)

    for target_level in target_levels:
        target_int = get_integer_for_api_level(target_level)
        flags = []
        for historical_level in all_levels:
            if get_integer_for_api_level(historical_level) <= target_int:
                flags.append('--cfg=fuchsia_api_level_at_least="{}"'.format(historical_level))
            else:
                flags.append('--cfg=fuchsia_api_level_less_than="{}"'.format(historical_level))

        by_target[target_level] = flags

    return by_target

def get_rustc_api_level_flags():
    """Generates a select() statement for rustc fuchsia_api_level config flags.

    Overlay: for the Fuchsia toolchains only; the host toolchain uses
    get_host_rustc_api_level_flags().

    Returns:
        A select() statement mapping API levels to their appropriate flags.
    """
    conditions = {}
    for target_level, flags in rustc_api_level_flags_by_target(
        all_numbered_api_levels,
        idk_buildable_api_levels,
    ).items():
        # Overlay: rules_fuchsia's settings, one per level its flag accepts. Label()
        # resolves them here, not in the repository of the BUILD file calling this.
        # PLATFORM is not one of them (see get_host_rustc_api_level_flags()), and there
        # is no //conditions:default: rules_fuchsia fails the build when the level is
        # unset, which is what a Fuchsia target should do.
        if target_level != "PLATFORM":
            conditions[Label("@fuchsia_sdk//constraints:api_level_" + target_level)] = flags

    return select(conditions)

def get_host_rustc_api_level_flags():
    """Overlay: the rustc fuchsia_api_level config flags for the host toolchain.

    Upstream's host toolchain uses the same select() as the Fuchsia ones, and upstream's
    API level flag is PLATFORM (its default) in host builds. rules_fuchsia's flag cannot
    be read on host at all: it fails analysis when unset. So host code gets the PLATFORM
    flags directly. This includes proc macros and other code built for the exec
    platform.

    Returns:
        The list of flags for target level PLATFORM.
    """
    return rustc_api_level_flags_by_target(
        all_numbered_api_levels,
        idk_buildable_api_levels,
    )["PLATFORM"]
