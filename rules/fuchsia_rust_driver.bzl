# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0

"""fuchsia_rust_driver: a Rust DFv2 driver (a cdylib) for rules_fuchsia's driver packaging.

Design R7 and §4.2 "Driver rule"; milestone M10. Neither rules_fuchsia nor fuchsia.git's
Bazel build has a Rust driver rule at the lock's revision, so this one is modeled on
rules_fuchsia's C++ equivalent, `fuchsia_cc_driver` (fuchsia/private/fuchsia_cc_driver.bzl)
wrapping `fuchsia_cc` (fuchsia/private/fuchsia_cc.bzl), and on GN's
`fuchsia_rust_driver` (build/drivers/fuchsia_driver.gni):

- The shared library is a rules_rust `rust_shared_library` (crate type `cdylib`; GN:
  `rustc_cdylib`) with soname `<output_name>.so`, linked with `-Wl,--version-script=`
  rules_fuchsia's `driver.ld`, so it exports only `__fuchsia_driver_registration__`
  (design F3), and against `@fuchsia_sdk//pkg/driver_runtime_shared_lib`, as
  `fuchsia_cc_driver` links it.
- Lints: `//rules/lints:fuchsia_rust_driver` by default (GN's
  `set_defaults("fuchsia_rust_driver")` adds `allow_unused_crate_dependencies`) and
  `--cap-lints=deny`, as `rustc_library`.
- `fuchsia_rust_driver` (the target named `name`) returns what `fuchsia_cc` returns for a
  driver: `FuchsiaUnstrippedBinariesInfo` with the library at `driver/<output_name>.so`
  plus the shared libraries its runfiles carry at `lib/`, an empty
  `FuchsiaPackageResourcesInfo`, and clang's `FuchsiaDebugSymbolInfo`; its `data` and
  `implicit_deps` bring the sysroot's and fdio's `dist` resources, as `fuchsia_cc_driver`
  and `fuchsia_cc` do. `fuchsia_driver_component(driver_lib = ...)` takes it unchanged.
- rules_fuchsia's restricted-symbols check (`//fuchsia/tools:check_restricted_symbols`
  against `driver_restricted_symbols.txt`) runs as a build action on the library, as
  `fuchsia_cc` runs it when `restricted_symbols` is set; the packaged file is the
  checked copy, so packaging cannot skip the check. (`fuchsia_cc_driver` itself leaves
  the check disabled, TODO(352586714).)
- The shared libraries the library's runfiles carry are packaged at `lib/`, including
  `libdriver_runtime.so` and `libasync-default.so`, as `fuchsia_cc_driver` does and as
  the pure-Rust drivers in the lock's `core.x64` bundle do (docs/evidence/M10.md); the
  driver host has its own `libdriver_runtime.so`, which C++ drivers there rely on.
- `with_unit_tests` and `test_deps` are accepted so GN's arguments translate unchanged,
  but no test target is generated yet (GN's `-test-staticlib`; milestone M16, design R9).

`fuchsia_driver_elf_test` checks a packaged driver's ELF files: the exported-symbols
check of R7 and the `DT_NEEDED` sets. `fuchsia_driver_manifest_test` checks its compiled
manifest's shards.
"""

load("@rules_fuchsia//fuchsia/private:providers.bzl", "FuchsiaPackageResourcesInfo")
load("@rules_fuchsia//fuchsia_rules_common:utils.bzl", "find_cc_toolchain", "get_runfiles_shared_lib_binary_info")
load(
    "@rules_fuchsia//fuchsia_rules_common/debug_symbols:providers.bzl",
    "FuchsiaDebugSymbolInfo",
    "FuchsiaUnstrippedBinariesInfo",
    "FuchsiaUnstrippedBinaryInfo",
    "make_fuchsia_unstripped_binary_info",
)
load("@rules_fuchsia//fuchsia_rules_common/packages:providers.bzl", "FuchsiaPackageInfo")
load("@rules_rust//rust:defs.bzl", "rust_shared_library")
load(":rustc.bzl", "with_fuchsia_rustc_flags")

