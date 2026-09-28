# Copyright 2025 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
# (providers.bzl: Copyright 2021 The Fuchsia Authors.)
#
# SPDX-FileCopyrightText: 2021 The Fuchsia Authors
# SPDX-FileCopyrightText: 2025 The Fuchsia Authors
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: BSD-2-Clause
#
# Ported from fuchsia.git build/bazel/rules/fidl/fidl_library.bzl, fidl_ir.bzl and
# providers.bzl at the lock's fuchsia_revision (b5274053cc0f); design §4.2 "FIDL bindings",
# R5, D7; milestone M8. The Fuchsia LICENSE is LICENSES/BSD-2-Clause.txt.
# scripts/regen.py rewrites upstream's sdk/fidl/<library>/BUILD.bazel files to load
# fidl_library from here, with the same arguments. Changes from upstream, all marked
# "Overlay:" below:
#   - Only the IR and the Rust bindings are built (//rules:fidl_rust.bzl, and
#     //rules:fidl_rust_next.bzl for rust_next since M8b). The C++,
#     HLCPP, Zither and Banjo backends, the IDK atom, the API summary and the
#     compatibility tests are not: their arguments are accepted and ignored, so upstream
#     BUILD files load unchanged. fidl-lint and the IR JSON-schema validation are not
#     run (the IDK has no schema; the sources are the IDK's, which upstream linted).
#   - fidlc is the IDK's (@fuchsia_sdk//tools:x64/fidlc, D7), run with --files groups
#     (dependencies first) as rules_fuchsia's fuchsia_fidl_library does; upstream writes
#     a response file with --sources/--dep-libraries through its gen_response_file tool.
#   - The target API level: on Fuchsia, rules_fuchsia's (@fuchsia_sdk//flags:
#     fuchsia_api_level, HEAD in the overlay's configs); elsewhere (host), PLATFORM,
#     upstream's default, which FIDL expands to runtime_supported_api_levels (from
#     @fuchsia_api_levels, the IDK's version_history.json). This matches the Rust
#     toolchains' API-level cfgs (M4): Fuchsia at the configured level, host at PLATFORM.

"""fidl_library: FIDL IR from the IDK's fidlc, and Rust bindings (//rules:fidl_rust.bzl)."""

load("@fuchsia_api_levels//:args.bzl", "runtime_supported_api_levels")
load("@rules_fuchsia//fuchsia/private:fuchsia_api_level.bzl", "FuchsiaAPILevelInfo")
load(":fidl_rust.bzl", "fidl_rust_library")
load(":fidl_rust_next.bzl", "fidl_rust_next_library")

visibility("public")

FidlLibraryInfo = provider(
    "Contains information about a FIDL library",
    fields = {
        "name": "Name of the FIDL library",
        "ir": "The JSON file with the library's intermediate representation",
        # Overlay: upstream has srcs_depset and libraries_file (its response-file tool's
        # input); fidlc's --files groups need each library's own files, in order.
        "libraries": "A list of struct(name, files) for this library and every library it " +
                     "depends on, each after its dependencies (fidlc's --files order)",
    },
)

