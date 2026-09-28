# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/emu.py: everything the harness derives from overlay.lock.json (C3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import emu

V = "33.20260927.4.1"
PB_URL = f"https://storage.googleapis.com/fuchsia/development/{V}/product_bundles.json"
TRANSFER = "gs://fuchsia-public-artifacts-release/builds/8669503301662913825/product_bundles/core.x64/transfer.json"


def lock(version=V, source=None):
    return {"sdk_version": {"value": version, "source": [PB_URL] if source is None else source}}


def test_the_committed_lock_is_readable():
    real = emu.read_lock()
    assert emu.product_bundles_url(real).endswith(f"/{emu.lock_version(real)}/product_bundles.json")


def test_product_bundles_url_comes_from_the_lock():
    assert emu.product_bundles_url(lock()) == PB_URL


def test_product_bundles_url_must_be_the_locks_source():
    with pytest.raises(emu.EmuError, match="does not list"):
        emu.product_bundles_url(lock(source=["https://example.com/x"]))


def test_lock_version_rejects_junk():
    with pytest.raises(emu.EmuError, match="not a version"):
        emu.lock_version(lock(version="../../etc"))


BUNDLES = [
    {"name": "core.vim3", "product_version": V, "transfer_manifest_url": TRANSFER.replace("core.x64", "core.vim3")},
    {"name": "core.x64", "product_version": V, "transfer_manifest_url": TRANSFER},
]


def test_transfer_manifest_url():
    assert emu.transfer_manifest_url(BUNDLES, "core.x64", V) == TRANSFER


def test_transfer_manifest_url_missing_product():
    with pytest.raises(emu.EmuError, match="0 entries named core.x64"):
        emu.transfer_manifest_url(BUNDLES[:1], "core.x64", V)


def test_transfer_manifest_url_duplicate_product():
    with pytest.raises(emu.EmuError, match="2 entries"):
        emu.transfer_manifest_url(BUNDLES + BUNDLES[1:], "core.x64", V)


def test_transfer_manifest_url_wrong_version():
    bad = [{**BUNDLES[1], "product_version": "33.20260919.6.1"}]
    with pytest.raises(emu.EmuError, match="the lock has"):
        emu.transfer_manifest_url(bad, "core.x64", V)


@pytest.mark.parametrize("url", ["https://evil/transfer.json", "gs://bucket/other.json", ""])
def test_transfer_manifest_url_shape(url):
    with pytest.raises(emu.EmuError, match="unexpected transfer manifest"):
        emu.transfer_manifest_url([{**BUNDLES[1], "transfer_manifest_url": url}], "core.x64", V)


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
    for cmd in ("setup", "start", "check", "run", "driver", "env"):
        assert f"scripts/emu {cmd}" in out
