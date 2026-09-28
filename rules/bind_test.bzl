# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0

"""fuchsia_driver_bind_test: `bindc test` on a driver's bind rules (investigation I3).

GN's `driver_bind_rules(tests = ...)` runs `bindc test --lint` on the rules with a JSON
test spec (device properties and the expected outcome, per composite parent for a
composite rule). rules_fuchsia's `fuchsia_driver_bind_bytecode_test` is meant to do the
same, but at this release it passes `bindc` and the bind libraries by their execroot
paths (`external/<repo>/...`) and leaves `bindc` out of the runfiles, so under Bzlmod
the test cannot find them ("No such file or directory"). This rule runs the same command
from the runfiles tree, with the SDK toolchain's `bindc` (the IDK's) and the
`fuchsia_bind_library` sources the rules include.
"""

load("@rules_fuchsia//fuchsia/private:fuchsia_toolchains.bzl", "FUCHSIA_TOOLCHAIN_DEFINITION", "get_fuchsia_sdk_toolchain")
load("@rules_fuchsia//fuchsia/private:providers.bzl", "FuchsiaBindLibraryInfo")

def _quote(s):
    return "'" + s.replace("'", "'\\''") + "'"

def _fuchsia_driver_bind_test_impl(ctx):
    bindc = get_fuchsia_sdk_toolchain(ctx).bindc
    libraries = depset(transitive = [d[FuchsiaBindLibraryInfo].transitive_sources for d in ctx.attr.deps]).to_list()
    # The rules file goes before --include, which takes every value after it.
    args = [bindc.short_path, "test", "--lint", ctx.file.rules.short_path, "--test-spec", ctx.file.tests.short_path]
    if libraries:
        args += ["--include"] + [f.short_path for f in libraries]
    script = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(
        script,
        "#!/bin/bash\nset -euo pipefail\nexec " + " ".join([_quote(a) for a in args]) + "\n",
        is_executable = True,
    )
    return [DefaultInfo(
        executable = script,
        runfiles = ctx.runfiles(files = [bindc, ctx.file.rules, ctx.file.tests] + libraries),
    )]

fuchsia_driver_bind_test = rule(
    implementation = _fuchsia_driver_bind_test_impl,
    doc = """Runs `bindc test --lint` on `rules` with the test spec `tests` (GN's bind test).

`deps` are the `fuchsia_bind_library` targets the rules use (as for
`fuchsia_driver_bind_bytecode`). The spec is bindc's JSON: for a composite rule, a list of
`{"parent": <name>, "tests": [{"name", "expected": "match"|"abort", "device": {key: value}}]}`.
""",
    test = True,
    toolchains = [FUCHSIA_TOOLCHAIN_DEFINITION],
    attrs = {
        "rules": attr.label(mandatory = True, allow_single_file = [".bind"]),
        "tests": attr.label(mandatory = True, allow_single_file = [".json"]),
        "deps": attr.label_list(providers = [FuchsiaBindLibraryInfo]),
    },
)
