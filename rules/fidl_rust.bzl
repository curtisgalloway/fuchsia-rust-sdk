# Copyright 2026 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# SPDX-FileCopyrightText: 2026 The Fuchsia Authors
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: BSD-2-Clause
#
# Ported from fuchsia.git build/bazel/rules/fidl/fidl_rust_library.bzl at the lock's
# fuchsia_revision (b5274053cc0f), with the crate settings of the GN templates the
# platform build uses, build/fidl/fidl.gni and build/rust/fidl_rust.gni (design §4.2
# "FIDL bindings", R5; milestone M8). The Fuchsia LICENSE is LICENSES/BSD-2-Clause.txt.
# Changes from upstream's Bazel rule, all marked "Overlay:" below:
#   - Flavors: "fidl" (target <name>_rust, crate fidl_<lib>), "common" (<name>_rust_common,
#     fidl_<lib>_common) and the flex crate of "fidl" (<name>_rust_flex, flex_<lib>).
#     The "fdomain" flavor and its flex crate are not built: no crate in pilot 1's closure
#     uses them (FDomain needs //src/lib/fdomain/client's FDomain side).
#   - GN parity (fidl_rust.gni): a FIDL dep on zx is the zx-types crate (upstream's Bazel
#     rule drops it); the crates use GN's lints (rustc_library defaults plus
#     allow_unused_crate_dependencies and deny_unused_results, no clippy:
#     //rules/lints:fidl_rust); `--include-drivers` is passed only on Fuchsia and only
#     with enable_rust_drivers (fidl.gni forwards contains_drivers to fidl_rust() only
#     then).
#   - Driver transport: GN also sets the crate feature "driver" and adds
#     //src/lib/fidl/rust/fidl_driver and //sdk/lib/driver/runtime/rust on Fuchsia.
#     Upstream's Bazel rule leaves them out (fxbug.dev/503359085), and so does the
#     overlay until those crates are vendored (milestone M8b): the generated driver code
#     is all #[cfg(feature = "driver")], so the crates compile without it.
#   - The generator is //tools/fidlgen_rust (built from vendored source, M7), and the
#     rustfmt config is fuchsia.git's root rustfmt.toml (//vendor/fuchsia:rustfmt.toml).
#   - Output files are named <name>_<flavor>.rs, inside the symbolic macro's namespace.

"""Rust bindings for a FIDL library: the `rust` flavor (upstream's fidl_rust_library)."""

load("@rules_rust//rust:defs.bzl", "rust_library")

visibility(["//rules/..."])

# Overlay: labels of the vendored crates (upstream: //sdk/rust/zx-status and so on).
_ZX = Label("//vendor/fuchsia/sdk/rust/zx")
_ZX_STATUS = Label("//vendor/fuchsia/sdk/rust/zx-status")
_ZX_TYPES = Label("//vendor/fuchsia/sdk/rust/zx-types")
_FIDL = Label("//vendor/fuchsia/src/lib/fidl/rust/fidl")
_BITFLAGS = Label("@rust_crates//vendor:bitflags")
_FUTURES = Label("@rust_crates//vendor:futures")

# The FIDL library zx (upstream //zircon/vdso/zx), whose Rust form is the zx-types crate.
_ZX_FIDL = Label("//vendor/fuchsia/zircon/vdso/zx:zx")

# Overlay: GN's lint configs for the bindings (see the header).
_LINT_CONFIG = Label("//rules/lints:fidl_rust")

# Overlay: the driver transport (feature "driver", fidl_driver, the driver runtime) is
# milestone M8b; see the header.
_DRIVER_TRANSPORT = False

def fidl_rust_library(
        *,
        name,
        fidl_library_name,
        fidl_ir_json,
        deps,
        contains_drivers,
        enable_rust_drivers,
        testonly,
        visibility):
    """
    Generates a `rust_library()` providing the generated Rust bindings for a given FIDL library.

    Args:
        name: String base name of the `rust_library()` target.
        fidl_library_name: String name of the FIDL library for which bindings are generated.
        fidl_ir_json: `Label` pointing to a single file containing the FIDL IR
            representation of the `fidl_library_name` library.
        deps: List of `Label`s for FIDL libraries that the `fidl_library_name` library depends on.
        contains_drivers: Boolean indicating whether the `fidl_library_name`
            library supports drivers.
        enable_rust_drivers: Overlay: the fidl_library() argument; the driver
            transport is generated only when both are set (as GN).
        testonly: usual meaning.
        visibility: usual meaning.
    """

    # Overlay: upstream also defines the "fdomain" flavor and its flex crate.
    _fidl_rust_library_flavor("fidl", name, fidl_library_name, fidl_ir_json, deps, contains_drivers and enable_rust_drivers, testonly, visibility)
    _fidl_rust_library_flavor("common", name, fidl_library_name, fidl_ir_json, deps, contains_drivers and enable_rust_drivers, testonly, visibility)
    _fidl_rust_library_flex("fidl", name, fidl_library_name, testonly, visibility)

