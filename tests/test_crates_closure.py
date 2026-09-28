# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""The generated crate set matches pilot 1's measured closure (milestone M6b, R4).

Consistency checks between committed files: vendor/crates_io.txt (regen.py's crate
roots) against docs/closure/pilot1.json (closure.py's measurement), and
third_party/crates/crates.json (regen.py's output) against the closure's transitive set.
"""

from __future__ import annotations

import json
from pathlib import Path

import regen

ROOT = Path(__file__).resolve().parent.parent
CLOSURE = json.loads((ROOT / "docs/closure/pilot1.json").read_text())
CRATES = json.loads((ROOT / "third_party/crates/crates.json").read_text())


def test_roots_are_the_closures_direct_aliases():
    roots = regen.read_crates_io_list((ROOT / regen.CRATES_IO_LIST).read_text())
    assert roots == sorted(d["alias"] for d in CLOSURE["crates_io"]["direct"])
    assert set(roots) <= set(CRATES["aliases"])


def test_only_the_closures_crates_are_generated():
    """Not all of Cargo.lock: exactly crates_io.transitive (121 at 33.20260927.4.1)."""
    generated = {c["path"]: c for c in CRATES["crates"]}
    closure = {c["dir"]: c for c in CLOSURE["crates_io"]["transitive"]}
    assert set(generated) == set(closure)
    for path, c in closure.items():
        g = generated[path]
        assert (g["name"], g["version"], g["proc_macro"]) == (c["name"], c["version"], c["proc_macro"])
        assert ("files" in g) == c["patched"], path


def test_patched_crates_are_committed_with_their_license_files():
    for c in CRATES["crates"]:
        if "files" not in c:
            continue
        src = ROOT / "third_party/crates" / regen.CRATES_SRC / c["path"]
        assert sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()) == c["files"]
        assert any(f.startswith(("LICENSE", "COPYING", "UNLICENSE")) for f in c["files"]), c["path"]
