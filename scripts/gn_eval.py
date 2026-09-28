# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""A small evaluator for the subset of GN that BUILD.gn files use (milestone M6).

It exists so scripts/closure.py can read a target's `deps` as GN would, including deps
held in file-level variables (bazel2gn output writes `deps = LIB_DEPS`), deps added
under `if (...)`, scope literals (`common = { deps = [...] }`) forwarded with
`forward_variables_from`, `foreach` loops, and templates defined in the same file
(expanded with `invoker` and `target_name`, as GN does). It does not load imports: a
call of an imported template is recorded as a target of that kind. A value it cannot
know (an imported variable, a function result) is UNKNOWN; a construct it cannot follow
(forwarding from an unknown scope, a foreach over an unknown list, assigning into a list
element) is recorded in FileResult.gaps, so a caller never loses deps silently.

Conditions are evaluated against a caller-supplied environment (for example
is_fuchsia = true, current_os = "fuchsia"). A condition that evaluates to true or false
takes one branch; one that evaluates to UNKNOWN runs both branches and merges them (a
list gets the union of both), so the result over-approximates. Build arguments
(declare_args(), in the file or passed in from its imports) have their declared defaults,
or are UNKNOWN when the caller asks for an upper bound. Every `if` is recorded
with its outcome ("taken", "else", "unknown") so the caller can report which
conditionals were decided and which were ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class GnError(Exception):
    """The file is not GN this evaluator can parse; the message names file:line."""


class _Unknown:
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self) -> str:
        return "UNKNOWN"


UNKNOWN = _Unknown()

# --- tokens -------------------------------------------------------------------------

_TOKEN = re.compile(r"""
    (?P<ws>[ \t\r\n]+)
  | (?P<comment>\#[^\n]*)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<number>-?\d+)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>==|!=|<=|>=|&&|\|\||\+=|-=|[=<>!+\-(){}\[\],.])
""", re.VERBOSE)


@dataclass
class Tok:
    kind: str
    value: str
    line: int
    pos: int


def tokenize(text: str, where: str) -> list[Tok]:
    toks: list[Tok] = []
    pos, line = 0, 1
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise GnError(f"{where}:{line}: cannot tokenize {text[pos:pos + 20]!r}")
        kind = m.lastgroup
        if kind not in ("ws", "comment"):
            toks.append(Tok(kind, m.group(0), line, pos))
        line += m.group(0).count("\n")
        pos = m.end()
    toks.append(Tok("eof", "", line, pos))
    return toks


# --- syntax tree ----------------------------------------------------------------------


@dataclass
class Node:
    line: int


@dataclass
class Lit(Node):
    value: object


@dataclass
class Str(Node):
    raw: str  # the literal without quotes, escapes and $ untouched


@dataclass
class Ident(Node):
    name: str


@dataclass
class ListExpr(Node):
    items: list


@dataclass
class Access(Node):
    base: Node
    member: str | None = None  # a.b
    index: Node | None = None  # a[i]


@dataclass
class Unary(Node):
    op: str
    operand: Node


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass
class Call(Node):
    name: str
    args: list
    block: list | None


@dataclass
class BlockExpr(Node):
    body: list


@dataclass
class Assign(Node):
    target: Node
    op: str
    value: Node


@dataclass
class If(Node):
    cond: Node
    text: str
    then: list
    orelse: list | None  # a list of statements; `else if` is a one-If list


_PRECEDENCE = [("||",), ("&&",), ("==", "!="), ("<", "<=", ">", ">="), ("+", "-")]