_DRIVER_LD = Label("@rules_fuchsia//fuchsia/private:driver.ld")
_DRIVER_RUNTIME = Label("@fuchsia_sdk//pkg/driver_runtime_shared_lib")
_LINT_CONFIG = Label("//rules/lints:fuchsia_rust_driver")
_FUCHSIA = [Label("@platforms//os:fuchsia")]

# Libraries a driver may need that its package does not ship under their own name:
# libc.so is the soname of lib/ld.so.1 (the sysroot's dist), libzircon.so the vDSO. In
# the lock's core.x64 bundle every other needed library of the Rust drivers is shipped
# at lib/ (docs/evidence/M10.md).
SYSTEM_LIBS = ["libc.so", "libzircon.so"]

# --- The driver library -----------------------------------------------------------------

def _fuchsia_rust_driver_binary_impl(ctx):
    native = ctx.attr.native_target[DefaultInfo]
    libs = [f for f in native.files.to_list() if f.extension == "so"]
    if len(libs) != 1:
        fail("Expected exactly 1 shared library from %s, got %s" % (ctx.attr.native_target.label, libs))
    target_in = libs[0]

    # rules_fuchsia's restricted-symbols check, as fuchsia_cc runs it. The tool copies its
    # input to the output only when the check passes.
    cc_toolchain = find_cc_toolchain(ctx)
    target_out = ctx.actions.declare_file(ctx.label.name + "/" + ctx.attr.bin_name)
    ctx.actions.run(
        executable = ctx.executable._check_restricted_symbols,
        arguments = [
            "--binary",
            target_in.path,
            "--objdump",
            cc_toolchain.objdump_executable,
            "--output",
            target_out.path,
            "--restricted_symbols_file",
            ctx.file._restricted_symbols.path,
        ],
        inputs = [target_in, ctx.file._restricted_symbols],
        outputs = [target_out],
        tools = cc_toolchain.all_files,
        progress_message = "Checking that driver %{label} does not import restricted symbols",
        mnemonic = "CheckRestrictedSymbols",
    )

    binaries = [
        make_fuchsia_unstripped_binary_info(
            dest = "driver/" + ctx.attr.bin_name,
            unstripped_file = target_out,
        ),
    ] + get_runfiles_shared_lib_binary_info(
        runfiles = native.default_runfiles,
        exclude_libs = [
            target_in.basename,
            # As fuchsia_cc: implicit_deps adds it unconditionally.
            "libfdio.so",
        ] + SYSTEM_LIBS,
    )

    return [
        DefaultInfo(files = depset([target_out])),
        FuchsiaPackageResourcesInfo(resources = []),
        FuchsiaUnstrippedBinariesInfo(binaries = binaries),
        ctx.attr.clang_debug_symbols[FuchsiaDebugSymbolInfo],
    ]

_fuchsia_rust_driver_binary = rule(
    implementation = _fuchsia_rust_driver_binary_impl,
    doc = "Attaches driver packaging metadata to a Rust cdylib (as fuchsia_cc does for C++).",
    toolchains = ["@bazel_tools//tools/cpp:toolchain_type"],
    attrs = {
        "bin_name": attr.string(
            doc = "The file name under driver/ in the package.",
            mandatory = True,
        ),
        "native_target": attr.label(
            doc = "The rust_shared_library (crate type cdylib).",
            mandatory = True,
            providers = [DefaultInfo],
        ),
        "clang_debug_symbols": attr.label(
            doc = "Clang debug symbols (as fuchsia_cc).",
            default = "@fuchsia_sdk//clang:debug_symbols",
            providers = [FuchsiaDebugSymbolInfo],
        ),
        "implicit_deps": attr.label_list(
            doc = "Resources every driver package carries (as fuchsia_cc: libfdio.so).",
            default = ["@fuchsia_sdk//pkg/fdio:dist"],
        ),
        "data": attr.label_list(
            doc = "Packaged files needed at run time (as fuchsia_cc_driver: the sysroot's ld.so.1).",
            providers = [
                [FuchsiaPackageResourcesInfo],
                [FuchsiaUnstrippedBinaryInfo],
                [FuchsiaUnstrippedBinariesInfo],
            ],
        ),
        "_restricted_symbols": attr.label(
            default = "@rules_fuchsia//fuchsia/private:driver_restricted_symbols.txt",
            allow_single_file = True,
        ),
        "_check_restricted_symbols": attr.label(
            default = "@rules_fuchsia//fuchsia/tools:check_restricted_symbols",
            executable = True,
            cfg = "exec",
        ),
        "_cc_toolchain": attr.label(
            default = Label("@bazel_tools//tools/cpp:current_cc_toolchain"),
        ),
    },
)

