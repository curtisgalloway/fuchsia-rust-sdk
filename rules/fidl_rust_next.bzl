# Copyright 2024 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
# (build/rust/fidl_rust_next.bzl: Copyright 2026 The Fuchsia Authors.)
#
# SPDX-FileCopyrightText: 2024 The Fuchsia Authors
# SPDX-FileCopyrightText: 2026 The Fuchsia Authors
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: BSD-2-Clause
#
# The `rust_next` FIDL bindings (design §4.2 "FIDL bindings", R5; milestone M8b), ported
# from the GN templates at the lock's fuchsia_revision (b5274053cc0f):
# build/rust/fidl_rust_next.gni (blob ba4f5f71) and the part of build/fidl/fidl.gni
# (blob 988ab2a7) that instantiates it, plus the allowlist of build/rust/fidl_rust_next.bzl
# (blob b0bc7a1b). Upstream's Bazel fidl_library has no rust_next yet
# (fxbug.dev/454452299), so GN is the reference. The Fuchsia LICENSE is
# LICENSES/BSD-2-Clause.txt. Changes from GN, all marked "Overlay:" below:
#   - Targets: <name>_rust_next and <name>_rust_next_common are the rust_library targets
#     themselves (GN: groups over <name>_rust_next[_common]_internal); dependent bindings
#     use them directly.
#   - Not built: the FDomain flavor (<name>_rust_fdomain_next) and the conversion crate
#     (<name>_rust_next_convert): no crate in pilot 1's closure uses them.
#   - The driver transport (contains_drivers: feature "driver" and
#     //sdk/lib/driver/runtime/rust/fidl, on Fuchsia only) is as GN since milestone M9a,
#     which vendors the driver runtime; before it, the flavor declared no targets for
#     such a library (fidlgen_rust_next uses ::fdf_fidl without a feature gate).
#   - The generator is the release's prebuilt //tools/fidlgen_rust_next (M7); the rustfmt
#     config is fuchsia.git's root rustfmt.toml (//vendor/fuchsia:rustfmt.toml).
#   - Allowlist: upstream's, with labels mapped to //vendor/fuchsia/<path> as regen.py
#     maps visibility, plus the overlay's own packages that must see the crates
#     (_OVERLAY_ALLOWLIST).

"""`rust_next` FIDL bindings (fidl_rust_next.gni) and upstream's fidl_rust_next_allowlist."""

load("@rules_rust//rust:defs.bzl", "rust_library")

# Vendored upstream BUILD files load fidl_rust_next_allowlist from here (scripts/regen.py
# maps //build/rust:fidl_rust_next.bzl to this file).
visibility("public")

# Upstream's fidl_rust_next_allowlist (build/rust/fidl_rust_next.bzl), labels mapped to
# //vendor/fuchsia/<path>. scripts/regen.py fails if it differs from the list at the
# lock's revision (after the same mapping), so keep it in upstream's order and form.
_UPSTREAM_ALLOWLIST = [
    "//vendor/fuchsia/examples:__subpackages__",
    "//vendor/fuchsia/examples/fidl/new/key_value_store/use_generic_values/rust_next:__subpackages__",
    "//vendor/fuchsia/examples/fidl/rust_next:__subpackages__",
    "//vendor/fuchsia/sdk/fidl:__subpackages__",
    "//vendor/fuchsia/sdk/lib/async:__subpackages__",
    "//vendor/fuchsia/sdk/lib/driver:__subpackages__",
    "//vendor/fuchsia/src/bringup/lib/userboot:__subpackages__",
    "//vendor/fuchsia/src/connectivity/bluetooth:__subpackages__",
    "//vendor/fuchsia/src/connectivity/overnet:__subpackages__",
    "//vendor/fuchsia/src/connectivity/wlan:__subpackages__",
    "//vendor/fuchsia/src/devices:__subpackages__",
    "//vendor/fuchsia/src/graphics:__subpackages__",
    "//vendor/fuchsia/src/lib/fdomain:__subpackages__",
    "//vendor/fuchsia/src/lib/fidl/rust_next:__subpackages__",
    "//vendor/fuchsia/src/lib/fuchsia-component:__subpackages__",
    "//vendor/fuchsia/src/tests/fidl/conformance_suite:__subpackages__",
    "//vendor/fuchsia/src/ui/input:__subpackages__",
    "//vendor/fuchsia/src/ui/lib/input_pipeline:__subpackages__",
    "//vendor/fuchsia/src/ui/tools/print-input-report-new:__subpackages__",
    "//vendor/fuchsia/tools/fidl:__subpackages__",
    "//vendor/fuchsia/vendor/google:__subpackages__",
    "//vendor/fuchsia/zircon/kernel/lib/userabi/userboot:__subpackages__",
]

