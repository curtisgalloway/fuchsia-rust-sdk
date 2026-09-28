# Copyright 2025 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# SPDX-FileCopyrightText: 2025 The Fuchsia Authors
# SPDX-FileCopyrightText: 2026 The Fuchsia Authors
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: BSD-2-Clause
#
# Ported from fuchsia.git build/bazel/rules/rust/ at the lock's fuchsia_revision
# (b5274053cc0f): common.bzl, rustc_library.bzl, rustc_binary.bzl, rustc_proc_macro.bzl
# and defs.bzl, in one file (design §4.1: rules/rustc.bzl). The Fuchsia LICENSE is
# LICENSES/BSD-2-Clause.txt. Changes from upstream, all marked "Overlay:" below:
#   - The API-level cfgs are not here: as upstream, the Rust toolchains add them
#     (toolchain/rust.BUILD.bazel, rules/rustc_api_level.bzl).
#   - --cap-lints uses GN's default for rust_cap_lints ("deny", build/rust/config.gni)
#     instead of reading the GN arg from @fuchsia_build_info.
#   - A `vendored` attribute (design R3, M4) sets --cap-lints=allow instead, as GN's
#     //build/config/rust:cap_lints_allow does for third-party code.
#   - The lint_config defaults are the overlay's copy of upstream's
#     //build/config/rust/lints (//rules/lints).
#   - with_host_unit_tests, with_unit_tests and test_deps are accepted, so upstream
#     BUILD files load unchanged, but no test target is generated yet: upstream's
#     generate_unit_tests.bzl needs the host-test and Fuchsia test wrappers, which are
#     milestone M16 (design R9).
#   - build_flags support loads from @rules_fuchsia, which ships fuchsia_rules_common;
#     upstream has a separate @fuchsia_rules_common.
#   - rustc_embed_files and rustc_test are not ported (not needed yet; rustc_test is M16).
#   - rustc_proc_macro targets are host-only unless they say otherwise (milestone M8): a
#     proc macro runs in the compiler, so it is built for the exec platform; built as a
#     Fuchsia target (as `bazel build --config=fuchsia_x64 //...` would) it cannot link.

"""rules_rust wrappers with Fuchsia-specific flags: rustc_library, rustc_binary, rustc_proc_macro."""

# Overlay: upstream loads from @fuchsia_rules_common//build_flags:rust.bzl.
load(
    "@rules_fuchsia//fuchsia_rules_common/build_flags:rust.bzl",
    "BUILD_FLAGS_RUST_ATTRS_KWARGS",
    "wrap_rust_macro_args_with_build_flags",
)
load("@rules_rust//rust:defs.bzl", "rust_binary", "rust_library", "rust_proc_macro")

# Overlay: GN's default for the rust_cap_lints arg (build/rust/config.gni,
# rust_cap_lints_default); upstream reads the arg from @fuchsia_build_info//:args.bzl.
_RUST_CAP_LINTS = "deny"

# Overlay: upstream uses "//build/config/rust/lints:<name>" strings.
_CLIPPY_WARN_PRODUCTION = Label("//rules/lints:clippy_warn_production")
_CLIPPY_ALLOW_ALL = Label("//rules/lints:clippy_allow_all")

# Overlay: where a rustc_proc_macro builds when its target does not say (the build host's
# OS; design C5: linux-amd64).
_PROC_MACRO_COMPATIBLE_WITH = [Label("@platforms//os:linux")]

# --- common.bzl ---

def with_fuchsia_rustc_flags(rustc_flags, vendored = False):
    """Add a list of Fuchsia-specific rustc flags to input rustc_flags.

    Args:
        rustc_flags: The target's own rustc_flags (a list, a select() or None).
        vendored: Overlay: True for code copied from elsewhere, whose lints are not ours
            to fix; it caps lints at "allow" instead of "deny".

    Returns:
        The flags with --cap-lints appended.
    """
    return (rustc_flags or []) + [
        # --cap-lints can't be overridden once set, see https://rust-lang.github.io/rfcs/1193-cap-lints.html.
        #
        # As a result, we avoid setting this on the toolchain directly, which will affect
        # third-party rust-crates.
        "--cap-lints={}".format("allow" if vendored else _RUST_CAP_LINTS),
    ]

# Overlay: attributes shared by the three macros. The test attributes are upstream's
# (docs match); vendored is the overlay's.
_COMMON_ATTRS = {
    "with_host_unit_tests": attr.bool(
        doc = "If true, a `host_rustc_test` target will be created. Incompatible with with_unit_tests. " +
              "Overlay: accepted but not yet implemented (milestone M16).",
        default = False,
        configurable = False,
    ),
    "with_unit_tests": attr.bool(
        doc = "If true, a `rust_test` target will be created. Incompatible with with_host_unit_tests. " +
              "Overlay: accepted but not yet implemented (milestone M16).",
        default = False,
        configurable = False,
    ),
    "test_deps": attr.label_list(
        doc = "Extra dependencies for the test target.",
        default = [],
    ),
    "vendored": attr.bool(
        doc = "Overlay: if true, the target is code copied from elsewhere (vendored), so " +
              "its lints are capped at `allow` (--cap-lints=allow) instead of `deny`.",
        default = False,
        configurable = False,
    ),
} | BUILD_FLAGS_RUST_ATTRS_KWARGS

