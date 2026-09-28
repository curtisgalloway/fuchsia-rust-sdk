# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""A small evaluator for the subset of GN that BUILD.gn files use (milestone M6).

It exists so scripts/closure.py can read a target's `deps` as GN would, including deps
held in file-level variables (bazel2gn output writes `deps = LIB_DEPS`) and deps added
under `if (...)`. It does not load imports or run templates: a call with a block is
recorded as a target of that kind, and anything it cannot know (an imported variable, a
build argument, a function result) is UNKNOWN.

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
    templates: list[str] = field(default_factory=list)  # template() definitions (not run)
    args: dict = field(default_factory=dict)  # declare_args() names -> default values


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


_INTERP = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*)|(0x[0-9A-Fa-f]{2}))")


def _merge(a, b):
    """The value a variable may have after one of two branches set it to a or b."""
    if a == b:
        return a
    if isinstance(a, list) and isinstance(b, list):
        return a + [x for x in b if x not in a]
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

    def run(self, text: str) -> FileResult:
        body = Parser(text, self.where).parse_file()
        self.exec_block(body, Scope(env=self.env))
        return self.result

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
            return  # a.b = ... or a[i] = ...: nothing the walker reads
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
            if call.args and isinstance(call.args[0], Str):
                self.result.templates.append(call.args[0].raw)
            return
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
            return
        if call.block is None:
            return  # assert(), not_needed(), print(), set_defaults ...
        tname = self.eval(call.args[0], scope) if call.args else None
        inner = Scope(scope)
        outer_target = self._target
        self._target = tname if isinstance(tname, str) else f"<{name}>"
        self.exec_block(call.block, inner)
        self._target = outer_target
        if isinstance(tname, str):
            self.result.targets[tname] = Target(name, tname, call.line, inner.vars,
                                                conditional=self._unknown_depth > 0)

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
            if node.name == "defined" and len(node.args) == 1 and isinstance(node.args[0], Ident):
                return True if scope.has(node.args[0].name) else UNKNOWN
            return UNKNOWN
        if isinstance(node, (Access, BlockExpr)):
            return UNKNOWN
        return UNKNOWN

    def string(self, raw: str, scope: Scope):
        unknown = False

        def sub(m):
            nonlocal unknown
            if m.group(3):
                return chr(int(m.group(3)[2:], 16))
            v = scope.get(m.group(1) or m.group(2))
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
                out.append(_INTERP.sub(sub, p))
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
