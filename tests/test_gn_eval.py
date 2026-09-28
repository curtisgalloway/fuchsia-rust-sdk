# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/gn_eval.py, the GN subset evaluator closure.py uses (milestone M6)."""

from __future__ import annotations

import pytest

import gn_eval
from gn_eval import UNKNOWN

FUCHSIA = {"is_fuchsia": True, "is_host": False, "current_os": "fuchsia"}
HOST = {"is_fuchsia": False, "is_host": True, "current_os": "linux"}

# The shape bazel2gn writes (src/lib/diagnostics/log/rust/BUILD.gn at the release): deps
# in file-level variables, built under conditions, then assigned to targets.
BAZEL2GN = '''\
import("//build/rust/rustc_library.gni")

LIB_DEPS = []
LIB_DEPS += [
  "//a",
  "//b",
]
if (is_fuchsia) {
  LIB_DEPS += [ "//fuchsia_only" ]
} else {
  LIB_DEPS += [ "//host_only" ]
}
not_needed([ "LIB_DEPS" ])

rustc_library("rust") {
  crate_name = "diagnostics_log"
  deps = LIB_DEPS
}
rustc_library("no_startup_handle") {
  features = [ "no_startup_handle" ]
  deps = LIB_DEPS
}
rustc_test("lib_test") {
  deps = []
  deps += LIB_DEPS
  if (is_fuchsia) {
    deps += [ "//test_only" ]
  }
}
'''


def test_bazel2gn_variables_and_conditions_per_context():
    r = gn_eval.evaluate(BAZEL2GN, FUCHSIA, "x/BUILD.gn")
    assert r.targets["rust"].scope["deps"] == ["//a", "//b", "//fuchsia_only"]
    assert r.targets["no_startup_handle"].scope["features"] == ["no_startup_handle"]
    assert r.targets["rust"].kind == "rustc_library"
    assert r.targets["lib_test"].scope["deps"][-1] == "//test_only"
    assert r.imports == ["//build/rust/rustc_library.gni"]
    h = gn_eval.evaluate(BAZEL2GN, HOST, "x/BUILD.gn")
    assert h.targets["rust"].scope["deps"] == ["//a", "//b", "//host_only"]
    outcomes = [(c.line, c.outcome, c.target) for c in r.conditionals]
    assert outcomes == [(8, "taken", None), (26, "taken", "lib_test")]
    assert [c.outcome for c in h.conditionals] == ["else", "else"]


def test_unknown_condition_follows_both_branches_and_is_recorded():
    text = '''\
d = [ "//x" ]
if (current_cpu == "arm64") {
  d += [ "//arm" ]
  only_then = "t"
} else {
  d += [ "//x", "//other" ]
}
group("g") {
  deps = d
  if (only_then == "t") {
    public_deps = [ "//p" ]
  }
}
'''
    r = gn_eval.evaluate(text, FUCHSIA, "f/BUILD.gn")
    assert r.targets["g"].scope["deps"] == ["//x", "//arm", "//other"]
    assert r.conditionals[0].outcome == "unknown"
    assert r.conditionals[0].text == 'current_cpu == "arm64"'
    # Set on one branch only: the variable is known to be "t" when it is defined at all.
    assert r.targets["g"].scope["public_deps"] == ["//p"]


def test_targets_under_conditions():
    text = '''\
if (is_host) {
  rustc_library("host_lib") {
  }
}
if (some_unknown) {
  rustc_library("maybe") {
  }
}
rustc_library("always") {
}
'''
    r = gn_eval.evaluate(text, FUCHSIA, "f/BUILD.gn")
    assert "host_lib" not in r.targets
    assert r.targets["maybe"].conditional is True
    assert r.targets["always"].conditional is False