# LINT.IfChange(determine_fidlc_versioned_arg)
def _get_fidlc_versioned_arg(
        library_name,
        versioned,
        category,
        stable,
        testonly):
    """Determines the value of the `versioned` argument to pass to fidlc.

    Also determines whether compatibility tests are required.

    Overlay: unchanged from upstream, except that upstream's package-name checks (vendor
    repositories, the internal zx library) compare against upstream paths, which the
    overlay's vendor/fuchsia/ packages never match; see the notes where they are used.

    Args:
        library_name: The name of the library.
        versioned: The value of the `versioned` attribute.
        category: The value of the `category` attribute.
        stable: The value of the `stable` attribute.
        testonly: The value of the `testonly` attribute.

    Returns:
        fidlc_versioned_arg: The value of the `versioned` argument to pass to fidlc.
        requires_compatibility_tests: Whether compatibility tests are required.
    """

    # Assume `category` validation is done elsewhere.

    # All libraries in an SDK category require compatibility tests.
    requires_compatibility_tests = category != ""

    # All publishable libraries must have compatibility tests.
    # Only "partner" libraries are publishable.
    is_idk_included_publishable = \
        requires_compatibility_tests and category == "partner"

    # Overlay: upstream compares native.package_name(), which has no leading "//", with
    # "//vendor/"; neither upstream's nor the overlay's packages ever match.
    is_vendor_library = native.package_name().startswith("//vendor/")
    if is_vendor_library:
        if category and category != "partner":
            fail(library_name + ": In vendor repos, only libraries in the vendor IDK should have `sdk_category` set.")
        if versioned != "unversioned":
            fail(library_name + ": `versioned` must be 'unversioned' for vendor IDK libraries.")

        # Vendor IDK libraries are `is_idk_included_publishable` but not
        # in the "fuchsia" namespace, not intended to be compaitibility
        # tested, and do not appear in allowlists. They specify
        # "unversioned" for clarity.
        if not is_idk_included_publishable:
            fail("Internal logic error")
        requires_compatibility_tests = False

        is_unversioned_vendor_idk = True
    else:
        is_unversioned_vendor_idk = False

    # All stable libraries must be included in an SDK [category] and require
    # compatibility tests, but the inverse is not always true.
    # For unstable libraries with `requires_compatibility_tests=True`, although
    # the build targets are created, the resulting API summery file will be empty.
    if stable and not requires_compatibility_tests:
        fail(library_name + ": Stable libraries must require compatibility tests.")

    if not stable and category and category != "partner":
        fail(
            library_name + ": Libraries in category '%s' must specify `stable=True`." % category,
        )

    # Some IDK prebuilts depend on FIDL libraries that are currently internal
    # and unstable. Treat such libraries as unversioned until each is resolved.
    _libraries_in_unsupported_scenarios = [
        # Do not add to this list without discussing with the FIDL team.
        # It is likely that only instances of the scenarios described in
        # https://fxbug.dev/369892217 should be added.

        # TODO(https://fxbug.dev/364294648): Resolve heapdump instrumentation dependency on library.
        "fuchsia.memory.heapdump.process",
    ]
    _is_library_in_unsupported_scenarios = \
        library_name in _libraries_in_unsupported_scenarios

    # TODO(https://fxbug.dev/364422340): Remove when the internal "zx" library is properly versioned.
    # Overlay: upstream's zx is in zircon/vdso/zx, not zircon/vdso, so this is False
    # upstream too; zx passes versioned = "fuchsia" and category = "partner" explicitly.
    _is_internal_zx_library = native.package_name() == "zircon/vdso" and library_name == "zx"

    # //sdk/banjo/fuchsia.sysmem is the only Banjo library with versioning.
    # Banjo libraries do not have an SDK category and are not marked stable,
    # so it is not caught in an earlier condition.
    # TODO(https://fxbug.dev/306258166): Determine an appropriate state for this
    # library and remove this variable and related exceptions.
    _is_banjo_sysmem = library_name == "fuchsia.sysmem" and not category

    # If `versioned` is not specified, set the default as defined in the
    # `fidl_library()` `versioned` attribute.
    if versioned:
        _platform_override_name = versioned.split(":")[0]
        if not (is_idk_included_publishable or testonly or _is_internal_zx_library):
            fail(
                library_name + ": Non-test library is explicitly versioned but not included in an IDK.",
            )
        if requires_compatibility_tests and _platform_override_name != "fuchsia":
            fail(
                library_name + ": Overriding `versioned` is not allowed for IDK FIDL library, which is a Fuchsia platform API requiring compatibility tests.",
            )

        fidlc_versioned_arg = versioned
    elif testonly and not category:
        fidlc_versioned_arg = "unversioned"
    elif library_name.startswith("fuchsia."):
        # The library is in the "fuchsia" namespace and either not test-only or
        # in an SDK category. Set `versioned` to appropriate default.
        if stable:
            if not category:
                fail(library_name + ": Libraries cannot be stable but not in an SDK category.")

            # Stable "fuchsia.*" library in an SDK category - must compile for all Supported API levels.
            fidlc_versioned_arg = "fuchsia"
        elif requires_compatibility_tests:
            if not category:
                fail(
                    library_name + ": Libraries cannot require compatibility tests unless they are in an SDK category.",
                )

            # Unstable "fuchsia.*" library in an SDK category - can only be used at HEAD.
            fidlc_versioned_arg = "fuchsia:HEAD"
        else:
            if category:
                fail(
                    library_name + ": Libraries with an SDK category should be stable or at least require compatibility tests.",
                )

            # All libraries in the "fuchsia" namespace must be versioned. For unstable
            # and/or internal libraries, that means specifying `@available(added=HEAD)`.
            fidlc_versioned_arg = "fuchsia:HEAD"

            # Temporary exceptions to the above rule. See the TODOs where each
            # variable is declared. Update the comment about "temporary exceptions" in
            # the `fidl_library()` `versioned` attribute when removing the last one.
            if _is_library_in_unsupported_scenarios:
                fidlc_versioned_arg = "unversioned"
            elif _is_banjo_sysmem:
                fidlc_versioned_arg = "fuchsia"
    else:
        if stable or category:
            fail(
                library_name + ": Libraries that are stable and/or have an SDK category must be versioned. This is handled automatically for fuchsia.* libraries but must be displayed for other libraries.",
            )
        fidlc_versioned_arg = "unversioned"

    # Verify the results are in one of the expected combinations.
    if (fidlc_versioned_arg == "fuchsia" and stable and
        requires_compatibility_tests and
        (is_idk_included_publishable or
         category == "compat_test" or
         category == "host_tool" or
         category == "prebuilt")):
        # Stable libraries versioned in "fuchsia".
        pass
    elif (fidlc_versioned_arg == "fuchsia" and _is_internal_zx_library and
          not stable and not requires_compatibility_tests and not category):
        # Exception: internal ZX library.
        pass
    elif (fidlc_versioned_arg == "fuchsia" and _is_banjo_sysmem and
          not stable and not requires_compatibility_tests and not category):
        # Exception: Banjo sysmem library.
        pass
    elif (fidlc_versioned_arg == "fuchsia:HEAD" and not stable and
          requires_compatibility_tests == (category != "")):
        # Unstable libraries versioned in "fuchsia".
        pass
    elif (fidlc_versioned_arg == "unversioned" and not stable and
          not requires_compatibility_tests and
          (not category or is_unversioned_vendor_idk)):
        # Unversioned libraries.
        pass
    elif (fidlc_versioned_arg == "unversioned" and not stable and
          not category and not requires_compatibility_tests and
          _is_library_in_unsupported_scenarios):
        # Exception: Unversioned libraries in unsupported scenarios.
        pass
    elif (testonly and not stable and not category and
          not requires_compatibility_tests and
          (fidlc_versioned_arg == "unversioned" or
           fidlc_versioned_arg == "test:1" or
           (fidlc_versioned_arg == "fuchsia" and
            library_name == "fuchsia.examples.docs"))):
        # Test-only libraries are either unversioned or versioned in "test".
        # The examples in the documentation may not conform to the expectations
        # for illustrative purposes, and it does not make sense to change them.
        pass
    else:
        fail(
            "Library '%s' has an unexpected combination of stability ('%s'), versioned ('%s'), SDK category ('%s'), publishable ('%s'), compatibility testing requirements ('%s'), and `testonly` ('%s')." % (
                library_name,
                stable,
                fidlc_versioned_arg,
                category,
                is_idk_included_publishable,
                requires_compatibility_tests,
                testonly,
            ),
        )

    return fidlc_versioned_arg, requires_compatibility_tests

