# Copyright 2025 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# SPDX-FileCopyrightText: 2023 The Fuchsia Authors
# SPDX-FileCopyrightText: 2025 The Fuchsia Authors
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: BSD-2-Clause
#
# Ported from fuchsia.git at the lock's fuchsia_revision (b5274053cc0f):
#   - get_integer_for_api_level(): build/bazel/versioning/api_level.bzl, unchanged except
#     that the file's visibility() list is dropped (it names upstream-only packages).
#   - platform_version_from_json(): build/config/fuchsia/get_platform_version.py
#     (get_gn_variables), translated from Python to Starlark. Upstream runs it on the
#     source tree's sdk/version_history.json; the overlay runs it on the IDK's copy
#     (toolchain/api_levels.bzl). Changes, marked "Overlay:" below:
#       - Numbered levels are sorted numerically. The IDK copy is written with sorted
#         keys ("10" < "4"); the source tree lists them in numeric order, which is the
#         order upstream's flags follow.
#       - Special levels are checked by name and by their integer value, not by position:
#         the IDK copy sorts them too (HEAD, NEXT, PLATFORM), which fails upstream's
#         positional assertion.
# The Fuchsia LICENSE is LICENSES/BSD-2-Clause.txt.

"""Functions related to the Fuchsia API level."""

def get_integer_for_api_level(api_level):
    """Returns the integer reprsentation of the Fuchsia `api_level`.

    This should only be used to pass an integer representation of the current
    target API level to build tools, such as Clang, or to determine whether to
    include a Fuchsia package in the IDK.
    Individual target definitions should not use it.
    """

    # Numerical values associated with special API levels, as defined in
    # https://fuchsia.dev/fuchsia-src/contribute/governance/rfcs/0246_api_levels_are_32_bits#special_api_levels.
    _FIRST_RESERVED_API_LEVEL = 2147483648  # 0x80000000
    _API_LEVEL_NEXT_AS_INTEGER = 4291821568
    _API_LEVEL_HEAD_AS_INTEGER = 4292870144
    _API_LEVEL_PLATFORM_AS_INTEGER = 4293918720

    if api_level == "NEXT":
        return _API_LEVEL_NEXT_AS_INTEGER
    elif api_level == "HEAD":
        return _API_LEVEL_HEAD_AS_INTEGER
    elif api_level == "PLATFORM":
        return _API_LEVEL_PLATFORM_AS_INTEGER
    else:
        # If the string is not an integer, this will raise a ValueError.
        api_level_integer = int(api_level)

        # `current_build_target_api_level` must be an integer. Ensure it adheres to
        # https://fuchsia.dev/fuchsia-src/contribute/governance/rfcs/0246_api_levels_are_32_bits#design.
        if api_level_integer < 0:
            fail("Non-special API levels must be a positive integer, not: %s" % api_level_integer)
        if api_level_integer >= _FIRST_RESERVED_API_LEVEL:
            fail("Special API levels should be given by name, not number: %s" % api_level_integer)

        return api_level_integer

# The special levels in upstream's expected order (get_platform_version.py).
SPECIAL_API_LEVELS = ["NEXT", "HEAD", "PLATFORM"]

def platform_version_from_json(content, source = "version_history.json"):
    """Reads version_history.json content as upstream's get_platform_version.py does.

    Args:
        content: The text of a version_history.json file.
        source: A name for the file, used in error messages.

    Returns:
        A struct with values upstream reads from @fuchsia_build_info//:args.bzl, as
        strings (build/bazel/BUILD.gn stringifies them): `all_numbered_api_levels` (every
        numbered level in the file, all frozen or previously frozen) and
        `idk_buildable_api_levels` (the GN default: the "supported" levels plus "NEXT"),
        which the Rust cfg generator reads, and `runtime_supported_api_levels` (the
        "sunset" and "supported" levels plus "NEXT" and "HEAD"), which FIDL's PLATFORM
        level expands to (build/bazel/rules/fidl/fidl_ir.bzl; overlay: milestone M8).
    """
    data = json.decode(content)["data"]
    api_levels = data["api_levels"]

    # Overlay: numeric order; upstream keeps the file's order, which in the source tree
    # is numeric and in the IDK copy is string-sorted.
    numbered = sorted([int(level) for level in api_levels])

    phases = {}
    for level in numbered:
        phase = api_levels[str(level)]["phase"]
        if phase not in ("retired", "sunset", "supported"):
            # Upstream: an assertion that every level is retired, sunset or supported.
            fail('%s: "api_levels" contains a level with an unexpected "phase": %s is "%s".' % (source, level, phase))
        phases[level] = phase
    sunset_api_levels = [level for level in numbered if phases[level] == "sunset"]
    supported_api_levels = [level for level in numbered if phases[level] == "supported"]

    # Special API levels are added below.
    runtime_supported_api_levels = [str(level) for level in sunset_api_levels + supported_api_levels]

    # Explicitly add concrete special API levels.
    # "HEAD" is not supported in the IDK - see https://fxbug.dev/334936990.
    runtime_supported_api_levels += ["NEXT", "HEAD"]
    idk_buildable_api_levels = [str(level) for level in supported_api_levels] + ["NEXT"]

    # Overlay: upstream asserts the special levels appear as NEXT, HEAD, PLATFORM in that
    # order. The IDK copy has sorted keys, so check the names and their integer values.
    special_api_levels = data["special_api_levels"]
    if sorted(special_api_levels.keys()) != sorted(SPECIAL_API_LEVELS):
        fail("%s: special API levels are %s, expected %s." % (source, sorted(special_api_levels.keys()), SPECIAL_API_LEVELS))
    for level in SPECIAL_API_LEVELS:
        as_u32 = special_api_levels[level]["as_u32"]
        if as_u32 != get_integer_for_api_level(level):
            fail("%s: special API level %s is %s, expected %s." % (source, level, as_u32, get_integer_for_api_level(level)))

    return struct(
        all_numbered_api_levels = [str(level) for level in numbered],
        idk_buildable_api_levels = idk_buildable_api_levels,
        runtime_supported_api_levels = runtime_supported_api_levels,
    )