def test_operators_strings_and_interpolation():
    text = r'''
name = "foo"
x = [ "a", "b", "c" ]
x -= [ "b" ]
s = "//lib/$name:${name}_rust"
q = "say \"hi\" \$name"
n = 1 + 2
m = 5 - 2
cmp = n < m || n == 3
u = "$undefined_var"
t = (is_fuchsia && !is_host) || unknown_thing
f = unknown_thing && false
group("g") {
  deps = x + [ s ]
  data = [ q, n, cmp, u, t, f ]
}
'''
    r = gn_eval.evaluate(text, FUCHSIA, "f/BUILD.gn")
    s = r.targets["g"].scope
    assert s["deps"] == ["a", "c", "//lib/foo:foo_rust"]
    assert s["data"] == ['say "hi" $name', 3, True, UNKNOWN, True, False]


def test_build_argument_defaults_and_their_reporting():
    gni = '''\
declare_args() {
  detect_cycles = compilation_mode == "debug"
  use_feature = false
}
'''
    args = gn_eval.evaluate(gni, FUCHSIA, "a/args.gni").args
    assert args == {"detect_cycles": UNKNOWN, "use_feature": False}
    text = '''\
import("//a/args.gni")
d = []
if (use_feature) {
  d += [ "//feature" ]
}
if (detect_cycles) {
  d += [ "//cycles" ]
}
group("g") {
  deps = d
}
'''
    r = gn_eval.evaluate(text, FUCHSIA, "f/BUILD.gn", args)
    assert r.targets["g"].scope["deps"] == ["//cycles"]
    assert [(c.outcome, c.args) for c in r.conditionals] == [
        ("else", {"use_feature": False}), ("unknown", {"detect_cycles": None})]
    # Without defaults every build argument is unknown (the upper-bound walk).
    r = gn_eval.evaluate(text, FUCHSIA, "f/BUILD.gn", args, arg_defaults=False)
    assert r.targets["g"].scope["deps"] == ["//feature", "//cycles"]
    # A declare_args() in the file itself works the same way.
    local = gni + text.replace('import("//a/args.gni")\n', "")
    r = gn_eval.evaluate(local, FUCHSIA, "f/BUILD.gn")
    assert r.targets["g"].scope["deps"] == ["//cycles"]
    assert r.args == args


def test_imports_lists_conditional_imports_but_not_targets():
    text = '''\
import("//a.gni")
if (is_host) {
  import("b.gni")
}
group("g") {
  import("//not/listed.gni")
}
'''
    assert gn_eval.imports(text, "f/BUILD.gn") == ["//a.gni", "b.gni"]


def test_templates_and_forwarding_are_not_run():
    text = '''\
template("my_rule") {
  group(target_name) {
    deps = invoker.deps
  }
}
my_rule("x") {
  deps = [ "//d" ]
  forward_variables_from(invoker, "*")
}
assert(true)
'''
    r = gn_eval.evaluate(text, FUCHSIA, "f/BUILD.gn")
    assert r.templates == ["my_rule"]
    assert r.targets["x"].kind == "my_rule"
    assert r.targets["x"].scope["deps"] == ["//d"]


def test_scope_access_and_list_index_are_unknown():
    text = '''\
s = { a = 1 }
group("g") {
  deps = [ s.a, x[0] ]
  foo.bar = 1
}
'''
    r = gn_eval.evaluate(text, FUCHSIA, "f/BUILD.gn")
    assert r.targets["g"].scope["deps"] == [UNKNOWN, UNKNOWN]


@pytest.mark.parametrize("text,msg", [
    ("group(\"g\") {\n  deps = [ \"a\" \n", "expected"),
    ("x = \n", "unexpected"),
    ("x = 1\n`\n", "cannot tokenize"),
    ("1 = 2\n", "unexpected"),
])
def test_parse_errors_name_file_and_line(text, msg):
    with pytest.raises(gn_eval.GnError, match=rf"^bad/BUILD.gn:\d+: .*{msg}"):
        gn_eval.evaluate(text, FUCHSIA, "bad/BUILD.gn")


def test_comments_and_else_if():
    text = '''\
# a comment with "//not/a/dep"
if (is_host) {
  d = [ "//h" ]
} else if (is_fuchsia) {  # trailing comment
  d = [ "//f" ]
} else {
  d = [ "//other" ]
}
'''
    r = gn_eval.evaluate(text, FUCHSIA, "f/BUILD.gn")
    assert [c.outcome for c in r.conditionals] == ["else", "taken"]