# LINT.ThenChange(//build/fidl/fidl_library.gni:determine_fidlc_versioned_arg)

# LINT.IfChange(available_default)
def _get_available(ctx):
    if ctx.attr.available:
        return ctx.attr.available

    # Overlay: upstream reads its own API level flag (default PLATFORM). The overlay
    # reads rules_fuchsia's on Fuchsia (the macro passes it only there: it fails
    # analysis when unset, as on host) and uses PLATFORM elsewhere.
    if ctx.attr.fuchsia_api_level:
        api_level = ctx.attr.fuchsia_api_level[FuchsiaAPILevelInfo].level
    else:
        api_level = "PLATFORM"

    if api_level == "PLATFORM":
        # FIDL directly supports targeting multiple API levels. "PLATFORM" is a
        # meta-level that refers to the set of all supported API levels.
        return ["fuchsia:" + ",".join(runtime_supported_api_levels)]
    else:
        return ["fuchsia:" + api_level]

# LINT.ThenChange(//build/fidl/fidl_library.gni:available_default)

def _fidlc_impl(ctx):
    library_name = ctx.attr.library_name

    # Overlay: upstream names the file after fidl_library_target_name (the same value).
    json_representation = ctx.actions.declare_file("%s.fidl.json" % ctx.label.name)

    # Overlay: --files groups, each library after the ones it depends on, as
    # rules_fuchsia's fuchsia_fidl_library (upstream: a response file).
    libraries = []
    seen = {}
    for dep in ctx.attr.deps:
        for lib in dep[FidlLibraryInfo].libraries:
            if lib.name not in seen:
                seen[lib.name] = True
                libraries.append(lib)
    if library_name in seen:
        fail("%s: the FIDL library %s depends on itself" % (ctx.label, library_name))
    libraries.append(struct(name = library_name, files = ctx.files.srcs))

    args = ctx.actions.args()
    args.add("--json", json_representation)
    args.add("--name", library_name)
    if ctx.attr.versioned:
        args.add("--versioned", ctx.attr.versioned)
    for available_value in _get_available(ctx):
        args.add("--available", available_value)
    for flag in ctx.attr.experimental_flags:
        args.add("--experimental", flag)
    inputs = []
    for lib in libraries:
        args.add_all("--files", lib.files)
        inputs.extend(lib.files)

    ctx.actions.run(
        executable = ctx.executable._fidlc,
        arguments = [args],
        inputs = inputs,
        outputs = [json_representation],
        mnemonic = "Fidlc",
        progress_message = "Compiling FIDL library %s (%%{label})" % library_name,
    )

    return [
        DefaultInfo(files = depset([json_representation])),
        FidlLibraryInfo(
            name = library_name,
            ir = json_representation,
            libraries = libraries,
        ),
    ]

