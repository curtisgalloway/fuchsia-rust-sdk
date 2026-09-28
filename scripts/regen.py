#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Regenerate the overlay's copies of upstream code (design R6, D6, D9; milestone M5).

Usage:
  regen.py vendor     rewrite vendor/fuchsia/ and third_party/crates/ from upstream
  regen.py --check    regenerate into a scratch directory and report drift (exit 1)

Only the vendor stage exists so far; the full pipeline (R1 -> R4 -> R5 -> R6, the
closure report, builds) is milestone M14.

Inputs, all committed:
  overlay.lock.json        fuchsia_revision (what to copy) and cargo_lock_sha256
  vendor/crates.txt        one "<upstream path> <upstream|overlay>" per line: which
                           fuchsia.git directories to copy, and where each one's
                           BUILD.bazel comes from (upstream's, rewritten, or ours)
  vendor/crates_io.txt     @rust_crates//vendor aliases to generate besides those the
                           vendored BUILD files use (the pilots' direct crates.io deps)
  overlays/<path>/BUILD.bazel     hand-written BUILD file for an "overlay" crate
  patches/fuchsia/<path>/*.patch  applied in name order after the BUILD files

Outputs, generated and committed (D6); never edit them by hand:
  vendor/fuchsia/<path>/   each listed directory, byte-for-byte from fuchsia.git at the
                           revision, except BUILD.bazel and what patches change (D9).
                           Subdirectories that are packages of their own (a BUILD.bazel
                           or BUILD.gn) are left out; list them separately.
  vendor/fuchsia/LICENSE, PATENTS   fuchsia.git's root files, which cover every file
                           under vendor/fuchsia/ as they cover the upstream tree (C4)
  vendor/fuchsia/BUILD.bazel        the license target upstream BUILD files name as
                           //:license
  third_party/crates/      the crates the vendored BUILD files and vendor/crates_io.txt
                           name, and everything they depend on: upstream's
                           crate_universe-generated BUILD files (fuchsia.git
                           third_party/rust_crates/<vendor|forks|ask2patch>/<dir>/BUILD.bazel)
                           with labels rewritten, and crates.json, which lists each
                           crates.io crate's static.crates.io URL and the SHA-256 the
                           release's Cargo.lock gives it. Patched crates (forks/,
                           ask2patch/; sources only in fuchsia.git) are copied byte for
                           byte to src/<kind>/<dir>/ (M6b), and crates.json lists their
                           files. //toolchain:crates.bzl turns this into the @rust_crates
                           repository; the build downloads each crates.io crate by that
                           checksum and resolves nothing.

Rewriting upstream BUILD.bazel files (parsed with Python's ast; comments untouched):
  load("//build/bazel/rules/rust:defs.bzl", ...)  -> load("//rules:rustc.bzl", ...)
                                           (rustc_library/_binary/_proc_macro only)
  load("@rules_rust//rust:defs.bzl", "rust_proc_macro")
      -> load("//rules:rustc.bzl", rust_proc_macro = "rustc_proc_macro")
                                           (rust_library/_binary/_proc_macro only)
  load of @rules_license rules             -> unchanged; any other load fails
  //build/config/rust/lints:<x>            -> //rules/lints:<x>
  //:license, //:__subpackages__, //:__pkg__  -> //vendor/fuchsia:<same>
  //third_party/rust_crates/vendor:<x>     -> @rust_crates//vendor:<x>
  //third_party/rust_crates/<forks|ask2patch>/<dir>[:<t>] -> @rust_crates//<kind>/<dir>[:<t>]
  //<path>[:<t>], <path> listed            -> //vendor/fuchsia/<path>[:<t>]
  //<path>:__pkg__ / :__subpackages__      -> //vendor/fuchsia/<path>:<same> (visibility)
Every call of one of those Rust rules gets `vendored = True`: the overlay builds
upstream code at HEAD, which upstream builds at PLATFORM, so its lints are upstream's
concern (M4 review). The rewriter fails closed, naming file:line: any other //-label
(for example a crate directory under third_party/rust_crates/vendor named without its
alias), a label that is not a plain double-quoted string, a rust_*/rustc_* call it
cannot mark, or a Rust rule that already sets `vendored`.

Git access (C1): one depth-1, blobless fetch of the revision into a scratch directory,
then one fetch of exactly the blobs needed, by object ID, with git isolated from user
and system configuration (resolve_pins.isolated_git). Nothing is fetched at build time.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

import resolve_pins
from resolve_pins import FetchError, isolated_git

ROOT = Path(__file__).resolve().parent.parent
FUCHSIA_GIT = resolve_pins.FUCHSIA_GIT

VENDOR_LIST = "vendor/crates.txt"
CRATES_IO_LIST = "vendor/crates_io.txt"
VENDOR_OUT = "vendor/fuchsia"
CRATES_OUT = "third_party/crates"
OVERLAYS = "overlays"
PATCHES = "patches/fuchsia"
# Every generated tree, relative to the repository root. --check compares these.
OUTPUTS = (VENDOR_OUT, CRATES_OUT)

# fuchsia.git root files copied to vendor/fuchsia/ (their license covers every file).
ROOT_FILES = ("LICENSE", "PATENTS")

RUST_CRATES = "third_party/rust_crates"
RUST_CRATES_VENDOR = f"{RUST_CRATES}/vendor"
CARGO_LOCK = f"{RUST_CRATES}/Cargo.lock"
CRATES_IO_SOURCE = "registry+https://github.com/rust-lang/crates.io-index"
CRATE_URL = "https://static.crates.io/crates/{name}/{name}-{version}.crate"
CRATES_REPO = "rust_crates"
# Locally patched crates (milestone M6b): third_party/rust_crates/<kind>/<dir> upstream,
# whose sources exist only in fuchsia.git. regen.py commits them under
# third_party/crates/src/<kind>/<dir>/ (D6); crates.bzl lays them out in @rust_crates.
PATCHED_KINDS = ("forks", "ask2patch")
CRATES_SRC = "src"
# Files that would make a package (or a repository boundary) inside a patched crate.
_PACKAGE_MARKERS = ("BUILD", "BUILD.bazel", "WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel", "REPO.bazel")

RUSTC_MACROS = ("rustc_library", "rustc_binary", "rustc_proc_macro")
PACKAGE_FILES = ("BUILD.bazel", "BUILD.gn")

# Labels that are Bazel built-ins, not packages.
_BUILTIN_PREFIXES = ("//visibility:", "//conditions:")

GENERATED_BY = "Generated by scripts/regen.py"


class RegenError(Exception):
    """The run cannot produce a correct tree; the message names the input at fault."""


# --- upstream access -----------------------------------------------------------


class Source(Protocol):
    """Read-only view of fuchsia.git at one revision. Tests substitute a directory."""

    revision: str

    def files(self, path: str) -> dict[str, int]:
        """Every file under `path` (repo-relative, recursive) -> its mode (0o644/0o755).

        Raises RegenError if `path` has no files, or holds a symlink or submodule.
        """
        ...

    def read(self, paths: list[str]) -> dict[str, bytes]:
        """The contents of each repo-relative file. Raises RegenError if one is missing."""
        ...

    def existing(self, paths: list[str]) -> set[str]:
        """The subset of `paths` that are files at the revision (closure.py, M6)."""
        ...


class DirSource:
    """A plain directory laid out like fuchsia.git (tests, or a local checkout)."""

    def __init__(self, root: Path, revision: str):
        self.root = root
        self.revision = revision

    def files(self, path: str) -> dict[str, int]:
        base = self.root / path
        out: dict[str, int] = {}
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_symlink():
                    raise RegenError(f"{p.relative_to(self.root).as_posix()}: symlinks are not supported")
                if p.is_file():
                    mode = 0o755 if p.stat().st_mode & stat.S_IXUSR else 0o644
                    out[p.relative_to(self.root).as_posix()] = mode
        if not out:
            raise RegenError(f"{path}: no such directory at {self.revision}")
        return out

    def read(self, paths: list[str]) -> dict[str, bytes]:
        out = {}
        for p in paths:
            f = self.root / p
            if not f.is_file():
                raise RegenError(f"{p}: no such file at {self.revision}")
            out[p] = f.read_bytes()
        return out

    def existing(self, paths: list[str]) -> set[str]:
        return {p for p in paths if (self.root / p).is_file() and not (self.root / p).is_symlink()}


class GitSource:
    """fuchsia.git over anonymous HTTPS (C1): depth-1 blobless fetch, blobs by ID."""

    def __init__(self, repo: str, revision: str, workdir: Path):
        self.repo = repo
        self.revision = revision
        self.gitdir = workdir / "fuchsia.git"
        self.home = workdir / "home"
        self._fetched_blobs: set[str] = set()
        self.home.mkdir(parents=True, exist_ok=True)
        self.gitdir.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q", "--bare")
        self._git("fetch", "-q", "--no-tags", "--depth", "1", "--filter=blob:none", repo, revision)
        fetched = self._git("rev-parse", "FETCH_HEAD").decode().strip()
        if fetched != revision:
            raise RegenError(f"git fetch {repo} {revision}: got {fetched}")
        self._entries: dict[str, tuple[int, str]] = {}

    def _git(self, *args: str, stdin: bytes | None = None) -> bytes:
        try:
            return isolated_git(self.gitdir, self.home, *args, stdin=stdin)
        except FetchError as e:
            raise RegenError(str(e)) from None

    def files(self, path: str) -> dict[str, int]:
        raw = self._git("ls-tree", "-r", "-z", "--full-tree", self.revision, "--", path)
        out: dict[str, int] = {}
        for rec in raw.split(b"\0"):
            if not rec:
                continue
            meta, name = rec.split(b"\t", 1)
            mode, kind, oid = meta.decode().split()
            name = name.decode()
            if name != path and not name.startswith(path + "/"):
                continue
            if kind != "blob" or mode not in ("100644", "100755"):
                raise RegenError(f"{name}: unsupported git entry (mode {mode}, {kind})")
            out[name] = 0o755 if mode == "100755" else 0o644
            self._entries[name] = (out[name], oid)
        if not out:
            raise RegenError(f"{path}: no such directory at {self.revision}")
        return out

    def _oid(self, path: str) -> str:
        if path not in self._entries:
            raw = self._git("ls-tree", "-z", "--full-tree", self.revision, "--", path)
            recs = [r for r in raw.split(b"\0") if r]
            if len(recs) != 1:
                raise RegenError(f"{path}: no such file at {self.revision}")
            meta, _ = recs[0].split(b"\t", 1)
            mode, kind, oid = meta.decode().split()
            if kind != "blob":
                raise RegenError(f"{path}: not a file at {self.revision}")
            self._entries[path] = (0o755 if mode == "100755" else 0o644, oid)
        return self._entries[path][1]

    def existing(self, paths: list[str]) -> set[str]:
        want = [p for p in paths if p not in self._entries]
        for i in range(0, len(want), 500):
            raw = self._git("ls-tree", "-z", "--full-tree", self.revision, "--", *want[i:i + 500])
            for rec in raw.split(b"\0"):
                if not rec:
                    continue
                meta, name = rec.split(b"\t", 1)
                mode, kind, oid = meta.decode().split()
                if kind == "blob" and mode in ("100644", "100755"):
                    self._entries[name.decode()] = (0o755 if mode == "100755" else 0o644, oid)
        return {p for p in paths if p in self._entries}

    def read(self, paths: list[str]) -> dict[str, bytes]:
        oids = {p: self._oid(p) for p in paths}
        missing = sorted(set(oids.values()) - self._fetched_blobs)
        if missing:
            # One request for every blob not yet local, as git's own partial-clone
            # prefetch does; without it cat-file would fetch them one at a time.
            self._git("-c", "fetch.negotiationAlgorithm=noop", "fetch", "-q", "--no-tags",
                      "--no-write-fetch-head", "--filter=blob:none", self.repo, *missing)
            self._fetched_blobs.update(missing)
        out: dict[str, bytes] = {}
        batch = self._git("cat-file", "--batch", stdin="".join(f"{oids[p]}\n" for p in paths).encode())
        pos = 0
        for p in paths:
            nl = batch.index(b"\n", pos)
            header = batch[pos:nl].decode().split()
            if len(header) != 3 or header[1] != "blob":
                raise RegenError(f"{p}: cat-file returned {' '.join(header)}")
            size = int(header[2])
            out[p] = batch[nl + 1:nl + 1 + size]
            pos = nl + 1 + size + 1
        return out


# --- inputs ----------------------------------------------------------------------


@dataclass(frozen=True)
class Crate:
    path: str  # upstream path, e.g. sdk/rust/zx-types
    build: str  # "upstream" or "overlay"


def _check_path(path: str, where: str) -> str:
    p = PurePosixPath(path)
    if (not path or p.is_absolute() or any(part in ("", ".", "..") for part in path.split("/"))
            or path.endswith("/")):
        raise RegenError(f"{where}: {path!r} is not a normalized relative path")
    return path


def read_vendor_list(text: str, where: str = VENDOR_LIST) -> list[Crate]:
    """Parse vendor/crates.txt: "<path> <upstream|overlay>", '#' comments."""
    crates: list[Crate] = []
    seen: set[str] = set()
    for n, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 2 or fields[1] not in ("upstream", "overlay"):
            raise RegenError(f"{where}:{n}: expected '<upstream path> upstream|overlay', got {line!r}")
        path = _check_path(fields[0], f"{where}:{n}")
        if path in seen:
            raise RegenError(f"{where}:{n}: {path} is listed twice")
        seen.add(path)
        crates.append(Crate(path, fields[1]))
    return crates


_ALIAS_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*")


def read_crates_io_list(text: str, where: str = CRATES_IO_LIST) -> list[str]:
    """Parse vendor/crates_io.txt: one @rust_crates//vendor alias per line, '#' comments.

    These are crate roots in addition to the aliases vendored BUILD files name: the
    direct crates.io deps of the pilots' closures (docs/closure/*.json, crates_io.direct),
    so their crates are generated before the in-tree crates that use them are vendored.
    """
    names: list[str] = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if not _ALIAS_NAME.fullmatch(line):
            raise RegenError(f"{where}:{n}: expected one alias name, got {line!r}")
        if line in names:
            raise RegenError(f"{where}:{n}: {line} is listed twice")
        if names and line < names[-1]:
            raise RegenError(f"{where}:{n}: {line} is out of order (keep the list sorted)")
        names.append(line)
    return names


def read_lock(root: Path) -> tuple[str, str]:
    """(fuchsia_revision, cargo_lock_sha256) from overlay.lock.json."""
    lock = json.loads((root / "overlay.lock.json").read_text())
    try:
        revision = lock["fuchsia_revision"]["value"]
        cargo_sha = lock["cargo_lock_sha256"]["value"]
    except (KeyError, TypeError):
        raise RegenError("overlay.lock.json: needs fuchsia_revision and cargo_lock_sha256") from None
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RegenError(f"overlay.lock.json: fuchsia_revision {revision!r} is not a commit")
    return revision, cargo_sha


# --- BUILD file rewriting ---------------------------------------------------------
#
# BUILD files are parsed with Python's `ast` (Starlark's BUILD dialect is a subset of
# Python's syntax), so strings, calls and loads are found structurally; comments are
# never touched. The rewriter fails closed: a load it has no mapping for, a Rust rule
# it cannot mark `vendored = True`, or a label written other than as a plain
# double-quoted string stops the run and names file:line.

# Loads kept as they are in upstream in-tree BUILD files.
_KEEP_LOADS = ("@rules_license//rules:license.bzl", "@rules_license//rules:package_info.bzl")
_UPSTREAM_RUST_RULES = "//build/bazel/rules/rust:defs.bzl"
# rules_rust rules an upstream BUILD file calls directly (e.g. src/lib/fuchsia-async-macro
# uses rust_proc_macro). Decision (M5 review): map them to the overlay's wrappers, which
# inherit every rules_rust attribute, so they get vendored = True (--cap-lints=allow)
# like the rest of vendor/. The load is rewritten with aliases, so call sites keep their
# names: load("//rules:rustc.bzl", rust_proc_macro = "rustc_proc_macro").
_RULES_RUST_DEFS = "@rules_rust//rust:defs.bzl"
_RULES_RUST_TO_WRAPPER = {
    "rust_binary": "rustc_binary",
    "rust_library": "rustc_library",
    "rust_proc_macro": "rustc_proc_macro",
}
_RUST_CALL_NAME = re.compile(r"rustc?_")
_PLAIN_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"')


class _Source:
    """Text with (line, UTF-8 column) -> character offset conversion for ast positions."""

    def __init__(self, text: str, where: str):
        self.text = text
        self.where = where
        self.lines = text.splitlines(keepends=True)
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))
        try:
            self.tree = ast.parse(text, filename=where)
        except SyntaxError as e:
            raise RegenError(f"{where}:{e.lineno}: cannot parse: {e.msg}") from None

    def offset(self, lineno: int, col: int) -> int:
        line = self.lines[lineno - 1]
        return self.starts[lineno - 1] + len(line.encode()[:col].decode())

    def span(self, node: ast.AST) -> tuple[int, int]:
        return (self.offset(node.lineno, node.col_offset),
                self.offset(node.end_lineno, node.end_col_offset))

    def segment(self, node: ast.AST) -> str:
        start, end = self.span(node)
        return self.text[start:end]

    def fail(self, node: ast.AST, message: str) -> RegenError:
        return RegenError(f"{self.where}:{node.lineno}: {message}")