def _check_test_attrs(name, with_host_unit_tests, with_unit_tests):
    # Upstream checks this in generate_unit_tests().
    if with_host_unit_tests and with_unit_tests:
        fail("Cannot specify both with_host_unit_tests and with_unit_tests on {}".format(name))

# --- rustc_library.bzl ---

def _rustc_library_impl(
        name,
        with_host_unit_tests,
        with_unit_tests,
        test_deps,  # buildifier: disable=unused-variable
        vendored,
        lint_config,
        disable_clippy,
        rustc_flags,
        build_flags,
        visibility,
        **kwargs):
    _check_test_attrs(name, with_host_unit_tests, with_unit_tests)
    if disable_clippy:
        lint_config = _CLIPPY_ALLOW_ALL
    elif lint_config == None:
        lint_config = _CLIPPY_WARN_PRODUCTION

    kwargs["rustc_flags"] = with_fuchsia_rustc_flags(rustc_flags, vendored)

    library_kwargs = wrap_rust_macro_args_with_build_flags(
        kwargs = kwargs,
        name = name,
        rust_rule_name = "rust_library",
        build_flags = build_flags,
        target_type = "rust_common",
    )

    rust_library(
        name = name,
        lint_config = lint_config,
        visibility = visibility,
        **library_kwargs
    )

    # Overlay: upstream calls generate_unit_tests() here (M16).

rustc_library = macro(
    doc = """`rust_library` wrapper with Fuchsia-specific features.

Apply Fuchsia-specific Rust flags.

The default lint_config value is //rules/lints:clippy_warn_production.

Overlay: `vendored = True` caps lints at `allow`. Test targets (with_unit_tests,
with_host_unit_tests) are not generated yet (M16).
""",
    implementation = _rustc_library_impl,
    inherit_attrs = rust_library,
    attrs = _COMMON_ATTRS | {
        "disable_clippy": attr.bool(
            doc = "If true, disables clippy lints on this target.",
            default = False,
            configurable = False,
        ),
    },
)

# --- rustc_binary.bzl ---

def _rustc_binary_impl(
        name,
        with_host_unit_tests,
        with_unit_tests,
        test_deps,  # buildifier: disable=unused-variable
        vendored,
        lint_config,
        rustc_flags,
        build_flags,
        visibility,
        **kwargs):
    _check_test_attrs(name, with_host_unit_tests, with_unit_tests)
    if lint_config == None:
        lint_config = _CLIPPY_WARN_PRODUCTION

    kwargs["rustc_flags"] = with_fuchsia_rustc_flags(rustc_flags, vendored)

    binary_kwargs = wrap_rust_macro_args_with_build_flags(
        kwargs = kwargs,
        name = name,
        rust_rule_name = "rust_binary",
        build_flags = build_flags,
        target_type = "rust_executable",
    )

    rust_binary(
        name = name,
        lint_config = lint_config,
        visibility = visibility,
        **binary_kwargs
    )

    # Overlay: upstream calls generate_unit_tests() here (M16).

rustc_binary = macro(
    doc = """`rust_binary` wrapper with Fuchsia-specific features.

Applies Fuchsia-specific Rust flags.

The default lint_config value is //rules/lints:clippy_warn_production.

Overlay: `vendored = True` caps lints at `allow`. Test targets (with_unit_tests,
with_host_unit_tests) are not generated yet (M16).
""",
    implementation = _rustc_binary_impl,
    inherit_attrs = rust_binary,
    attrs = _COMMON_ATTRS,
)

# --- rustc_proc_macro.bzl ---

def _rustc_proc_macro_impl(
        name,
        with_host_unit_tests,
        with_unit_tests,
        test_deps,  # buildifier: disable=unused-variable
        vendored,
        lint_config,
        rustc_flags,
        build_flags,
        visibility,
        **kwargs):
    _check_test_attrs(name, with_host_unit_tests, with_unit_tests)
    if lint_config == None:
        lint_config = _CLIPPY_WARN_PRODUCTION

    kwargs["rustc_flags"] = with_fuchsia_rustc_flags(rustc_flags, vendored)

    # Overlay: host-only by default (see the file header).
    if kwargs.get("target_compatible_with") == None:
        kwargs["target_compatible_with"] = _PROC_MACRO_COMPATIBLE_WITH

    proc_macro_kwargs = wrap_rust_macro_args_with_build_flags(
        kwargs = kwargs,
        name = name,
        rust_rule_name = "rust_proc_macro",
        build_flags = build_flags,
        target_type = "rust_shared_library",
    )

    rust_proc_macro(
        name = name,
        lint_config = lint_config,
        visibility = visibility,
        **proc_macro_kwargs
    )

    # Overlay: upstream calls generate_unit_tests() here (M16).

rustc_proc_macro = macro(
    doc = """`rust_proc_macro` wrapper with Fuchsia-specific features.

Applies Fuchsia-specific Rust flags.

The default lint_config value is //rules/lints:clippy_warn_production.

Overlay: `vendored = True` caps lints at `allow`. Test targets (with_unit_tests,
with_host_unit_tests) are not generated yet (M16). Without `target_compatible_with`, the
target is compatible with Linux only (the build host): proc macros run in the compiler.
""",
    implementation = _rustc_proc_macro_impl,
    inherit_attrs = rust_proc_macro,
    attrs = _COMMON_ATTRS,
)