fidl_ir = rule(
    doc = "Runs the IDK's FIDL compiler to generate the FIDL IR.",
    implementation = _fidlc_impl,
    attrs = {
        "library_name": attr.string(
            doc = "Name of the FIDL library.",
            mandatory = True,
        ),
        "srcs": attr.label_list(
            doc = "List of `.fidl` source files.",
            mandatory = True,
            allow_files = [".fidl"],
            allow_empty = False,
        ),
        "deps": attr.label_list(
            doc = "List of labels of other fidl_ir targets on which this library depends.",
            providers = [FidlLibraryInfo],
        ),
        "available": attr.string_list(
            doc = "See `fidl_library()`. Empty: the target API level (see _get_available).",
        ),
        "versioned": attr.string(
            doc = "See `fidl_library()`.",
        ),
        "experimental_flags": attr.string_list(
            doc = "A list of experimental fidlc features to enable.",
        ),
        # Overlay: rules_fuchsia's API level setting, set by the macro on Fuchsia only.
        "fuchsia_api_level": attr.label(
            doc = "rules_fuchsia's API level setting on Fuchsia; None elsewhere (PLATFORM).",
            providers = [FuchsiaAPILevelInfo],
        ),
        "_fidlc": attr.label(
            doc = "The FIDL compiler (the IDK's, D7).",
            default = "@fuchsia_sdk//tools:x64/fidlc",
            allow_single_file = True,
            executable = True,
            cfg = "exec",
        ),
    },
)