def _fidl_rust_flavor_crate_name(fidl_library_name, flavor):
    base = fidl_library_name.replace(".", "_")
    if flavor == "fidl":
        return "fidl_%s" % base
    elif flavor == "common":
        return "fidl_%s_common" % base
    elif flavor == "fdomain":
        return "fdomain_%s" % base
    else:
        fail("Unknown flavor: %s" % flavor)

def _fidl_rust_flavor_label_suffix(flavor):
    if flavor == "fidl":
        return "rust"
    elif flavor == "common":
        return "rust_common"
    elif flavor == "fdomain":
        return "rust_fdomain"
    else:
        fail("Unknown flavor: %s" % flavor)

def _fidl_rust_flavor_label_name(label_name, flavor):
    return label_name + "_" + _fidl_rust_flavor_label_suffix(flavor)

def _fidl_rust_flavor_label(label, flavor):
    # Overlay: same_package_label keeps the repository (upstream builds a "//pkg:name" string).
    return label.same_package_label(_fidl_rust_flavor_label_name(label.name, flavor))

def _fidl_rust_library_flavor(flavor, name, fidl_library_name, fidl_ir_json, deps, include_drivers, testonly, visibility):
    flavor_label = name + "_" + _fidl_rust_flavor_label_suffix(flavor)

    fidlgen_label = flavor_label + "_fidlgen"

    if flavor == "common":
        use_common = ""
    else:
        use_common = _fidl_rust_flavor_crate_name(fidl_library_name, "common")

    _fidlgen_rust(
        name = fidlgen_label,
        fidl_ir_json = fidl_ir_json,
        # Overlay: upstream writes bindings/rust/<name>[_common|__fdomain].rs.
        out = flavor_label + ".rs",
        # Overlay: GN passes --include-drivers on Fuchsia only (fidl.gni: !is_host).
        contains_drivers = select({
            "@platforms//os:fuchsia": include_drivers,
            "//conditions:default": False,
        }),
        common = (flavor == "common"),
        fdomain = (flavor == "fdomain"),
        use_common = use_common,
        testonly = testonly,
        visibility = ["//visibility:private"],
    )

    library_deps = [
        _ZX_STATUS,
        _FIDL,
        _BITFLAGS,
        _FUTURES,
    ]

    if flavor == "fdomain":
        fail("Overlay: the fdomain flavor is not built (see //rules:fidl_rust.bzl)")

    for dep in deps:
        if dep == _ZX_FIDL:
            # Overlay: GN (fidl_rust.gni) adds zx-types; upstream's Bazel rule skips zx.
            library_deps.append(_ZX_TYPES)
            continue

        library_deps.append(_fidl_rust_flavor_label(dep, flavor))

    if flavor != "common":
        library_deps.append(":" + _fidl_rust_flavor_label_name(name, "common"))

    if include_drivers and _DRIVER_TRANSPORT:
        # TODO(https://fxbug.dev/503359085): driver transport support
        #     library_deps += [
        #         "//src/lib/fidl/rust/fidl_driver",
        #         "//sdk/lib/driver/runtime/rust",
        #     ]
        # Overlay: milestone M8b, with crate_features = ["driver"] on Fuchsia.
        pass

    # `select()` must be appended last.
    library_deps += select({
        "@platforms//os:fuchsia": [_ZX],
        "//conditions:default": [],
    })

    rust_library(
        name = flavor_label,
        crate_name = _fidl_rust_flavor_crate_name(fidl_library_name, flavor),
        srcs = [fidlgen_label],
        deps = library_deps,
        edition = "2018",
        # Overlay: GN's lints (the header); upstream's Bazel rule sets only the tag.
        lint_config = _LINT_CONFIG,
        tags = ["noclippy"],
        testonly = testonly,
        visibility = visibility,
    )