class Parser:
    def __init__(self, text: str, where: str):
        self.text = text
        self.where = where
        self.toks = tokenize(text, where)
        self.i = 0

    def peek(self, off: int = 0) -> Tok:
        return self.toks[min(self.i + off, len(self.toks) - 1)]

    def next(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def fail(self, msg: str) -> GnError:
        return GnError(f"{self.where}:{self.peek().line}: {msg}")

    def expect(self, value: str) -> Tok:
        t = self.next()
        if t.value != value or t.kind == "string":
            self.i -= 1
            raise self.fail(f"expected {value!r}, got {t.value!r}")
        return t

    def at(self, value: str) -> bool:
        t = self.peek()
        return t.kind == "op" and t.value == value

    def parse_file(self) -> list:
        body = self.statements()
        if self.peek().kind != "eof":
            raise self.fail(f"unexpected {self.peek().value!r}")
        return body

    def statements(self) -> list:
        out = []
        while self.peek().kind != "eof" and not self.at("}"):
            out.append(self.statement())
        return out

    def block(self) -> list:
        self.expect("{")
        body = self.statements()
        self.expect("}")
        return body

    def statement(self) -> Node:
        t = self.peek()
        if t.kind == "ident" and t.value == "if":
            return self.if_stmt()
        if t.kind == "ident" and self.peek(1).value == "(" and self.peek(1).kind == "op":
            call = self.call()
            return call
        target = self.postfix(Ident(t.line, self.next().value) if t.kind == "ident" else None)
        if target is None:
            raise self.fail(f"unexpected {t.value!r}")
        op = self.next()
        if op.value not in ("=", "+=", "-="):
            self.i -= 1
            raise self.fail(f"expected an assignment, got {op.value!r}")
        return Assign(t.line, target, op.value, self.expr())

    def if_stmt(self) -> If:
        line = self.next().line
        self.expect("(")
        start = self.peek().pos
        cond = self.expr()
        end = self.peek().pos
        self.expect(")")
        then = self.block()
        orelse = None
        if self.peek().kind == "ident" and self.peek().value == "else":
            self.next()
            if self.peek().kind == "ident" and self.peek().value == "if":
                orelse = [self.if_stmt()]
            else:
                orelse = self.block()
        return If(line, cond, " ".join(self.text[start:end].split()), then, orelse)

    def call(self) -> Call:
        name = self.next()
        self.expect("(")
        args = []
        while not self.at(")"):
            args.append(self.expr())
            if not self.at(")"):
                self.expect(",")
        self.expect(")")
        block = self.block() if self.at("{") else None
        return Call(name.line, name.value, args, block)

    def expr(self, level: int = 0) -> Node:
        if level == len(_PRECEDENCE):
            return self.unary()
        left = self.expr(level + 1)
        while self.peek().kind == "op" and self.peek().value in _PRECEDENCE[level]:
            op = self.next()
            left = Binary(op.line, op.value, left, self.expr(level + 1))
        return left

    def unary(self) -> Node:
        if self.at("!"):
            t = self.next()
            return Unary(t.line, "!", self.unary())
        return self.postfix(self.primary())

    def postfix(self, node: Node | None) -> Node | None:
        while node is not None:
            if self.at("."):
                self.next()
                member = self.next()
                if member.kind != "ident":
                    raise self.fail("expected a scope member")
                node = Access(member.line, node, member=member.value)
            elif self.at("["):
                self.next()
                idx = self.expr()
                self.expect("]")
                node = Access(node.line, node, index=idx)
            else:
                break
        return node

    def primary(self) -> Node:
        t = self.peek()
        if t.kind == "string":
            self.next()
            return Str(t.line, t.value[1:-1])
        if t.kind == "number":
            self.next()
            return Lit(t.line, int(t.value))
        if t.kind == "ident":
            if t.value in ("true", "false"):
                self.next()
                return Lit(t.line, t.value == "true")
            if self.peek(1).value == "(" and self.peek(1).kind == "op":
                return self.call()
            self.next()
            return Ident(t.line, t.value)
        if self.at("("):
            self.next()
            e = self.expr()
            self.expect(")")
            return e
        if self.at("["):
            self.next()
            items = []
            while not self.at("]"):
                items.append(self.expr())
                if not self.at("]"):
                    self.expect(",")
            self.expect("]")
            return ListExpr(t.line, items)
        if self.at("{"):
            return BlockExpr(t.line, self.block())
        raise self.fail(f"unexpected {t.value!r}")


# --- evaluation -------------------------------------------------------------------------


@dataclass
class Target:
    kind: str
    name: str
    line: int
    scope: dict  # the variables its block set (deps, public_deps, crate_name, ...)
    conditional: bool = False  # defined under an `if` whose condition was UNKNOWN
    # Variables forwarded from a scope the evaluator does not know (e.g. `invoker` of an
    # imported template): any of them, deps included, may be missing.
    unknown_forward: bool = False


@dataclass
class Conditional:
    line: int
    text: str
    outcome: str  # "taken" (then branch), "else", "unknown" (both branches)
    target: str | None  # the enclosing target's name, or None at file level
    args: dict = field(default_factory=dict)  # build arguments it read -> their defaults


@dataclass
class FileResult:
    targets: dict[str, Target] = field(default_factory=dict)
    conditionals: list[Conditional] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)  # template() definitions in the file
    args: dict = field(default_factory=dict)  # declare_args() names -> default values
    # Constructs the evaluator could not follow, so a value may be missing or UNKNOWN:
    # (line, enclosing target or None, what). Callers report these; nothing is dropped
    # silently.
    gaps: list[tuple[int, str | None, str]] = field(default_factory=list)
    template_calls: dict[str, str] = field(default_factory=dict)  # target -> same-file template