def _fidl_library_impl(
        name,
        srcs,
        library_name,
        category,
        stable,
        api_area,  # buildifier: disable=unused-variable
        deps,
        api_file_path,  # buildifier: disable=unused-variable
        versioned,
        available,
        experimental_flags,
        experimental_checks,  # buildifier: disable=unused-variable
        excluded_checks,  # buildifier: disable=unused-variable
        goldens_dir,  # buildifier: disable=unused-variable
        contains_drivers,
        enable_cpp,  # buildifier: disable=unused-variable
        enable_hlcpp,  # buildifier: disable=unused-variable
        enable_rust,
        enable_rust_next,
        enable_rust_drivers,
        enable_banjo,  # buildifier: disable=unused-variable
        enable_zither,  # buildifier: disable=unused-variable
        additional_cpp_configs,
        non_fidl_deps,  # buildifier: disable=unused-variable - For GN conversion only.
        testonly,
        visibility):
    """Implementation of the fidl_library() macro."""

    if available and not testonly:
        fail("`available` is only allowed for `testonly` libraries.")
    if enable_rust_drivers and not enable_rust:
        fail("`enable_rust_drivers` requires `enable_rust`.")
    if additional_cpp_configs:
        fail("`additional_cpp_configs` is not yet supported. A different mechanism will be needed to support this in Bazel.")

    # IMPORTANT: The name of this target must be the the same as the name that
    # will be used in the `deps` of other FIDL libraries for reasons described
    # in `fidl_ir()`.
    fidl_ir_target_name = name

    fidlc_versioned_arg, _ = _get_fidlc_versioned_arg(
        library_name = library_name,
        versioned = versioned,
        category = category,
        stable = stable,
        testonly = testonly,
    )

    # LINT.IfChange(ir_compilation)
    # Overlay: upstream's fidl_ir() adds fidl-lint and JSON-schema validation targets
    # around the fidlc target; the overlay runs fidlc only (see the file header).
    fidl_ir(
        name = fidl_ir_target_name,
        library_name = library_name,
        srcs = srcs,
        deps = deps,
        available = available,
        versioned = fidlc_versioned_arg,
        experimental_flags = experimental_flags,
        fuchsia_api_level = select({
            "@platforms//os:fuchsia": "@fuchsia_sdk//flags:fuchsia_api_level",
            "//conditions:default": None,
        }),
        testonly = testonly,
        # Other FIDL libraries depend on the IR target.
        visibility = visibility,
    )
    # LINT.ThenChange(//build/fidl/fidl_library.gni:ir_compilation)

    # Overlay: the summary, compatibility tests, C++/HLCPP, Banjo, Zither and IDK atom
    # targets upstream declares here are not built.

    if enable_rust:
        fidl_rust_library(
            name = name,
            fidl_library_name = library_name,
            fidl_ir_json = fidl_ir_target_name,
            deps = deps,
            contains_drivers = contains_drivers,
            # Overlay: upstream's Bazel rule does not take it yet; GN's fidl() passes
            # contains_drivers to the Rust bindings only with enable_rust_drivers.
            enable_rust_drivers = enable_rust_drivers,
            testonly = testonly,
            visibility = visibility,
        )

    if enable_rust_next:
        # TODO(https://fxbug.dev/454452299): Implement next-generation Rust bindings and conversions.
        # Overlay: the rust_next flavor from GN (fidl.gni, fidl_rust_next.gni; milestone
        # M8b), with the driver transport for contains_drivers libraries (M9a). Conversion
        # crates are not built.
        fidl_rust_next_library(
            name = name,
            fidl_library_name = library_name,
            fidl_ir_json = fidl_ir_target_name,
            deps = deps,
            contains_drivers = contains_drivers,
            testonly = testonly,
            visibility = visibility,
        )