def _fidl_rust_library_flex(flavor, name, fidl_library_name, testonly, visibility):
    original_label = name + "_" + _fidl_rust_flavor_label_suffix(flavor)
    original_crate_name = _fidl_rust_flavor_crate_name(fidl_library_name, flavor)

    flex_label = original_label + "_flex"
    flex_generate_label = flex_label + "_generate"

    base_library_name = fidl_library_name.replace(".", "_")
    flex_crate_name = "flex_%s" % base_library_name

    # Overlay: upstream writes bindings/rust/<name>_<flavor>_flex.rs.
    flex_file_name = flex_label + ".rs"

    native.genrule(
        name = flex_generate_label,
        outs = [flex_file_name],
        cmd = "echo 'pub use %s::*;' > $@" % original_crate_name,
        testonly = testonly,
        visibility = ["//visibility:private"],
    )

    rust_library(
        name = flex_label,
        crate_name = flex_crate_name,
        srcs = [flex_generate_label],
        deps = [":" + original_label],
        edition = "2024",
        # Overlay: GN (fidl_rust.gni's _flex_crate) uses rustc_library's lints plus
        # deny_unused_results, which //rules/lints:fidl_rust has.
        lint_config = _LINT_CONFIG,
        tags = ["noclippy"],
        testonly = testonly,
        visibility = visibility,
    )

def _fidlgen_rust_impl(ctx):
    if ctx.attr.common != (ctx.attr.use_common == ""):
        fail("'use_common' must be empty if and only if `common` is True.")

    ir = ctx.file.fidl_ir_json
    rustfmt_config = ctx.file._rustfmt_config

    rust_toolchain = ctx.toolchains["@rules_rust//rust:toolchain_type"]
    rustfmt = rust_toolchain.rustfmt

    # The config must be passed explicitly: otherwise rustfmt searches for it
    # in the working directory's ancestors, so local actions (whose execroot
    # is inside the Fuchsia checkout) find //rustfmt.toml while remote actions
    # use rustfmt's defaults, making the output depend on where it ran.
    arguments = [
        "--json",
        ir.path,
        "--output-filename",
        ctx.outputs.out.path,
        "--rustfmt",
        rustfmt.path,
        "--rustfmt-config",
        rustfmt_config.path,
    ]

    if ctx.attr.contains_drivers:
        arguments.append("--include-drivers")
    if ctx.attr.common:
        arguments.append("--common")
    if ctx.attr.fdomain:
        arguments.append("--fdomain")
    if ctx.attr.use_common != "":
        arguments.append("--use_common=" + ctx.attr.use_common)

    ctx.actions.run(
        executable = ctx.executable._fidlgen_tool,
        arguments = arguments,
        inputs = [ir, rustfmt, rustfmt_config],
        tools = rust_toolchain.all_files,
        outputs = [ctx.outputs.out],
        mnemonic = "FidlGenRust",
    )

    return [
        DefaultInfo(files = depset([ctx.outputs.out])),
    ]

_fidlgen_rust = rule(
    implementation = _fidlgen_rust_impl,
    toolchains = ["@rules_rust//rust:toolchain_type"],
    attrs = {
        "fidl_ir_json": attr.label(
            doc = "The FIDL IR for which to generate code.",
            allow_single_file = True,
            mandatory = True,
        ),
        "contains_drivers": attr.bool(
            doc = "Indicates if any of the FIDL files contain the driver transport or " +
                  "references to the driver transport.",
            mandatory = True,
        ),
        "common": attr.bool(
            doc = "If `True`, generate only the common (non-resource) data structures.",
            default = False,
        ),
        "fdomain": attr.bool(
            doc = "If `True`, generate FDomain bindings.",
            default = False,
        ),
        "use_common": attr.string(
            doc = "If not empty, use the given crate name for the common (non-resource) data structures.",
            default = "",
        ),
        "_fidlgen_tool": attr.label(
            doc = "fidlgen_rust tool.",
            executable = True,
            cfg = "exec",
            # Overlay: upstream's @//tools/fidl/fidlgen_rust.
            default = "//tools/fidlgen_rust",
        ),
        "_rustfmt_config": attr.label(
            doc = "rustfmt configuration used to format the generated code.",
            allow_single_file = True,
            # Overlay: upstream's @//:rustfmt.toml (fuchsia.git's root file).
            default = "//vendor/fuchsia:rustfmt.toml",
        ),
        "out": attr.output(
            doc = "Output filename.",
            mandatory = True,
        ),
    },
)