def _fuchsia_rust_driver_impl(
        name,
        visibility,
        output_name,
        with_unit_tests,  # buildifier: disable=unused-variable
        test_deps,  # buildifier: disable=unused-variable
        crate_name,
        deps,
        compile_data,
        rustc_flags,
        lint_config,
        target_compatible_with,
        tags,
        **kwargs):
    cdylib = name + ".cdylib"
    bin_name = (output_name or name) + ".so"
    rust_shared_library(
        name = cdylib,
        # GN names the crate after the target (rustc_cdylib without `name`).
        crate_name = crate_name or name.replace("-", "_"),
        deps = (deps or []) + [_DRIVER_RUNTIME],
        compile_data = (compile_data or []) + [_DRIVER_LD],
        rustc_flags = with_fuchsia_rustc_flags(rustc_flags) + [
            "-Clink-arg=-Wl,--version-script=$(execpath %s)" % _DRIVER_LD,
            # As GN's and fuchsia_cc_driver's shared libraries: the soname is the file
            # name (the core.x64 Rust drivers have DT_SONAME <output_name>.so).
            "-Clink-arg=-Wl,-soname=" + bin_name,
        ],
        lint_config = lint_config or _LINT_CONFIG,
        target_compatible_with = target_compatible_with or _FUCHSIA,
        tags = tags,
        visibility = ["//visibility:private"],
        **kwargs
    )
    _fuchsia_rust_driver_binary(
        name = name,
        bin_name = bin_name,
        native_target = ":" + cdylib,
        data = ["@fuchsia_sdk//pkg/sysroot:dist"],
        target_compatible_with = target_compatible_with or _FUCHSIA,
        tags = tags,
        visibility = visibility,
    )

fuchsia_rust_driver = macro(
    doc = """A Rust DFv2 driver: a cdylib linked with rules_fuchsia's driver.ld.

The target `name` goes in `fuchsia_driver_component(driver_lib = ...)`; the library is
packaged at `driver/<output_name>.so` (default: `name`). The default lint_config is
//rules/lints:fuchsia_rust_driver (unused crate dependencies allowed, as GN). Fuchsia-only
unless target_compatible_with says otherwise. with_unit_tests and test_deps are accepted
but generate nothing yet (M16).
""",
    implementation = _fuchsia_rust_driver_impl,
    inherit_attrs = rust_shared_library,
    attrs = {
        "output_name": attr.string(
            doc = "The library's file name under driver/, without `.so` (GN's output_name).",
            configurable = False,
        ),
        "with_unit_tests": attr.bool(
            doc = "Accepted but not yet implemented (milestone M16).",
            default = False,
            configurable = False,
        ),
        "test_deps": attr.label_list(
            doc = "Extra dependencies for the test target (not yet generated, M16).",
            default = [],
        ),
    },
)

# --- The package tests -----------------------------------------------------------------

def _resources_file(ctx, package):
    """Writes the package's resources as "<dest>=<runfiles path>" lines; returns (file, srcs)."""
    resources = package[FuchsiaPackageInfo].package_resources
    out = ctx.actions.declare_file(ctx.label.name + ".resources")
    ctx.actions.write(out, "".join(sorted([
        "%s=%s\n" % (r.dest, r.src.short_path)
        for r in resources
    ])))
    return out, [r.src for r in resources]

