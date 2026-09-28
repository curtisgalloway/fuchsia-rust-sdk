# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0

"""Host constraints for vendored upstream BUILD files (milestone M7).

scripts/regen.py maps upstream's load of HOST_OS_CONSTRAINTS from
//build/bazel/platforms:constraints.bzl to this file. Upstream defines it as the host
platform's OS constraint alone (read from @fuchsia_build_config), so that a host tool
builds for the host OS on any CPU. Here it is the OS entries of @platforms' own
HOST_CONSTRAINTS, the constraints of the machine Bazel runs on (linux-x64 for the
overlay, design C5).
"""

load("@platforms//host:constraints.bzl", "HOST_CONSTRAINTS")

HOST_OS_CONSTRAINTS = [c for c in HOST_CONSTRAINTS if c.startswith("@platforms//os:")]