# Overlay: packages of the overlay itself that use the crates. //rules: the bindings
# declared by this file's macro name fidl_next (a symbolic macro's own dependencies are
# checked against the package that defines it; both FIDL macros live in //rules itself).
# //tests/fidl: the crate-name test (milestone M8b). Only packages outside
# //vendor/fuchsia belong here (tests/test_regen.py checks it): upstream's entries are
# in _UPSTREAM_ALLOWLIST, which regen.py checks against the revision.
_OVERLAY_ALLOWLIST = [
    "//rules:__pkg__",
    "//tests/fidl:__pkg__",
]

fidl_rust_next_allowlist = _UPSTREAM_ALLOWLIST + _OVERLAY_ALLOWLIST

# Overlay: labels of the vendored crates (GN: //src/lib/fidl/rust_next/fidl_next:
# fidl_next_internal, which upstream's Bazel file keeps private behind this alias).
_FIDL_NEXT = Label("//vendor/fuchsia/src/lib/fidl/rust_next/fidl_next:fidl_next")
_STATIC_ASSERTIONS = Label("@rust_crates//vendor:static_assertions")
_ZX_TYPES = Label("//vendor/fuchsia/sdk/rust/zx-types")

# The FIDL library zx (upstream //zircon/vdso/zx), whose Rust form is the zx-types crate.
_ZX_FIDL = Label("//vendor/fuchsia/zircon/vdso/zx:zx")

# GN: //sdk/lib/driver/runtime/rust/fidl, added with contains_drivers.
_DRIVER_RUNTIME_FIDL = Label("//vendor/fuchsia/sdk/lib/driver/runtime/rust/fidl")

# GN's lint configs for the bindings, the same as the rust flavor's (fidl_rust_next.gni:
# rustc_library's defaults with disable_clippy, allow_unused_crate_dependencies,
# deny_unused_results).
_LINT_CONFIG = Label("//rules/lints:fidl_rust")

_CONFIGS = "//vendor/fuchsia/tools/fidl/fidlgen_rust_next/configs:"

def fidl_rust_next_library(
        *,
        name,
        fidl_library_name,
        fidl_ir_json,
        deps,
        contains_drivers,
        testonly,
        visibility):
    """Declares <name>_rust_next and <name>_rust_next_common (fidl.gni's rust_next block).

    Args:
        name: the fidl_library target name.
        fidl_library_name: the FIDL library name, e.g. "fuchsia.io".
        fidl_ir_json: the library's IR target.
        deps: the FIDL libraries it depends on (fidl_library targets).
        contains_drivers: the library uses the driver transport. GN forwards it on
            Fuchsia only (fidl.gni: !is_host).
        testonly: usual meaning.
        visibility: the library's visibility; the crates get its intersection with
            fidl_rust_next_allowlist, as fidl.gni computes it.
    """
    crate_visibility = _allowlisted_visibility(visibility)
    common_crate = rust_next_crate_name(fidl_library_name, common = True)
    for common in (True, False):
        _fidl_rust_next_flavor(
            name = name,
            fidl_library_name = fidl_library_name,
            fidl_ir_json = fidl_ir_json,
            deps = deps,
            common = common,
            common_lib = None if common else common_crate,
            contains_drivers = contains_drivers,
            testonly = testonly,
            visibility = crate_visibility,
        )

def rust_next_crate_name(fidl_library_name, common):
    """fidl_rust_next.gni: "${prefix}_next${common}_<library, . -> _>" (prefix "fidl")."""
    return "fidl_next%s_%s" % ("_common" if common else "", fidl_library_name.replace(".", "_"))

def _flavor_suffix(common):
    return "rust_next_common" if common else "rust_next"

def _fidl_rust_next_flavor(*, name, fidl_library_name, fidl_ir_json, deps, common, common_lib, contains_drivers, testonly, visibility):
    suffix = _flavor_suffix(common)
    target = "%s_%s" % (name, suffix)
    generated = target + "_fidlgen"

    _fidlgen_rust_next(
        name = generated,
        fidl_ir_json = fidl_ir_json,
        out = target + ".rs",
        config = Label(_CONFIGS + ("common.json" if common else "fuchsia.json")),
        common_lib = common_lib or "",
        testonly = testonly,
        # Overlay: //tests/fidlgen compares the output with M7's generator tests
        # (tests/fidlgen/fidlgen.bzl's FLAVORS), so the arguments cannot drift apart.
        visibility = ["//tests/fidlgen:__pkg__"],
    )

    library_deps = [_FIDL_NEXT, _STATIC_ASSERTIONS]
    for dep in deps:
        if dep == _ZX_FIDL:
            library_deps.append(_ZX_TYPES)
        else:
            # GN: <dep>_rust_next[_common]_internal; Overlay: the targets themselves.
            library_deps.append(dep.same_package_label("%s_%s" % (dep.name, suffix)))
    if not common:
        library_deps.append(":%s_rust_next_common" % name)

    features = ["fuchsia"]
    driver_deps = []
    if contains_drivers:
        # GN forwards contains_drivers on Fuchsia only (fidl.gni: !is_host).
        features.append("driver")
        driver_deps.append(_DRIVER_RUNTIME_FIDL)

    rust_library(
        name = target,
        crate_name = rust_next_crate_name(fidl_library_name, common),
        srcs = [":" + generated],
        # `select()` must be appended last.
        deps = library_deps + select({
            "@platforms//os:fuchsia": driver_deps,
            "//conditions:default": [],
        }),
        crate_features = select({
            "@platforms//os:fuchsia": features,
            "//conditions:default": [],
        }),
        edition = "2024",
        version = "0.1.0",
        lint_config = _LINT_CONFIG,
        tags = ["noclippy"],
        testonly = testonly,
        visibility = visibility,
    )