_fidl_library = macro(
    doc = """Declares a FIDL library.

Use the `fidl_library()` wrapper instead.

Overlay: builds the IR and the Rust bindings only (see //rules:fidl.bzl's header).""",
    implementation = _fidl_library_impl,
    attrs = {
        "srcs": attr.label_list(
            doc = """List of `.fidl` source files for the library.
GN equivalent: `sources`""",
            mandatory = True,
            allow_files = True,
            allow_empty = False,
            configurable = False,
        ),
        "library_name": attr.string(
            doc = """Name of the library.
When using the wrapper macro: Defaults to `name`.
GN equivalent: `name`""",
            mandatory = True,
            configurable = False,
        ),
        "category": attr.string(
            doc = "Publication level of the library in the IDK. See _create_idk_atom().",
            values = ["compat_test", "host_tool", "prebuilt", "partner", ""],
            mandatory = False,
            configurable = False,
        ),
        "stable": attr.bool(
            doc = """Whether this FIDL library is stabilized.
When True, a `.api` file is generated. When False, the atom is marked as unstable in the final IDK.""",
            mandatory = False,
            configurable = False,
            default = False,
        ),
        "api_area": attr.string(
            doc = """The API area responsible for maintaining this library.
GN equivalent: `sdk_area`""",
            mandatory = False,
        ),
        "deps": attr.label_list(
            doc = """List of `Label`s for other FIDL libraries on which this library depends.
Must not contain `select()` statements.
GN equivalent: `public_deps`""",
            default = [],
            configurable = False,
        ),
        "api_file_path": attr.label(
            doc = """Override path for the file representing the API of this library.
Overlay: ignored (no IDK atoms); scripts/regen.py sets it to None.""",
            allow_single_file = True,
            configurable = False,
        ),
        "versioned": attr.string(
            doc = """String of the form "PLATFORM" or "PLATFORM:VERSION".
If provided, fidlc will validate that the library is versioned under PLATFORM and added at
VERSION (if provided). See upstream's fidl_library.bzl for the defaults.""",
            configurable = False,
        ),
        "available": attr.string_list(
            doc = """List of strings of the form "PLATFORM:VERSION". Only allowed on
`testonly` libraries. If not specified, appropriate values will be determined based on
the target API level.""",
            configurable = False,
        ),
        "experimental_flags": attr.string_list(
            doc = "List of experimental `fidlc` features to enable.",
            configurable = False,
        ),
        "experimental_checks": attr.string_list(
            doc = "List of `fidl-lint` check IDs to include. Overlay: fidl-lint is not run.",
            configurable = False,
        ),
        "excluded_checks": attr.string_list(
            doc = "List of `fidl-lint` check IDs to ignore. Overlay: fidl-lint is not run.",
            configurable = False,
        ),
        "goldens_dir": attr.string(
            doc = "Golden files for compatibility tests. Overlay: ignored.",
            default = "//sdk/history",
            configurable = False,
        ),
        "contains_drivers": attr.bool(
            doc = "Indicates whether any of the FIDL files contain the " +
                  "driver transport or references to the driver transport.",
            default = False,
            configurable = False,
        ),
        "enable_cpp": attr.bool(
            doc = "Set to False to disable the new C++ bindings for this library. Overlay: ignored.",
            default = True,
            configurable = False,
        ),
        "enable_hlcpp": attr.bool(
            doc = "Set to True to enable legacy HLCPP bindings for this library. Overlay: ignored.",
            default = False,
            configurable = False,
        ),
        "enable_rust": attr.bool(
            doc = "Set to False to disable Rust bindings for this library",
            default = True,
            configurable = False,
        ),
        "enable_rust_next": attr.bool(
            doc = "Set to False to disable next-generation Rust bindings for this library",
            default = True,
            configurable = False,
        ),
        "enable_rust_drivers": attr.bool(
            doc = "Set to True to enable experimental rust driver transport support",
            default = False,
            configurable = False,
        ),
        "enable_banjo": attr.bool(
            doc = "Set to True to enable Banjo bindings for this library. Overlay: ignored.",
            default = False,
            configurable = False,
        ),
        "enable_zither": attr.bool(
            doc = "Set to True to enable Zither bindings for this library. Overlay: ignored.",
            default = False,
            configurable = False,
        ),
        "testonly": attr.bool(
            doc = "Standard meaning.",
            default = False,
            configurable = False,
        ),
        "additional_cpp_configs": attr.string_list(
            doc = "Unused in Bazel, for GN conversion only.",
            default = [],
            configurable = False,
        ),
        "non_fidl_deps": attr.string_list(
            doc = "Unused in Bazel, for GN conversion only.",
            default = [],
            configurable = False,
        ),
    },
)

def fidl_library(
        *,
        name,
        library_name = "",
        **kwargs):
    """Declares a FIDL library.

    This is a wrapper around `_fidl_library()` that defaults `library_name` to `name`.
    Overlay: upstream's also derives `api_file_path` and the HLCPP deps, which the overlay
    does not use.

    See `_fidl_library()` for documentation.
    """
    if not library_name:
        library_name = name

    _fidl_library(
        name = name,
        library_name = library_name,
        **kwargs
    )
