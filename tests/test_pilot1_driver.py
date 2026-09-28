# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Pilot 1's driver package (milestone M10) matches upstream and its measured closure.

drivers/simple_rust/ holds upstream's src/lib.rs and meta/simple_rust_driver.cml
unchanged, and its fuchsia_rust_driver has exactly the direct deps that
docs/closure/pilot1.json records for //examples/drivers/simple/rust:driver, mapped to the
overlay's labels (GN's deps unchanged; the unused ones are allowed by the rule's lints).
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVER_DIR = ROOT / "drivers/simple_rust"
CLOSURE = json.loads((ROOT / "docs/closure/pilot1.json").read_text())
GN_DRIVER = "//examples/drivers/simple/rust:driver"

# Git blob IDs at the lock's fuchsia_revision (git -C <fuchsia.git> rev-parse
# <revision>:examples/drivers/simple/rust/<path>); docs/evidence/M10.md.
UPSTREAM_BLOBS = {
    "src/lib.rs": "1b8f76dc5d1cf913109ab8f5837849829254a6b2",
    "meta/simple_rust_driver.cml": "0aaa32246e786dfd3bedae4395ff2b4dedca2316",
}
UPSTREAM_REVISION = "b5274053cc0f1ba03cd0902a3da575ac9c31c152"


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def call_kwargs(build: Path, rule: str, name: str) -> dict:
    """The keyword arguments of the call `rule(name = name, ...)` in a BUILD file."""
    for node in ast.walk(ast.parse(build.read_text())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == rule:
            kwargs = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
            if kwargs.get("name") == name:
                return kwargs
    raise AssertionError(f"{build}: no {rule}(name = {name!r})")


def test_upstream_files_unchanged():
    lock = json.loads((ROOT / "overlay.lock.json").read_text())
    assert UPSTREAM_REVISION in json.dumps(lock["fuchsia_revision"])
    assert CLOSURE["fuchsia_revision"] == UPSTREAM_REVISION
    for rel, blob in UPSTREAM_BLOBS.items():
        assert git_blob_id((DRIVER_DIR / rel).read_bytes()) == blob, rel


def expected_deps() -> set[str]:
    deps = set()
    for crate in CLOSURE["intree"]:
        for t in crate["targets"]:
            if GN_DRIVER in t["used_by"]:
                last = crate["path"].rsplit("/", 1)[-1]
                deps.add(f"//vendor/fuchsia/{crate['path']}" + ("" if t["target"] in (last, "rust") else f":{t['target']}"))
    deps |= {f"@rust_crates//vendor:{c['alias']}" for c in CLOSURE["crates_io"]["direct"] if GN_DRIVER in c["used_by"]}
    deps |= {f"//vendor/fuchsia/sdk/fidl/{f['library']}:{f['library']}_rust" for f in CLOSURE["fidl"] if GN_DRIVER in f["used_by"]}
    deps |= {f"//drivers/bind:{b['library']}_rust" for b in CLOSURE["bind"] if GN_DRIVER in b["used_by"]}
    return deps


def test_driver_deps_are_gn_deps():
    kwargs = call_kwargs(DRIVER_DIR / "BUILD.bazel", "fuchsia_rust_driver", "driver")
    assert set(kwargs["deps"]) == expected_deps()
    assert len(kwargs["deps"]) == 8  # BUILD.gn's deps list
    # No lint override: the rule's default allows GN's unused deps (anyhow, fdf, zx).
    assert "lint_config" not in kwargs
    assert kwargs["output_name"] == "simple_rust_driver"
    assert kwargs["edition"] == "2024"


def test_bind_crates_match_closure():
    kwargs = call_kwargs(ROOT / "drivers/bind/BUILD.bazel", "fuchsia_bind_rust_library", "fuchsia.test_rust")
    assert kwargs["library"] == "@fuchsia_sdk//bind/fuchsia.test"
    assert kwargs["library_name"] == "fuchsia.test"
    assert all(b["in_idk"] for b in CLOSURE["bind"])
