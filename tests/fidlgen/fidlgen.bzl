# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0

"""Test helpers for the FIDL generators (milestone M7).

fidlgen_rust_outputs runs both generators on one library's JSON IR the way upstream's GN
templates do (build/rust/fidl_rust.gni, build/rust/fidl_rust_next.gni at the lock
revision): each writes a regular crate and a _common crate, formatted by the release's
rustfmt with fuchsia.git's rustfmt.toml. The binding rules (//rules:fidl_rust.bzl,
//rules:fidl_rust_next.bzl) run the generators themselves; BUILD.bazel here checks that
the rust_next rule's output equals these genrules' (M8b).
"""

load("@platforms//host:constraints.bzl", "HOST_CONSTRAINTS")

_RUSTFMT = "@fuchsia_rust_toolchain//:bin/rustfmt"
_RUSTFMT_CONFIG = "//vendor/fuchsia:rustfmt.toml"
_NEXT_CONFIGS = "//vendor/fuchsia/tools/fidl/fidlgen_rust_next/configs:"

# (output suffix, generator, extra arguments); {lib} is the library name with "." -> "_".
FLAVORS = [
    ("rust", "//tools/fidlgen_rust", "--use_common=fidl_{lib}_common"),
    ("rust_common", "//tools/fidlgen_rust", "--common=true"),
    ("rust_next", "//tools/fidlgen_rust_next", "--config $(execpath " + _NEXT_CONFIGS + "fuchsia.json) --common-lib fidl_next_common_{lib}"),
    ("rust_next_common", "//tools/fidlgen_rust_next", "--config $(execpath " + _NEXT_CONFIGS + "common.json)"),
]

def fidlgen_rust_outputs(name, ir, library, rust_args = []):
    """Genrules <name>_<flavor> writing <name>_<flavor>.rs for each of FLAVORS.

    Args:
      name: prefix of the targets and files.
      ir: label of the library's JSON IR.
      library: the FIDL library name, e.g. "fuchsia.mem".
      rust_args: more fidlgen_rust arguments for both of its crates, as fidl_rust.gni's
        shared_fidlgen_args: "--api-coverage=true" (enable_api_coverage) and
        "--include-drivers" (contains_drivers).
    """
    lib = library.replace(".", "_")
    for flavor, tool, extra in FLAVORS:
        if tool == "//tools/fidlgen_rust":
            extra = " ".join(rust_args + [extra])
        native.genrule(
            name = "%s_%s" % (name, flavor),
            srcs = [
                ir,
                _RUSTFMT_CONFIG,
                _NEXT_CONFIGS + "fuchsia.json",
                _NEXT_CONFIGS + "common.json",
            ],
            outs = ["%s_%s.rs" % (name, flavor)],
            cmd = " ".join([
                "$(execpath %s)" % tool,
                "--json $(execpath %s)" % ir,
                "--output-filename $@",
                "--rustfmt $(execpath %s)" % _RUSTFMT,
                "--rustfmt-config $(execpath %s)" % _RUSTFMT_CONFIG,
                extra.format(lib = lib),
            ]),
            tools = [
                tool,
                _RUSTFMT,
                "@fuchsia_rust_toolchain//:rustc_lib",
            ],
            target_compatible_with = HOST_CONSTRAINTS,
            testonly = True,
        )

def _shell_quote(s):
    """s as one single-quoted shell word; a ' inside becomes '\\''."""
    return "'" + s.replace("'", "'\\''") + "'"

def _contains_test_impl(ctx):
    src = ctx.file.src
    lines = ["#!/bin/sh", "set -u", "status=0", "f=%s" % _shell_quote(src.short_path)]
    lines.append("[ -s \"$f\" ] || { echo \"$f: empty or missing\"; exit 1; }")
    for needle in ctx.attr.expected:
        if "\n" in needle:
            fail("contains_test: %r: grep -F matches one line; split it" % needle)
        q = _shell_quote(needle)
        lines.append("grep -qF -- %s \"$f\" || { echo \"$f: no line containing:\" %s; status=1; }" % (q, q))
    lines.append("exit $status")
    script = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(script, "\n".join(lines) + "\n", is_executable = True)
    return [DefaultInfo(executable = script, runfiles = ctx.runfiles(files = [src]))]

contains_test = rule(
    implementation = _contains_test_impl,
    doc = "Passes when `src` is non-empty and contains each string in `expected` (grep -F).",
    attrs = {
        "src": attr.label(allow_single_file = True, mandatory = True),
        "expected": attr.string_list(mandatory = True),
    },
    test = True,
)
