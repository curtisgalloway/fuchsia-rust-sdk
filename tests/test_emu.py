# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/emu.py: everything the harness derives from overlay.lock.json (C3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import emu
import resolve_pins

V = "33.20260927.4.1"
PB_URL = f"https://storage.googleapis.com/fuchsia/development/{V}/product_bundles.json"
TRANSFER = "gs://fuchsia-public-artifacts-release/builds/8669503301662913825/product_bundles/core.x64/transfer.json"


DIGEST = "d" * 64


def lock(version=V, **bundle):
    return {"sdk_version": {"value": version, "source": [PB_URL]},
            "product_bundle": {"product": "core.x64", "url": TRANSFER, "files": 2, "value": DIGEST,
                               "source": [PB_URL], **bundle}}


def test_the_committed_lock_names_a_bundle():
    real = emu.read_lock()
    pin = emu.bundle_pin(real, "core.x64")
    assert pin.url.endswith("/core.x64/transfer.json") and pin.files > 0


def test_bundle_pin_from_the_lock():
    assert emu.bundle_pin(lock(), "core.x64") == emu.BundlePin(TRANSFER, DIGEST, 2)


def test_bundle_pin_missing_field():
    bare = lock()
    del bare["product_bundle"]
    with pytest.raises(emu.EmuError, match="no product_bundle field"):
        emu.bundle_pin(bare, "core.x64")


@pytest.mark.parametrize("bad,match", [
    ({"product": "core.vim3"}, "not core.x64"),
    ({"url": "https://evil/transfer.json"}, "url"),
    ({"url": "gs://bucket/other.json"}, "url"),
    ({"value": "abc"}, "not a SHA-256"),
    ({"files": 0}, "files"),
    ({"files": "2"}, "files"),
])
def test_bundle_pin_rejects_malformed(bad, match):
    with pytest.raises(emu.EmuError, match=match):
        emu.bundle_pin(lock(**bad), "core.x64")


def test_lock_version_rejects_junk():
    with pytest.raises(emu.EmuError, match="not a version"):
        emu.lock_version(lock(version="../../etc"))


def make_bundle(root: Path) -> emu.BundlePin:
    (root / "blobs" / "1").mkdir(parents=True)
    (root / "blobs" / "1" / "a").write_bytes(b"blob")
    (root / "product_bundle.json").write_bytes(b"{}")
    sha = {"blobs/1/a": hashlib.sha256(b"blob").hexdigest(),
           "product_bundle.json": hashlib.sha256(b"{}").hexdigest()}
    return emu.BundlePin(TRANSFER, resolve_pins.bundle_digest(sha), 2)


def test_verify_bundle_matches(tmp_path):
    emu.verify_bundle(tmp_path, make_bundle(tmp_path))


def test_verify_bundle_changed_file(tmp_path):
    pin = make_bundle(tmp_path)
    (tmp_path / "product_bundle.json").write_bytes(b"{ }")
    with pytest.raises(emu.EmuError, match="does not match the lock"):
        emu.verify_bundle(tmp_path, pin)


def test_verify_bundle_extra_or_missing_file(tmp_path):
    pin = make_bundle(tmp_path)
    (tmp_path / "extra").write_bytes(b"")
    with pytest.raises(emu.EmuError, match="3 files"):
        emu.verify_bundle(tmp_path, pin)
    (tmp_path / "extra").unlink()
    (tmp_path / "blobs" / "1" / "a").unlink()
    with pytest.raises(emu.EmuError, match="1 files"):
        emu.verify_bundle(tmp_path, pin)


def test_verify_bundle_wrong_lock_digest(tmp_path):
    pin = make_bundle(tmp_path)
    with pytest.raises(emu.EmuError, match="does not match"):
        emu.verify_bundle(tmp_path, emu.BundlePin(pin.url, "0" * 64, pin.files))


@pytest.mark.parametrize("listing,state", [
    ("[]", None),
    ("", None),
    ('[{"name":"fuchsia-emu","state":"running"}]', "running"),
    ('[{"name":"fuchsia-emu","state":"staged"}]', "staged"),
    ('[{"name":"other","state":"running"}]', None),
])
def test_instance_state(listing, state):
    # Seen live: a running instance is "running"; after QEMU is killed it is "staged".
    assert emu.instance_state(listing, "fuchsia-emu") == state


def test_instance_state_only_running_counts():
    assert emu.instance_state('[{"name":"fuchsia-emu","state":"staged"}]', "fuchsia-emu") != "running"


@pytest.mark.parametrize("listing", ["[staged]  fuchsia-emu", '{"name":"fuchsia-emu"}',
                                     '[{"name":"fuchsia-emu"},{"name":"fuchsia-emu"}]'])
def test_instance_state_malformed(listing):
    with pytest.raises(emu.EmuError):
        emu.instance_state(listing, "fuchsia-emu")


def write_bundle(tmp_path: Path, **fields) -> Path:
    meta = {"product_name": "core.x64", "product_version": V, "sdk_version": V, **fields}
    (tmp_path / "product_bundle.json").write_text(json.dumps(meta))
    return tmp_path


def test_check_bundle_version_ok(tmp_path):
    emu.check_bundle_version(write_bundle(tmp_path), "core.x64", V)


@pytest.mark.parametrize("field", ["product_name", "product_version", "sdk_version"])
def test_check_bundle_version_mismatch(tmp_path, field):
    with pytest.raises(emu.EmuError, match="product_bundle.json says"):
        emu.check_bundle_version(write_bundle(tmp_path, **{field: "other"}), "core.x64", V)


def test_hash_tree(tmp_path):
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "b").write_bytes(b"")
    (tmp_path / "link").symlink_to(tmp_path / "a")
    assert emu.hash_tree(tmp_path) == {
        "a": "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
        "d/b": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }


def test_find_version_nested():
    show = [{"title": "Build", "label": "build", "child": [
        {"label": "version", "value": V},
        {"label": "product", "value": "core"},
    ]}]
    assert emu.find_version(show) == V


def test_find_version_product_version_key():
    assert emu.find_version({"build": {"product_version": V, "board": "x64"}}) == V


def test_find_version_ambiguous():
    with pytest.raises(emu.EmuError, match="expected one product version"):
        emu.find_version({"a": {"product_version": V}, "b": {"product_version": "1.2.3.4"}})


def test_find_version_absent():
    with pytest.raises(emu.EmuError, match=r"found \[\]"):
        emu.find_version({"build": {}})


def test_help_lists_commands(capsys):
    assert emu.main(["help"]) == 0
    out = capsys.readouterr().out
    for cmd in ("setup", "verify", "start", "check", "run", "driver", "env"):
        assert f"scripts/emu {cmd}" in out