def _test_launcher(ctx, script, args, files):
    executable = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.write(
        executable,
        "#!/bin/bash\nexec %s %s\n" % (
            script.short_path,
            " ".join(["'%s'" % a for a in args]),
        ),
        is_executable = True,
    )
    return DefaultInfo(
        executable = executable,
        runfiles = ctx.runfiles(files = files + [script]),
    )

def _fuchsia_driver_elf_test_impl(ctx):
    resources, srcs = _resources_file(ctx, ctx.attr.package)
    return [_test_launcher(ctx, ctx.file._script, [
        ctx.file._readelf.short_path,
        resources.short_path,
        ctx.attr.driver,
        " ".join(sorted(ctx.attr.exported_symbols)),
        " ".join(sorted(ctx.attr.allowed_needed)),
        " ".join(SYSTEM_LIBS),
    ], srcs + [resources, ctx.file._readelf])]

fuchsia_driver_elf_test = rule(
    implementation = _fuchsia_driver_elf_test_impl,
    test = True,
    doc = """Checks the driver library in a Fuchsia package with llvm-readelf (design R7).

- `--dyn-syms`: the defined, non-local dynamic symbols are exactly `exported_symbols`
  (default: `__fuchsia_driver_registration__`, design F3).
- `--dynamic`: the driver's `DT_NEEDED` libraries are all in `allowed_needed` (the
  reference driver's set, docs/evidence/M10.md), and every ELF file in the package finds
  each library it needs at `lib/` or among SYSTEM_LIBS.

The checked files are the packaged (stripped) ones, as the driver host loads them.
""",
    attrs = {
        "package": attr.label(
            doc = "The fuchsia_package holding the driver.",
            mandatory = True,
            providers = [FuchsiaPackageInfo],
        ),
        "driver": attr.string(
            doc = "The driver library's path in the package (driver/<name>.so).",
            mandatory = True,
        ),
        "exported_symbols": attr.string_list(
            default = ["__fuchsia_driver_registration__"],
        ),
        "allowed_needed": attr.string_list(
            doc = "The DT_NEEDED libraries the driver may have.",
            mandatory = True,
        ),
        "_readelf": attr.label(
            default = Label("@fuchsia_clang//:bin/llvm-readelf"),
            allow_single_file = True,
            cfg = "exec",
        ),
        "_script": attr.label(
            default = Label("//rules:driver_elf_test.sh"),
            allow_single_file = True,
        ),
    },
)

def _fuchsia_driver_manifest_test_impl(ctx):
    resources = ctx.attr.package[FuchsiaPackageInfo].package_resources
    cms = [r.src for r in resources if r.dest == ctx.attr.component]
    if len(cms) != 1:
        fail("%s has no %s" % (ctx.attr.package.label, ctx.attr.component))
    return [_test_launcher(ctx, ctx.file._script, [
        cms[0].short_path,
        " ".join(ctx.attr.shards),
        " ".join(ctx.attr.protocols),
    ], cms)]

fuchsia_driver_manifest_test = rule(
    implementation = _fuchsia_driver_manifest_test_impl,
    test = True,
    doc = """Checks a packaged driver manifest's shards (milestone M10).

GN's `expect_includes` (`//sdk/lib/syslog:client_includes`,
`//sdk/lib/inspect:client_includes`) make a Rust driver's manifest include
`syslog/client.shard.cml` and `inspect/client.shard.cml`; the overlay drops those
targets, so this test checks the compiled manifest in the package instead: it was
compiled with each of `shards` and uses each of `protocols`.
""",
    attrs = {
        "package": attr.label(
            doc = "The fuchsia_package holding the driver component.",
            mandatory = True,
            providers = [FuchsiaPackageInfo],
        ),
        "component": attr.string(
            doc = "The compiled manifest's path in the package (meta/<name>.cm).",
            mandatory = True,
        ),
        "shards": attr.string_list(
            default = ["inspect/client.shard.cml", "syslog/client.shard.cml"],
        ),
        "protocols": attr.string_list(
            default = ["fuchsia.inspect.InspectSink", "fuchsia.logger.LogSink"],
        ),
        "_script": attr.label(
            default = Label("//rules:driver_manifest_test.sh"),
            allow_single_file = True,
        ),
    },
)
