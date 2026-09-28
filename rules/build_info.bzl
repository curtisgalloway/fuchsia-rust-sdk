# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0

"""The overlay's values for upstream build arguments.

Upstream BUILD.bazel files load build arguments from @fuchsia_build_info//:args.bzl, which
GN writes from its args. scripts/regen.py maps that load to this file (milestone M8) and
fails on any name not defined here (regen.BUILD_INFO_ARGS lists them).
"""

# GN default: compilation_mode == "debug" (src/lib/fuchsia-sync). Decided false for the
# overlay (plan backlog, M6a review): no lock-cycle detection, so no forks/tracing-mutex;
# scripts/closure.py uses the same value (OVERLAY_ARGS).
fuchsia_sync_detect_lock_cycles = False
