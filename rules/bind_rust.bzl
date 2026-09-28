# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0

"""fuchsia_bind_rust_library: the Rust crate of a bind library (milestone M10).

GN gives every `bind_library` a Rust crate, `<target>_rust`, named
`bind_<library name with "." replaced by "_">` (build/bind/bind.gni,
`_bind_library_rust`): `bindc generate-rust --lint` writes one source file, compiled as a
`rustc_library` (edition 2024, lint config `deny_unused_results`), depending on the
`_rust` crates of the library's `public_deps`. rules_fuchsia has only the C++ equivalent
(`fuchsia_bind_cc_library`, which runs `bindc generate-cpp`); this is its Rust
counterpart, using the same `bindc` (the SDK toolchain's, from the IDK) on a
`fuchsia_bind_library` such as `@fuchsia_sdk//bind/fuchsia.test`.
"""

load("@rules_fuchsia//fuchsia/private:fuchsia_toolchains.bzl", "FUCHSIA_TOOLCHAIN_DEFINITION", "get_fuchsia_sdk_toolchain")
load("@rules_fuchsia//fuchsia/private:providers.bzl", "FuchsiaBindLibraryInfo")
load(":rustc.bzl", "rustc_library")

def _bind_rust_source_impl(ctx):
    info = ctx.attr.library[FuchsiaBindLibraryInfo]
    sources = ctx.attr.library[DefaultInfo].files.to_list()
    if len(sources) != 1:
        fail("Expected exactly 1 bind library source from %s, got %s" % (ctx.attr.library.label, sources))
    out = ctx.actions.declare_file("%s/%s_lib.rs" % (ctx.label.name, info.name.replace(".", "_")))
    ctx.actions.run(
        executable = get_fuchsia_sdk_toolchain(ctx).bindc,
        arguments = ["generate-rust", "--lint", "--output", out.path, sources[0].path],
        inputs = sources,
        outputs = [out],
        mnemonic = "BindcGenRust",
        progress_message = "Generating the Rust crate source of bind library %{label}",
        toolchain = FUCHSIA_TOOLCHAIN_DEFINITION,
    )
    return [DefaultInfo(files = depset([out]))]

_bind_rust_source = rule(
    implementation = _bind_rust_source_impl,
    toolchains = [FUCHSIA_TOOLCHAIN_DEFINITION],
    attrs = {
        "library": attr.label(
            mandatory = True,
            providers = [FuchsiaBindLibraryInfo],
        ),
    },
)

def _fuchsia_bind_rust_library_impl(name, visibility, library, library_name, deps, target_compatible_with):
    source = name + "_source"
    _bind_rust_source(
        name = source,
        library = library,
        target_compatible_with = target_compatible_with,
        visibility = ["//visibility:private"],
    )
    rustc_library(
        name = name,
        crate_name = "bind_" + library_name.replace(".", "_"),
        edition = "2024",
        srcs = [":" + source],
        crate_root = ":" + source,
        lint_config = Label("//rules/lints:bind_rust"),
        deps = deps,
        target_compatible_with = target_compatible_with,
        visibility = visibility,
    )

fuchsia_bind_rust_library = macro(
    doc = """The Rust crate `bind_<library_name>` of a fuchsia_bind_library (GN: `<target>_rust`).

`library_name` is the bind library's name (e.g. "fuchsia.test"); `deps` are the Rust
crates of the libraries it depends on (GN: its public_deps' `_rust` targets).
""",
    implementation = _fuchsia_bind_rust_library_impl,
    attrs = {
        "library": attr.label(mandatory = True, configurable = False),
        "library_name": attr.string(mandatory = True, configurable = False),
        "deps": attr.label_list(default = []),
        "target_compatible_with": attr.label_list(
            default = ["@platforms//os:fuchsia"],
            configurable = False,
        ),
    },
)