class Scope:
    def __init__(self, parent: Scope | None = None, env: dict | None = None):
        self.parent = parent
        self.vars: dict[str, object] = dict(env or {})

    def get(self, name: str):
        s = self
        while s is not None:
            if name in s.vars:
                return s.vars[name]
            s = s.parent
        return UNKNOWN

    def has(self, name: str) -> bool:
        s = self
        while s is not None:
            if name in s.vars:
                return True
            s = s.parent
        return False


_INTERP = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\}"
                     r"|(0x[0-9A-Fa-f]{2})|([A-Za-z_][A-Za-z0-9_]*))")
_UNKNOWN_FORWARD = "__unknown_forward__"


def _merge(a, b):
    """The value a variable may have after one of two branches set it to a or b."""
    if a == b:
        return a
    if isinstance(a, list) and isinstance(b, list):
        return a + [x for x in b if x not in a]
    if isinstance(a, dict) and isinstance(b, dict):
        return {k: (_merge(a[k], b[k]) if k in a and k in b else a.get(k, b.get(k)))
                for k in list(a) + [k for k in b if k not in a]}
    return UNKNOWN


class Evaluator:
    def __init__(self, env: dict, where: str, args: dict | None = None, arg_defaults: bool = True):
        """`args`: build arguments declared in imported files -> their defaults.

        With arg_defaults, a build argument has its declared default (what a build that
        sets no args.gn gets), and conditions that read one record it; otherwise every
        build argument is UNKNOWN.
        """
        self.env = dict(env)
        self.arg_defaults = arg_defaults
        self.arg_names = set(args or {})
        if args:
            self.env.update(args if arg_defaults else {k: UNKNOWN for k in args})
        self.where = where
        self.result = FileResult()
        self._target: str | None = None
        self._unknown_depth = 0
        self._templates: dict[str, list] = {}
        self._file_scope: Scope | None = None
        self._depth = 0

    def run(self, text: str) -> FileResult:
        body = Parser(text, self.where).parse_file()
        self._file_scope = Scope(env=self.env)
        self.exec_block(body, self._file_scope)
        return self.result

    def gap(self, line: int, what: str) -> None:
        self.result.gaps.append((line, self._target, what))

    # statements
    def exec_block(self, body: list, scope: Scope) -> None:
        for stmt in body:
            self.exec(stmt, scope)

    def exec(self, stmt: Node, scope: Scope) -> None:
        if isinstance(stmt, Assign):
            self.assign(stmt, scope)
        elif isinstance(stmt, If):
            self.exec_if(stmt, scope)
        elif isinstance(stmt, Call):
            self.exec_call(stmt, scope)
        else:
            raise GnError(f"{self.where}:{stmt.line}: not a statement")

    def assign(self, stmt: Assign, scope: Scope) -> None:
        if not isinstance(stmt.target, Ident):
            t = stmt.target
            if (isinstance(t, Access) and t.member and isinstance(t.base, Ident)
                    and isinstance(scope.get(t.base.name), dict) and stmt.op == "="):
                scope.vars[t.base.name] = {**scope.get(t.base.name), t.member: self.eval(stmt.value, scope)}
            else:
                self.gap(stmt.line, "assignment to a scope member or list element not evaluated")
            return
        name = stmt.target.name
        value = self.eval(stmt.value, scope)
        if stmt.op == "=":
            scope.vars[name] = value
            return
        old = scope.get(name) if scope.has(name) else []
        if stmt.op == "+=":
            if isinstance(old, list) and isinstance(value, list):
                scope.vars[name] = old + value
            elif isinstance(old, str) and isinstance(value, str):
                scope.vars[name] = old + value
            elif isinstance(old, int) and isinstance(value, int) and not isinstance(old, bool):
                scope.vars[name] = old + value
            elif isinstance(old, list) and value is UNKNOWN:
                scope.vars[name] = old + [UNKNOWN]
            else:
                scope.vars[name] = UNKNOWN
        else:  # -=
            if isinstance(old, list) and isinstance(value, list):
                scope.vars[name] = [x for x in old if x not in value]
            elif isinstance(old, list):
                scope.vars[name] = old  # removing unknown items: keep the upper bound
            else:
                scope.vars[name] = UNKNOWN

    def _args_read(self, node: Node, scope: Scope) -> dict:
        names = {n.name for n in _walk(node) if isinstance(n, Ident)} & self.arg_names
        return {n: scope.get(n) if scope.get(n) is not UNKNOWN else None for n in sorted(names)}

    def exec_if(self, stmt: If, scope: Scope) -> None:
        cond = self.eval(stmt.cond, scope)
        args = self._args_read(stmt.cond, scope)
        if isinstance(cond, bool):
            self.result.conditionals.append(
                Conditional(stmt.line, stmt.text, "taken" if cond else "else", self._target, args))
            if cond:
                self.exec_block(stmt.then, scope)
            elif stmt.orelse is not None:
                self.exec_block(stmt.orelse, scope)
            return
        self.result.conditionals.append(Conditional(stmt.line, stmt.text, "unknown", self._target, args))
        before = dict(scope.vars)
        self._unknown_depth += 1
        self.exec_block(stmt.then, scope)
        after_then = scope.vars
        scope.vars = dict(before)
        if stmt.orelse is not None:
            self.exec_block(stmt.orelse, scope)
        after_else = scope.vars
        self._unknown_depth -= 1
        merged = {}
        for k in set(after_then) | set(after_else):
            if k in after_then and k in after_else:
                merged[k] = _merge(after_then[k], after_else[k])
            else:
                # Set on one branch only: before-value (if any) on the other.
                one = after_then.get(k, after_else.get(k))
                merged[k] = _merge(before[k], one) if k in before else one
        scope.vars = merged

    def exec_call(self, call: Call, scope: Scope) -> None:
        name = call.name
        if name == "import":
            if call.args and isinstance(call.args[0], Str):
                self.result.imports.append(call.args[0].raw)
            return
        if name == "template":
            if call.args and isinstance(call.args[0], Str) and call.block is not None:
                self.result.templates.append(call.args[0].raw)
                self._templates[call.args[0].raw] = call.block
            else:
                self.gap(call.line, "template() without a literal name and a body")
            return
        if name == "set_defaults":
            return  # defaults for imported templates' configs: not deps
        if name == "declare_args":
            # Build arguments: their declared defaults, or UNKNOWN (see __init__).
            inner = Scope(scope)
            self.exec_block(call.block or [], inner)
            for k, v in inner.vars.items():
                self.result.args[k] = v
                self.arg_names.add(k)
                scope.vars[k] = v if self.arg_defaults else UNKNOWN
            return
        if name == "forward_variables_from":
            self.forward(call, scope)
            return
        if name == "foreach":
            self.foreach(call, scope)
            return
        if call.block is None:
            return  # assert(), not_needed(), print() ...
        tname = self.eval(call.args[0], scope) if call.args else None
        if not isinstance(tname, str):
            self.gap(call.line, f"{name}() with a target name that is not known")
            return
        inner = Scope(scope)
        inner.vars["target_name"] = tname
        outer_target = self._target
        self._target = tname
        self.exec_block(call.block, inner)
        if name in self._templates:
            self.expand(name, tname, call, inner)
            self._target = outer_target
            return
        self._target = outer_target
        inner.vars.pop("target_name", None)
        unknown_forward = bool(inner.vars.pop(_UNKNOWN_FORWARD, False))
        self.register(Target(name, tname, call.line, inner.vars,
                             conditional=self._unknown_depth > 0, unknown_forward=unknown_forward))

    def register(self, target: Target) -> None:
        old = self.result.targets.get(target.name)
        if old is not None and self._unknown_depth > 0 and old.kind == target.kind:
            # Defined on both branches of an unknown condition: either may apply.
            target.scope = _merge(old.scope, target.scope)
            target.unknown_forward |= old.unknown_forward
        self.result.targets[target.name] = target

    def expand(self, template: str, tname: str, call: Call, invocation: Scope) -> None:
        """Run a same-file template's body with `invoker` and `target_name` (as GN does)."""
        self._depth += 1
        if self._depth > 20:
            raise GnError(f"{self.where}:{call.line}: template {template} recurses too deeply")
        invoker = {k: v for k, v in invocation.vars.items() if k != "target_name"}
        if invoker.pop(_UNKNOWN_FORWARD, False):
            self.gap(call.line, f"{template}(\"{tname}\") forwards from an unknown scope")
        body_scope = Scope(self._file_scope, {"target_name": tname, "invoker": invoker})
        self.exec_block(self._templates[template], body_scope)
        self._depth -= 1
        self.result.template_calls[tname] = template
        if tname not in self.result.targets:
            # The template made no target of that name (it may wrap an imported
            # template under another name): keep the call as an opaque target.
            self.register(Target(template, tname, call.line, invoker,
                                 conditional=self._unknown_depth > 0))

    def forward(self, call: Call, scope: Scope) -> None:
        """forward_variables_from(scope, "*" | [names] [, exclude])."""
        if len(call.args) < 2:
            self.gap(call.line, "forward_variables_from() without two arguments")
            return
        src = self.eval(call.args[0], scope)
        which = self.eval(call.args[1], scope)
        exclude = self.eval(call.args[2], scope) if len(call.args) > 2 else []
        exclude = exclude if isinstance(exclude, list) else []
        if isinstance(src, dict) and (which == "*" or isinstance(which, list)):
            names = list(src) if which == "*" else [n for n in which if isinstance(n, str)]
            for n in names:
                if n in src and n not in exclude:
                    scope.vars[n] = src[n]
            return
        if isinstance(which, list) and all(isinstance(n, str) for n in which):
            for n in which:
                if n not in exclude:
                    scope.vars[n] = UNKNOWN
            self.gap(call.line, f"forward_variables_from() from an unknown scope: {', '.join(which)} UNKNOWN")
            return
        scope.vars[_UNKNOWN_FORWARD] = True
        self.gap(call.line, "forward_variables_from(<unknown scope>, \"*\"): any variable may be missing")

    def foreach(self, call: Call, scope: Scope) -> None:
        if len(call.args) != 2 or not isinstance(call.args[0], Ident) or call.block is None:
            self.gap(call.line, "foreach() not in the form foreach(x, list) { ... }")
            return
        var = call.args[0].name
        items = self.eval(call.args[1], scope)
        had, old = var in scope.vars, scope.vars.get(var)
        if not isinstance(items, list):
            self.gap(call.line, f"foreach({var}, ...) over an unknown list: body run once with {var} UNKNOWN")
            items = [UNKNOWN]
        for item in items:
            scope.vars[var] = item
            self.exec_block(call.block, scope)
        if had:
            scope.vars[var] = old
        else:
            scope.vars.pop(var, None)

    # expressions
    def eval(self, node: Node, scope: Scope):
        if isinstance(node, Lit):
            return node.value
        if isinstance(node, Str):
            return self.string(node.raw, scope)
        if isinstance(node, Ident):
            return scope.get(node.name)
        if isinstance(node, ListExpr):
            return [self.eval(x, scope) for x in node.items]
        if isinstance(node, Unary):
            v = self.eval(node.operand, scope)
            return (not v) if isinstance(v, bool) else UNKNOWN
        if isinstance(node, Binary):
            return self.binary(node, scope)
        if isinstance(node, Call):
            if node.name == "defined" and len(node.args) == 1:
                arg = node.args[0]
                if isinstance(arg, Ident):
                    return True if scope.has(arg.name) else UNKNOWN
                if isinstance(arg, Access) and arg.member:
                    base = self.eval(arg.base, scope)
                    return (arg.member in base) if isinstance(base, dict) else UNKNOWN
            return UNKNOWN
        if isinstance(node, BlockExpr):
            inner = Scope(scope)
            self.exec_block(node.body, inner)
            return dict(inner.vars)
        if isinstance(node, Access):
            base = self.eval(node.base, scope)
            if node.member is not None:
                return base.get(node.member, UNKNOWN) if isinstance(base, dict) else UNKNOWN
            idx = self.eval(node.index, scope)
            if isinstance(base, list) and isinstance(idx, int) and not isinstance(idx, bool) \
                    and 0 <= idx < len(base):
                return base[idx]
            return UNKNOWN
        return UNKNOWN

    def string(self, raw: str, scope: Scope):
        unknown = False

        def sub(m):
            nonlocal unknown
            if m.group(2):
                return chr(int(m.group(2)[2:], 16))
            name = m.group(1) or m.group(3)
            base, _, member = name.partition(".")
            v = scope.get(base)
            if member:
                v = v.get(member, UNKNOWN) if isinstance(v, dict) else UNKNOWN
            if isinstance(v, str):
                return v
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, int):
                return str(v)
            unknown = True
            return ""

        # GN escapes: \" \$ \\ ; other backslashes are literal.
        parts = re.split(r'(\\["$\\])', raw)
        out = []
        for i, p in enumerate(parts):
            if i % 2:
                out.append(p[1])
            else:
                text = _INTERP.sub(sub, p)
                if "$" in text:
                    unknown = True  # a $ form this evaluator does not read
                out.append(text)
        return UNKNOWN if unknown else "".join(out)

    def binary(self, node: Binary, scope: Scope):
        op = node.op
        a = self.eval(node.left, scope)
        if op in ("&&", "||"):
            if a is False and op == "&&":
                return False
            if a is True and op == "||":
                return True
            b = self.eval(node.right, scope)
            if op == "&&":
                if b is False:
                    return False
                return True if a is True and b is True else UNKNOWN
            if b is True:
                return True
            return False if a is False and b is False else UNKNOWN
        b = self.eval(node.right, scope)
        if a is UNKNOWN or b is UNKNOWN:
            return UNKNOWN
        if isinstance(a, list) and UNKNOWN in a or isinstance(b, list) and UNKNOWN in b:
            return UNKNOWN
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        if op in ("<", "<=", ">", ">="):
            if isinstance(a, int) and isinstance(b, int):
                return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
            return UNKNOWN
        if op == "+":
            if isinstance(a, list) and isinstance(b, list):
                return a + b
            if isinstance(a, str) and isinstance(b, str):
                return a + b
            if isinstance(a, int) and isinstance(b, int):
                return a + b
            return UNKNOWN
        if op == "-":
            if isinstance(a, list) and isinstance(b, list):
                return [x for x in a if x not in b]
            if isinstance(a, int) and isinstance(b, int):
                return a - b
        return UNKNOWN


def _walk(node):
    yield node
    for v in vars(node).values():
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, Node):
                yield from _walk(x)


def evaluate(text: str, env: dict, where: str, args: dict | None = None,
             arg_defaults: bool = True) -> FileResult:
    """Evaluate a BUILD.gn file's text in `env` (see the module docstring and Evaluator)."""
    return Evaluator(env, where, args, arg_defaults).run(text)


def imports(text: str, where: str) -> list[str]:
    """The files a GN file imports at top level or under a condition (not in targets)."""
    out = []

    def visit(body):
        for st in body:
            if isinstance(st, Call) and st.name == "import" and st.args and isinstance(st.args[0], Str):
                out.append(st.args[0].raw)
            elif isinstance(st, If):
                visit(st.then)
                visit(st.orelse or [])

    visit(Parser(text, where).parse_file())
    return out