def _loads(src: _Source) -> list[tuple[ast.Call, str, list[tuple[str, str]]]]:
    """Each load(): (call, file, [(local name, loaded name)])."""
    out = []
    for node in ast.walk(src.tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "load":
            args = node.args
            if not args or not isinstance(args[0], ast.Constant) or not isinstance(args[0].value, str):
                raise src.fail(node, "load() without a file string")
            symbols = []
            for a in args[1:]:
                if not isinstance(a, ast.Constant) or not isinstance(a.value, str):
                    raise src.fail(node, "load() symbol is not a string")
                symbols.append((a.value, a.value))
            for k in node.keywords:
                if k.arg is None or not isinstance(k.value, ast.Constant) or not isinstance(k.value.value, str):
                    raise src.fail(node, "load() alias is not name = \"symbol\"")
                symbols.append((k.arg, k.value.value))
            out.append((node, args[0].value, symbols))
    return out


def _string_edits(src: _Source, label, skip: set[int]) -> list[tuple[int, int, str]]:
    """Edits replacing each label-like string with label(value).

    Strings inside nodes whose id() is in `skip` (load statements) are left alone. A
    label-like string ("//..." or "@...") must be a plain double-quoted literal.
    """
    skipped: set[int] = set()
    for node in ast.walk(src.tree):
        if id(node) in skip:
            skipped.update(id(n) for n in ast.walk(node))
    edits = []
    for node in ast.walk(src.tree):
        if id(node) in skipped or not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        value = node.value
        if not value.startswith(("//", "@")):
            continue
        seg = src.segment(node)
        if not _PLAIN_STRING.fullmatch(seg):
            raise src.fail(node, f"label {value!r} is not a plain double-quoted string ({seg})")
        new = label(value, node)
        if new != value:
            start, end = src.span(node)
            edits.append((start, end, json.dumps(new)))
    return edits


def _apply(text: str, edits: list[tuple[int, int, str]]) -> str:
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    return text


def _wrapper_calls(src: _Source, wrappers: dict[str, str]) -> list[ast.Call]:
    """Calls of loaded wrapper macros; any other rust_*/rustc_* call fails."""
    calls = []
    for node in ast.walk(src.tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if isinstance(func, ast.Name) and name in wrappers:
            calls.append(node)
        elif name and _RUST_CALL_NAME.match(name):
            raise src.fail(node, f"{name}() is not loaded from a rules file regen.py maps; "
                                 f"write an overlay ({OVERLAYS}/<path>/BUILD.bazel)")
    return calls


def _vendored_edits(src: _Source, calls: list[ast.Call]) -> list[tuple[int, int, str]]:
    edits = []
    for call in calls:
        if any(k.arg == "vendored" for k in call.keywords):
            raise src.fail(call, "a Rust rule already sets vendored; regen.py adds it, so write "
                                 f"an overlay ({OVERLAYS}/<path>/BUILD.bazel) instead")
        pos = src.offset(call.func.end_lineno, call.func.end_col_offset)
        paren = src.text.index("(", pos)
        line_start = src.text.rfind("\n", 0, paren) + 1
        indent = re.match(r"[ \t]*", src.text[line_start:]).group(0)
        if src.text[paren + 1:paren + 2] == "\n":
            new = f"\n{indent}    vendored = True,  # {GENERATED_BY}"
        else:
            new = "vendored = True, "
        edits.append((paren + 1, paren + 1, new))
    return edits


def _check_all_vendored(text: str, where: str) -> None:
    """Every wrapper call in `text` must pass vendored = True (checked after rewriting)."""
    src = _Source(text, where)
    wrappers = {local: name for call, f, syms in _loads(src) if f == "//rules:rustc.bzl"
                for local, name in syms}
    for call in _wrapper_calls(src, wrappers):
        if not any(k.arg == "vendored" and isinstance(k.value, ast.Constant) and k.value.value is True
                   for k in call.keywords):
            raise src.fail(call, f"{call.func.id} call without vendored = True")


def _split_label(label: str) -> tuple[str, str]:
    """"//a/b:c" -> ("a/b", ":c"); "//a/b" -> ("a/b", "")."""
    body = label[2:]
    pkg, colon, target = body.partition(":")
    return pkg, (colon + target) if colon else ""


def crate_dir(pkg: str) -> str | None:
    """The crate directory, relative to third_party/rust_crates, of an upstream package.

    "third_party/rust_crates/vendor/foo-1.0.0" -> "vendor/foo-1.0.0" (a crates.io crate);
    "third_party/rust_crates/forks/libc-0.2.189" -> "forks/libc-0.2.189" (patched, M6b);
    anything else, including the vendor alias package itself, -> None.
    """
    if not pkg.startswith(RUST_CRATES + "/"):
        return None
    rel = pkg[len(RUST_CRATES) + 1:]
    kind, _, rest = rel.partition("/")
    if kind == "vendor" and rest and "/" not in rest:
        return rel
    if kind in PATCHED_KINDS and rest:
        return rel
    return None


_CRATE_LABEL_HELP = (f"only crates.io crates ({RUST_CRATES_VENDOR}) and patched crates "
                     f"({', '.join(f'{RUST_CRATES}/{k}' for k in PATCHED_KINDS)}) are supported")


def rewrite_upstream_build(text: str, where: str, vendored_paths: set[str]) -> str:
    """Rewrite an upstream in-tree BUILD.bazel for vendor/fuchsia/ (see module doc)."""
    src = _Source(text, where)
    edits: list[tuple[int, int, str]] = []
    wrappers: dict[str, str] = {}
    load_nodes: set[int] = set()
    for call, file, symbols in _loads(src):
        load_nodes.add(id(call))
        if file == _UPSTREAM_RUST_RULES:
            for local, name in symbols:
                if name not in RUSTC_MACROS:
                    raise src.fail(call, f"loads {name} from {file}; the overlay's //rules:rustc.bzl "
                                         f"provides only {', '.join(RUSTC_MACROS)} (rustc_test is M16)")
                wrappers[local] = name
            start, end = src.span(call.args[0])
            edits.append((start, end, '"//rules:rustc.bzl"'))
        elif file == _RULES_RUST_DEFS:
            parts = []
            for local, name in symbols:
                if name not in _RULES_RUST_TO_WRAPPER:
                    raise src.fail(call, f"loads {name} from {file}; regen.py maps only "
                                         f"{', '.join(_RULES_RUST_TO_WRAPPER)} (to the overlay's wrappers)")
                wrappers[local] = _RULES_RUST_TO_WRAPPER[name]
                parts.append(f'{local} = "{_RULES_RUST_TO_WRAPPER[name]}"')
            start, end = src.span(call)
            edits.append((start, end, 'load("//rules:rustc.bzl", ' + ", ".join(parts) + ")"))
        elif file not in _KEEP_LOADS:
            raise src.fail(call, f"load of {file}: regen.py has no mapping for it; add one or "
                                 f"write an overlay ({OVERLAYS}/<path>/BUILD.bazel)")

    def label(s: str, node: ast.AST) -> str:
        if s.startswith(_BUILTIN_PREFIXES) or not s.startswith("//"):
            return s
        pkg, target = _split_label(s)
        if s == "//build/config/rust/lints" or (pkg == "build/config/rust/lints" and target):
            return "//rules/lints" + target
        if pkg == "" and target in (":license", ":__subpackages__", ":__pkg__"):
            return f"//{VENDOR_OUT}{target}"
        if pkg == RUST_CRATES_VENDOR and target:
            return f"@{CRATES_REPO}//vendor" + target
        d = crate_dir(pkg)
        if d and not d.startswith("vendor/"):
            return f"@{CRATES_REPO}//{d}{target}"
        if pkg == RUST_CRATES or pkg.startswith(RUST_CRATES + "/"):
            raise src.fail(node, f"{s}: {_CRATE_LABEL_HELP}; use an alias from {RUST_CRATES_VENDOR}")
        if pkg in vendored_paths or (pkg and target in (":__pkg__", ":__subpackages__")):
            # Visibility may name packages that are not vendored; it needs no target.
            return f"//{VENDOR_OUT}/{pkg}{target}"
        if pkg.startswith("build/") or pkg == "":
            raise src.fail(node, f"{s}: no overlay mapping for this label")
        raise src.fail(node, f"depends on {s}, but {pkg} is not listed in {VENDOR_LIST}")

    edits += _string_edits(src, label, load_nodes)
    edits += _vendored_edits(src, _wrapper_calls(src, wrappers))
    out = _apply(text, edits)
    _check_all_vendored(out, where)
    return out


def check_overlay_build(text: str, where: str) -> None:
    """Overlay BUILD files are ours: Rust rules come from //rules:rustc.bzl, vendored = True."""
    src = _Source(text, where)
    for call, file, _ in _loads(src):
        if file.startswith("@rules_rust//"):
            raise src.fail(call, f"loads from {file}; overlays use the wrappers in //rules:rustc.bzl")
    _string_edits(src, lambda s, n: s, set())  # labels must be plain double-quoted strings
    _check_all_vendored(text, where)


def build_strings(text: str, where: str) -> list[str]:
    """Every string constant in a BUILD file."""
    return [n.value for n in ast.walk(_Source(text, where).tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def rewrite_crate_build(text: str, where: str) -> tuple[str, set[str]]:
    """Rewrite an upstream crate_universe BUILD file for the @rust_crates repository.

    Returns the text and the crate directories its labels name, relative to
    third_party/rust_crates ("vendor/<crate>-<version>", "forks/<dir>", "ask2patch/<dir>"),
    so the caller can follow the closure. In @rust_crates each keeps that path.
    """
    src = _Source(text, where)
    deps: set[str] = set()

    def label(s: str, node: ast.AST) -> str:
        if s.startswith(_BUILTIN_PREFIXES) or not s.startswith("//"):
            return s
        pkg, target = _split_label(s)
        d = crate_dir(pkg)
        if d:
            deps.add(d)
            return f"//{d}{target}"
        if pkg.startswith(RUST_CRATES):
            raise src.fail(node, f"{s}: {_CRATE_LABEL_HELP}")
        raise src.fail(node, f"{s}: unexpected label in a crate_universe BUILD file")

    return _apply(text, _string_edits(src, label, set())), deps


_ALIAS = re.compile(r'alias\(\s*name = "([^"]+)",\s*actual = "([^"]+)",(?:\s*tags = \[[^\]]*\],)?\s*\)')


def parse_aliases(text: str) -> dict[str, str]:
    """name -> actual for each alias() in upstream's third_party/rust_crates/vendor/BUILD.bazel."""
    return {m.group(1): m.group(2) for m in _ALIAS.finditer(text)}


def _package_info(text: str, where: str) -> tuple[str, str]:
    name = re.search(r'package_name = "([^"]+)"', text)
    version = re.search(r'package_version = "([^"]+)"', text)
    if not name or not version:
        raise RegenError(f"{where}: no package_info with package_name and package_version")
    return name.group(1), version.group(1)


def cargo_lock_checksums(text: str) -> dict[tuple[str, str], str]:
    """(name, version) -> SHA-256 for every crates.io package in a Cargo.lock."""
    data = tomllib.loads(text)
    out = {}
    for pkg in data.get("package", []):
        if pkg.get("source") == CRATES_IO_SOURCE and "checksum" in pkg:
            out[(pkg["name"], pkg["version"])] = pkg["checksum"]
    return out


def cargo_lock_local(text: str) -> set[tuple[str, str]]:
    """(name, version) of every package without a source (path dependencies and
    [patch] entries: the patched crates under forks/ and ask2patch/)."""
    return {(pkg["name"], pkg["version"]) for pkg in tomllib.loads(text).get("package", [])
            if "source" not in pkg}


# --- generation ------------------------------------------------------------------


def _header(revision: str, upstream: str, what: str) -> str:
    return (f"# {GENERATED_BY} from fuchsia.git {revision}:{upstream}\n"
            f"# ({what}). Do not edit: change {OVERLAYS}/ or {PATCHES}/ and rerun it.\n")


def _crate_header(revision: str, upstream: str, what: str) -> str:
    return (f"# {GENERATED_BY} from fuchsia.git {revision}:{upstream}\n"
            f"# ({what}).\n"
            f"# Do not edit: the crate set follows the deps of the vendored BUILD files, and the\n"
            f"# pins follow overlay.lock.json; change those and rerun regen.py.\n")


# No SPDX header: this is upstream's license target, so REUSE.toml's vendor/fuchsia/**
# annotation (BSD-2-Clause, the Fuchsia Authors) is the only one that applies to it.
_VENDOR_ROOT_BUILD = """\
# {generated} from fuchsia.git {revision}:build/bazel/toplevel.BUILD.bazel
# (its license target, unchanged). Do not edit.
#
# The license of everything under vendor/fuchsia/: upstream BUILD files name it as
# //:license, which regen.py rewrites to //vendor/fuchsia:license.

load("@rules_license//rules:license.bzl", "license")

license(
    name = "license",
    license_kinds = ["@rules_license//licenses/spdx:BSD-2-Clause"],
    license_text = "LICENSE",
    visibility = ["//visibility:public"],
)
"""

_CRATES_BUILD = """\
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
#
# {generated}. Do not edit.
#
# //toolchain:crates.bzl reads crates.json and the BUILD.*.bazel files here to create
# the @rust_crates repository (upstream's third_party/rust_crates layout).

exports_files(glob(["BUILD.*.bazel"]) + ["crates.json"])
"""


def _files_of(source: Source, crate: Crate) -> dict[str, int]:
    """The crate's files, without subdirectories that are packages of their own."""
    files = source.files(crate.path)
    subpackages = {str(PurePosixPath(f).parent) for f in files
                   if PurePosixPath(f).name in PACKAGE_FILES and str(PurePosixPath(f).parent) != crate.path}
    return {f: m for f, m in files.items()
            if not any(f.startswith(sp + "/") for sp in subpackages)}


def _write(out: Path, rel: str, data: bytes, mode: int = 0o644) -> None:
    p = out / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    p.chmod(mode)


def apply_patches(root: Path, vendor_dir: Path, crates: list[Crate], home: Path) -> list[str]:
    """Apply patches/fuchsia/<path>/*.patch in name order, relative to the fuchsia.git root.

    Returns the applied patches (repo-relative). A patch that does not apply stops the run
    with its name and the file it failed on.
    """
    applied = []
    for crate in crates:
        pdir = root / PATCHES / crate.path
        if not pdir.is_dir():
            continue
        for patch in sorted(pdir.glob("*.patch")):
            rel = patch.relative_to(root).as_posix()
            env = {"GIT_CEILING_DIRECTORIES": str(vendor_dir.parent)}
            try:
                stat_out = isolated_git(vendor_dir, home, "apply", "--numstat", str(patch), extra_env=env)
            except FetchError as e:
                raise RegenError(f"{rel}: not a patch git can read: {e}") from None
            touched = [line.split("\t", 2)[2] for line in stat_out.decode().splitlines() if line]
            outside = [t for t in touched if not t.startswith(crate.path + "/")]
            if outside or not touched:
                raise RegenError(f"{rel}: patches under {PATCHES}/{crate.path}/ may change only files "
                                 f"of {crate.path}; this one changes {', '.join(outside) or 'nothing'}")
            try:
                # GIT_CEILING_DIRECTORIES keeps git from treating an enclosing repository
                # as the one to patch; outside a repository `git apply` works like patch(1).
                isolated_git(vendor_dir, home, "apply", "--whitespace=nowarn", str(patch), extra_env=env)
            except FetchError as e:
                # git's last line names the file: "error: <file>: patch does not apply",
                # "error: <file>: No such file or directory", "error: patch failed: <file>:<n>".
                msg = str(e)
                m = re.search(r"error: (?:patch failed: )?([^:\s]+)", msg)
                failed = m.group(1) if m else "?"
                raise RegenError(f"{rel}: does not apply to {VENDOR_OUT}/{failed}: {msg}") from None
            applied.append(rel)
    return applied


def _check_orphans(root: Path, crates: list[Crate]) -> None:
    """Every file under overlays/ and patches/fuchsia/ must be used, or it would be ignored.

    overlays/ may hold only <path>/BUILD.bazel for a crate listed 'overlay';
    patches/fuchsia/ only <path>/*.patch for a listed crate.
    """
    overlay_crates = {c.path for c in crates if c.build == "overlay"}
    listed = {c.path for c in crates}
    for f in sorted(p for p in (root / OVERLAYS).rglob("*") if not p.is_dir()) if (root / OVERLAYS).is_dir() else []:
        rel = f.relative_to(root).as_posix()
        path = f.parent.relative_to(root / OVERLAYS).as_posix()
        if f.name != "BUILD.bazel":
            raise RegenError(f"{rel}: not an overlay (only {OVERLAYS}/<path>/BUILD.bazel is used)")
        if path in listed and path not in overlay_crates:
            raise RegenError(f"{rel} exists, but {VENDOR_LIST} says 'upstream'")
        if path not in listed:
            raise RegenError(f"{rel}: {path} is not listed in {VENDOR_LIST}")
    for f in sorted(p for p in (root / PATCHES).rglob("*") if not p.is_dir()) if (root / PATCHES).is_dir() else []:
        rel = f.relative_to(root).as_posix()
        path = f.parent.relative_to(root / PATCHES).as_posix()
        if f.suffix != ".patch":
            raise RegenError(f"{rel}: not a patch (only {PATCHES}/<path>/*.patch is applied)")
        if path not in listed:
            raise RegenError(f"{rel}: {path} is not listed in {VENDOR_LIST}")


def generate(root: Path, source: Source, out: Path, cargo_lock_sha256: str, home: Path) -> None:
    """Write every output tree (OUTPUTS) under `out`, from `source` and the repo's inputs."""
    crates = read_vendor_list((root / VENDOR_LIST).read_text())
    if not crates:
        raise RegenError(f"{VENDOR_LIST}: lists no crates")
    rev = source.revision
    vendored = {c.path for c in crates}
    _check_orphans(root, crates)
    vendor = out / VENDOR_OUT
    vendor.mkdir(parents=True)

    crate_files = {c.path: _files_of(source, c) for c in crates}
    # One read, so a GitSource fetches every blob in one request.
    everything = source.read(list(ROOT_FILES) + sorted(f for fs in crate_files.values() for f in fs))
    for name in ROOT_FILES:
        _write(vendor, name, everything[name])
    _write(vendor, "BUILD.bazel", _VENDOR_ROOT_BUILD.format(generated=GENERATED_BY, revision=rev).encode())

    for crate in crates:
        files = crate_files[crate.path]
        build = f"{crate.path}/BUILD.bazel"
        overlay = root / OVERLAYS / crate.path / "BUILD.bazel"
        contents = {f: everything[f] for f in sorted(files)}
        for rel, data in contents.items():
            if rel == build:
                continue
            _write(vendor, rel, data, files[rel])
        if crate.build == "upstream":
            if build not in contents:
                raise RegenError(f"{VENDOR_LIST}: {crate.path} is 'upstream', but upstream has no "
                                 f"BUILD.bazel there; write {OVERLAYS}/{crate.path}/BUILD.bazel "
                                 "and list it as 'overlay'")
            text = rewrite_upstream_build(contents[build].decode(), build, vendored)
            text = _header(rev, build, "labels rewritten, vendored = True added") + text
        else:
            if not overlay.is_file():
                raise RegenError(f"{VENDOR_LIST}: {crate.path} is 'overlay', but "
                                 f"{OVERLAYS}/{crate.path}/BUILD.bazel does not exist")
            text = overlay.read_text()
            check_overlay_build(text, f"{OVERLAYS}/{crate.path}/BUILD.bazel")
        _write(vendor, build, text.encode())

    apply_patches(root, vendor, crates, home)
    list_file = root / CRATES_IO_LIST
    if not list_file.is_file():
        raise RegenError(f"{CRATES_IO_LIST}: missing (list the crates.io aliases to generate, "
                         "one per line; it may list none)")
    generate_crates(vendor, source, out / CRATES_OUT, cargo_lock_sha256,
                    read_crates_io_list(list_file.read_text()))


def generate_crates(vendor: Path, source: Source, out: Path, cargo_lock_sha256: str,
                    extra_aliases: list[str] = ()) -> None:
    """third_party/crates/: the closure of the @rust_crates labels under `vendor`, plus
    the aliases in `extra_aliases` (vendor/crates_io.txt).

    crates.io crates are downloaded at build time by the SHA-256 in crates.json; patched
    crates (forks/, ask2patch/) are copied here from fuchsia.git, under src/<kind>/<dir>/,
    with their BUILD.bazel moved beside the others (so no package is created in the
    main repository and --check covers every source file).
    """
    prefix = f"@{CRATES_REPO}//vendor:"
    repo_prefix = f"@{CRATES_REPO}//"
    strings = [s for build in sorted(vendor.rglob("BUILD.bazel"))
               for s in build_strings(build.read_text(), str(build))]
    roots = {s[len(prefix):] for s in strings if s.startswith(prefix)} | set(extra_aliases)
    # Labels straight into a patched crate (rewrite_upstream_build maps them).
    direct: set[str] = set()
    for s in strings:
        if s.startswith(repo_prefix) and not s.startswith(prefix):
            d = crate_dir(f"{RUST_CRATES}/" + _split_label("//" + s[len(repo_prefix):])[0])
            if d is None or d.startswith("vendor/"):
                raise RegenError(f"{s}: not a crate regen.py can generate ({_CRATE_LABEL_HELP})")
            direct.add(d)
    out.mkdir(parents=True)
    rev = source.revision
    header_note = "labels rewritten for the @rust_crates repository"
    if not roots and not direct:
        crates_json: dict = {"aliases": [], "crates": []}
    else:
        alias_file = f"{RUST_CRATES_VENDOR}/BUILD.bazel"
        texts = source.read([alias_file, CARGO_LOCK])
        lock_sha = hashlib.sha256(texts[CARGO_LOCK]).hexdigest()
        if lock_sha != cargo_lock_sha256:
            raise RegenError(f"{CARGO_LOCK}: SHA-256 {lock_sha} at {rev}, but overlay.lock.json "
                             f"has cargo_lock_sha256 {cargo_lock_sha256}")
        checksums = cargo_lock_checksums(texts[CARGO_LOCK].decode())
        local = cargo_lock_local(texts[CARGO_LOCK].decode())
        aliases = parse_aliases(texts[alias_file].decode())
        alias_blocks = []
        todo: set[str] = set(direct)
        for name in sorted(roots):
            actual = aliases.get(name)
            if actual is None:
                raise RegenError(f"@{CRATES_REPO}//vendor:{name}: upstream {alias_file} has no alias {name!r}")
            text, deps = rewrite_crate_build(f'"{actual}"', alias_file)
            alias_blocks.append(f'alias(\n    name = "{name}",\n    actual = {text},\n)\n')
            todo |= deps
        seen: set[str] = set()
        entries = []
        build_files: dict[str, str] = {}
        frontier = sorted(todo)
        while frontier:
            # One read (one blob fetch) per level of the dependency graph.
            seen.update(frontier)
            files = {d: f"{RUST_CRATES}/{d}/BUILD.bazel" for d in frontier}
            raws = source.read(sorted(files.values()))
            nxt: set[str] = set()
            for d in frontier:
                upstream = files[d]
                raw = raws[upstream].decode()
                name, version = _package_info(raw, upstream)
                text, deps = rewrite_crate_build(raw, upstream)
                if d.startswith("vendor/"):
                    if d != f"vendor/{name}-{version}":
                        raise RegenError(f"{upstream}: package_info says {name} {version}, not {d[7:]}")
                    sha = checksums.get((name, version))
                    if sha is None:
                        raise RegenError(f"{upstream}: {name} {version} is not a crates.io package in {CARGO_LOCK}")
                    build_file = f"BUILD.{d[7:]}.bazel"
                    entry = {"sha256": sha, "strip_prefix": d[7:],
                             "url": CRATE_URL.format(name=name, version=version)}
                else:
                    if (name, version) not in local:
                        raise RegenError(f"{upstream}: {name} {version} is not a local (patched) "
                                         f"package in {CARGO_LOCK}")
                    build_file = f"BUILD.{d.replace('/', '.')}.bazel"
                    entry = {"files": _copy_patched(source, d, out)}
                if build_file in build_files:
                    raise RegenError(f"{upstream}: {build_file} would also be written for "
                                     f"{build_files[build_file]}")
                build_files[build_file] = d
                _write(out, build_file, (_crate_header(rev, upstream, header_note) + text).encode())
                entries.append({"build_file": build_file, "name": name, "path": d,
                                "version": version, **entry})
                nxt |= deps
            frontier = sorted(nxt - seen)
        entries.sort(key=lambda e: e["path"])
        aliases_text = (_crate_header(rev, alias_file, "only the aliases the overlay uses; " + header_note)
                        + '\npackage(default_visibility = ["//visibility:public"])\n\n'
                        + "\n".join(alias_blocks))
        _write(out, "BUILD.vendor.bazel", aliases_text.encode())
        crates_json = {"aliases": sorted(roots), "crates": entries}
    crates_json = {
        "cargo_lock": f"{FUCHSIA_GIT} {rev}:{CARGO_LOCK}",
        "cargo_lock_sha256": cargo_lock_sha256,
        "vendor_build_file": "BUILD.vendor.bazel" if roots or direct else None,
        **crates_json,
    }
    _write(out, "crates.json", (json.dumps(crates_json, indent=2, sort_keys=True) + "\n").encode())
    _write(out, "BUILD.bazel", _CRATES_BUILD.format(generated=GENERATED_BY).encode())


def _copy_patched(source: Source, d: str, out: Path) -> list[str]:
    """Copy fuchsia.git's third_party/rust_crates/<d>/ to <out>/src/<d>/, except its
    BUILD.bazel (written as BUILD.<kind>.<dir>.bazel). Returns the files, relative to it."""
    base = f"{RUST_CRATES}/{d}"
    modes = source.files(base)
    rels = sorted(f[len(base) + 1:] for f in modes if f != f"{base}/BUILD.bazel")
    for rel in rels:
        if PurePosixPath(rel).name in _PACKAGE_MARKERS:
            raise RegenError(f"{base}/{rel}: a patched crate may not contain another "
                             f"{PurePosixPath(rel).name}; @rust_crates keeps the crate as one package")
    contents = source.read([f"{base}/{rel}" for rel in rels])
    for rel in rels:
        _write(out, f"{CRATES_SRC}/{d}/{rel}", contents[f"{base}/{rel}"], modes[f"{base}/{rel}"])
    return rels


# --- install and check -----------------------------------------------------------


def _tree(base: Path) -> dict[str, tuple[bytes, bool]]:
    """rel path -> (content, executable) for every file under base."""
    out = {}
    if base.is_dir():
        for p in sorted(base.rglob("*")):
            if p.is_file() or p.is_symlink():
                out[p.relative_to(base).as_posix()] = (
                    p.read_bytes() if p.is_file() else b"<symlink>",
                    bool(p.stat().st_mode & stat.S_IXUSR) if p.is_file() else False)
    return out


def diff_trees(root: Path, generated: Path) -> list[str]:
    """Drift between the repo's output trees and freshly generated ones, one line per file."""
    problems = []
    for rel in OUTPUTS:
        have, want = _tree(root / rel), _tree(generated / rel)
        for f in sorted(set(have) | set(want)):
            path = f"{rel}/{f}"
            if f not in have:
                problems.append(f"{path}: missing (regen.py would create it)")
            elif f not in want:
                problems.append(f"{path}: not generated by regen.py (remove it, or change the inputs)")
            elif have[f][0] != want[f][0]:
                problems.append(f"{path}: content differs from upstream plus overlays and patches")
            elif have[f][1] != want[f][1]:
                problems.append(f"{path}: executable bit differs")
    return problems


def install(root: Path, generated: Path) -> None:
    """Replace each output tree in the repo with the generated one."""
    for rel in OUTPUTS:
        dest = root / rel
        new = dest.with_name(dest.name + ".regen-new")
        old = dest.with_name(dest.name + ".regen-old")
        for p in (new, old):
            if p.exists():
                shutil.rmtree(p)
        shutil.copytree(generated / rel, new)
        if dest.exists():
            dest.rename(old)
        new.rename(dest)
        if old.exists():
            shutil.rmtree(old)


def run(root: Path, check: bool, make_source=None) -> int:
    revision, cargo_sha = read_lock(root)
    with tempfile.TemporaryDirectory(prefix="regen-") as tmp:
        tmp = Path(tmp)
        home = tmp / "home"
        home.mkdir()
        if make_source is None:
            source = GitSource(FUCHSIA_GIT, revision, tmp / "git")
        else:
            source = make_source(revision)
        generated = tmp / "out"
        generate(root, source, generated, cargo_sha, home)
        if check:
            problems = diff_trees(root, generated)
            for p in problems:
                print(f"regen.py --check: {p}", file=sys.stderr)
            if problems:
                print(f"regen.py --check: {len(problems)} file(s) drift from fuchsia.git {revision} "
                      f"plus {OVERLAYS}/ and {PATCHES}/; rerun `scripts/regen.py vendor`",
                      file=sys.stderr)
                return 1
            print(f"regen.py --check: {', '.join(OUTPUTS)} match fuchsia.git {revision}")
            return 0
        install(root, generated)
        print(f"regen.py: wrote {', '.join(OUTPUTS)} from fuchsia.git {revision}")
        return 0


def main(argv: list[str] | None = None, root: Path = ROOT, make_source=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", nargs="?", choices=["vendor"], default=None,
                        help="the stage to run (only 'vendor' exists so far)")
    parser.add_argument("--check", action="store_true",
                        help="regenerate into a scratch directory and fail on drift")
    args = parser.parse_args(argv)
    if args.stage is None and not args.check:
        parser.error("give a stage ('vendor') or --check")
    try:
        return run(root, args.check, make_source)
    except RegenError as e:
        print(f"regen.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
