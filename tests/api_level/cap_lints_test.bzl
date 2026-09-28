# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0

"""Analysis test: the --cap-lints value a rustc_* target passes to rustc."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")

def _cap_lints_test_impl(ctx):
    env = analysistest.begin(ctx)
    rustc = [a for a in analysistest.target_actions(env) if a.mnemonic == "Rustc"]
    asserts.equals(env, 1, len(rustc), "Rustc actions")
    caps = [arg for arg in rustc[0].argv if arg.startswith("--cap-lints=")]
    asserts.equals(env, ["--cap-lints=" + ctx.attr.expected], caps)
    return analysistest.end(env)

cap_lints_test = analysistest.make(
    _cap_lints_test_impl,
    attrs = {"expected": attr.string(mandatory = True)},
)