# --- visibility: fidl.gni's intersection with the allowlist ---------------------------

def _spec(label):
    """A visibility label as (package, kind): kind is "public", "pkg" or "subpackages"."""
    s = str(label)
    for prefix in ("@@//", "@//"):
        if s.startswith(prefix):
            s = s[len(prefix) - 2:]
    if s == "//visibility:public":
        return ("", "public")
    if s.endswith(":__pkg__"):
        return (s[2:-len(":__pkg__")], "pkg")
    if s.endswith(":__subpackages__"):
        return (s[2:-len(":__subpackages__")], "subpackages")
    fail("Overlay: rust_next visibility supports //visibility:public, :__pkg__ and " +
         ":__subpackages__ only, not %s" % s)

def _covers(pattern, spec):
    """Whether visibility `pattern` matches everything `spec` names (GN's pattern match)."""
    pkg, kind = pattern
    if kind == "public":
        return True
    if spec[1] == "public":
        return False
    if kind == "pkg":
        return spec == pattern
    return spec[0] == pkg or spec[0].startswith(pkg + "/")

def _label_of(spec):
    pkg, kind = spec
    if kind == "public":
        return "//visibility:public"
    return "//%s:__%s__" % (pkg, kind)

def _allowlisted_visibility(visibility):
    """fidl.gni: filter_labels_include(visibility, allowlist) +
    filter_labels_include(allowlist, visibility), with visibility ["*"] when unset."""
    given = [_spec(v) for v in (visibility or ["//visibility:public"])]
    allowed = [_spec(v) for v in fidl_rust_next_allowlist]
    out = []
    for spec in [g for g in given if any([_covers(a, g) for a in allowed])] + \
                [a for a in allowed if any([_covers(g, a) for g in given])]:
        label = _label_of(spec)
        if label not in out:
            out.append(label)

    # An empty list would make the crates visible to their own package only; the macro's
    # package is added by Bazel either way.
    return out or ["//visibility:private"]

# --- the generator -------------------------------------------------------------------

def _fidlgen_rust_next_impl(ctx):
    ir = ctx.file.fidl_ir_json
    rustfmt_config = ctx.file._rustfmt_config
    config = ctx.file.config
    rust_toolchain = ctx.toolchains["@rules_rust//rust:toolchain_type"]
    rustfmt = rust_toolchain.rustfmt

    # fidl_rust_next.gni's arguments, in its order.
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
    if ctx.attr.common_lib:
        arguments += ["--common-lib", ctx.attr.common_lib]
    arguments += ["--config", config.path]

    ctx.actions.run(
        executable = ctx.executable._fidlgen_tool,
        arguments = arguments,
        inputs = [ir, rustfmt, rustfmt_config, config],
        # rustfmt needs the toolchain's shared libraries (librustc_driver).
        tools = rust_toolchain.all_files,
        outputs = [ctx.outputs.out],
        mnemonic = "FidlGenRustNext",
    )
    return [DefaultInfo(files = depset([ctx.outputs.out]))]

_fidlgen_rust_next = rule(
    implementation = _fidlgen_rust_next_impl,
    toolchains = ["@rules_rust//rust:toolchain_type"],
    attrs = {
        "fidl_ir_json": attr.label(
            doc = "The FIDL IR for which to generate code.",
            allow_single_file = True,
            mandatory = True,
        ),
        "config": attr.label(
            doc = "The --config file: configs/common.json for the _common crate, " +
                  "configs/fuchsia.json for the regular one.",
            allow_single_file = True,
            mandatory = True,
        ),
        "common_lib": attr.string(
            doc = "--common-lib: the crate name of the _common crate the regular crate " +
                  "re-exports; empty for the _common crate itself.",
            default = "",
        ),
        "out": attr.output(
            doc = "Output filename.",
            mandatory = True,
        ),
        "_fidlgen_tool": attr.label(
            doc = "fidlgen_rust_next (GN: //tools/fidl/fidlgen_rust_next).",
            executable = True,
            cfg = "exec",
            default = "//tools/fidlgen_rust_next",
        ),
        "_rustfmt_config": attr.label(
            doc = "GN: //rustfmt.toml.",
            allow_single_file = True,
            default = "//vendor/fuchsia:rustfmt.toml",
        ),
    },
)
