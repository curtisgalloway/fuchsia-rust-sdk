# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/idk_extract.py: SHA-256 before extraction, and the trim."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

import pytest

import idk_extract as ie
import idk_trim as it

ROOT = Path(__file__).resolve().parent.parent

# A miniature IDK with the layout the trim acts on.
MANIFEST = {
    "parts": [
        {"meta": "pkg/fdio/meta.json", "type": "cc_prebuilt_library"},
        {"meta": "tools/x64/cmc-meta.json", "type": "host_tool"},
        {"meta": "tools/arm64/cmc-meta.json", "type": "host_tool"},
    ]
}
FILES = {
    "meta/manifest.json": json.dumps(MANIFEST).encode(),
    "pkg/fdio/meta.json": b"{}",
    "pkg/fdio/include/lib/fdio/fdio.h": b"/* header */",
    "arch/x64/lib/libfdio.so": b"x64 head lib",
    "arch/x64/debug/libfdio.so": b"x64 head debug",
    "arch/arm64/lib/libfdio.so": b"arm64 head lib",
    "arch/riscv64/lib/libfdio.so": b"riscv64 head lib",
    "arch/riscv64/sysroot/include/zircon/types.h": b"/* riscv64 sysroot header */",
    "arch/riscv64/sysroot/lib/libc.so": b"riscv64 sysroot lib",
    "obj/x64-api-27/lib/libfdio.so": b"x64 27",
    "obj/x64-api-NEXT/lib/libfdio.so": b"x64 NEXT",
    "obj/arm64-api-32/debug/libfdio.so": b"arm64 32",
    "obj/riscv64-api-30/lib/libfdio.so": b"riscv64 30",
    "tools/x64/cmc": b"x64 cmc",
    "tools/x64/cmc-meta.json": b"{}",
    "tools/arm64/cmc": b"arm64 cmc",
    "tools/arm64/cmc-meta.json": b"{}",
    "tools/qemu_uefi_internal/x64/OVMF_CODE.fd": b"firmware",
    "version_history.json": b"{}",
}
KEPT_WHEN_TRIMMED = {
    "meta/manifest.json",
    "pkg/fdio/meta.json",
    "pkg/fdio/include/lib/fdio/fdio.h",
    "arch/x64/lib/libfdio.so",
    "arch/x64/debug/libfdio.so",
    "arch/arm64/lib/libfdio.so",
    "arch/riscv64/sysroot/include/zircon/types.h",  # globbed by the generated SDK
    "arch/riscv64/sysroot/lib/libc.so",
    "tools/x64/cmc",
    "tools/x64/cmc-meta.json",
    "tools/arm64/cmc-meta.json",  # part metadata is always kept
    "tools/qemu_uefi_internal/x64/OVMF_CODE.fd",
    "version_history.json",
}


def make_archive(path: Path, files: dict[str, bytes], prefix: str = "") -> str:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            info.mode = 0o755 if name.startswith("tools/") and "." not in name else 0o644
            tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extracted(dest: Path) -> set[str]:
    return {
        p.relative_to(dest).as_posix()
        for p in dest.rglob("*")
        if p.is_file() and p.name != ie.REPORT_NAME
    }


@pytest.fixture
def idk(tmp_path):
    archive = tmp_path / "core.tar.gz"
    sha = make_archive(archive, FILES)
    dest = tmp_path / "out"
    dest.mkdir()
    return archive, sha, dest


def test_drop_reason_groups():
    assert it.drop_reason("obj/x64-api-27/lib/libfdio.so") == "obj/x64-api-27"
    assert it.drop_reason("obj/arm64-api-NEXT/lib/libfdio.so") == "obj/arm64-api-NEXT"
    assert it.drop_reason("arch/riscv64/lib/libfdio.so") == "arch/riscv64"
    assert it.drop_reason("arch/riscv64/debug/libfdio.so") == "arch/riscv64"
    assert it.drop_reason("tools/arm64/ffx") == "tools/arm64"
    assert it.drop_reason("tools/riscv64/ffx") == "tools/riscv64"


def test_drop_reason_keeps_what_the_build_uses():
    for name in (
        "arch/x64/sysroot/include/zircon/types.h",
        "arch/arm64/debug/libfdio.so",
        "arch/riscv64/sysroot/include/tar.h",
        "arch/riscv64/sysroot/lib/libc.so",
        "tools/x64/ffx",
        "tools/qemu_uefi_internal/x64/OVMF_CODE.fd",
        "pkg/fdio/meta.json",
        "meta/manifest.json",
        "tools/arm64/ffx-meta.json",
        "obj/x64-api-27/meta.json",
    ):
        assert it.drop_reason(name) is None, name


def test_drop_reason_keeps_unknown_layouts():
    # A layout the trim does not recognize is kept (more disk, never a missing file).
    assert it.drop_reason("obj/something-else/lib.so") is None
    assert it.drop_reason("obj/README") is None
    assert it.drop_reason("tools/mips/ffx") is None


def test_obj_kept_for_a_configured_level(monkeypatch):
    monkeypatch.setattr(it, "KEEP_API_LEVELS", ("HEAD", "27"))
    assert it.drop_reason("obj/x64-api-27/lib/libfdio.so") is None
    assert it.drop_reason("obj/riscv64-api-27/lib/libfdio.so") == "obj/riscv64-api-27"
    assert it.drop_reason("obj/x64-api-28/lib/libfdio.so") == "obj/x64-api-28"


def test_hosted_extracts_trimmed(idk):
    archive, sha, dest = idk
    report = ie.run(archive, sha, "hosted", dest)
    assert extracted(dest) == KEPT_WHEN_TRIMMED
    assert report["trimmed"] is True
    assert set(report["dropped"]) == {
        "arch/riscv64", "obj/x64-api-27", "obj/x64-api-NEXT", "obj/arm64-api-32",
        "obj/riscv64-api-30", "tools/arm64",
    }
    assert report["kept"]["files"] == len(KEPT_WHEN_TRIMMED)
    assert report["dropped"]["tools/arm64"] == {"files": 1, "bytes": len(b"arm64 cmc")}
    on_disk = json.loads((dest / ie.REPORT_NAME).read_text())
    assert on_disk == report and on_disk["archive_sha256"] == sha


def test_large_disk_extracts_everything(idk):
    archive, sha, dest = idk
    report = ie.run(archive, sha, "large-disk", dest)
    assert extracted(dest) == set(FILES)
    assert report["trimmed"] is False and report["dropped"] == {}


def test_contents_and_modes_preserved(idk):
    archive, sha, dest = idk
    ie.run(archive, sha, "hosted", dest)
    assert (dest / "arch/x64/lib/libfdio.so").read_bytes() == b"x64 head lib"
    assert (dest / "tools/x64/cmc").stat().st_mode & 0o111


def test_leading_dot_slash_members(tmp_path):
    archive = tmp_path / "core.tar.gz"
    sha = make_archive(archive, FILES, prefix="./")
    dest = tmp_path / "out"
    dest.mkdir()
    ie.run(archive, sha, "hosted", dest)
    assert extracted(dest) == KEPT_WHEN_TRIMMED


def test_tampered_archive_fails_before_extraction(idk):
    archive, sha, dest = idk
    data = bytearray(archive.read_bytes())
    data[len(data) // 2] ^= 0x01
    archive.write_bytes(bytes(data))
    for profile in ("hosted", "large-disk"):
        with pytest.raises(ie.ExtractError, match="SHA-256 .* expected " + sha):
            ie.run(archive, sha, profile, dest)
        assert list(dest.iterdir()) == []


def test_wrong_expected_hash_fails(idk):
    archive, _, dest = idk
    with pytest.raises(ie.ExtractError, match="nothing was extracted"):
        ie.run(archive, "0" * 64, "hosted", dest)
    assert list(dest.iterdir()) == []


def test_malformed_expected_hash_fails(idk):
    archive, sha, dest = idk
    with pytest.raises(ie.ExtractError, match="not 64 lowercase hex"):
        ie.run(archive, sha.upper(), "hosted", dest)


def test_missing_part_metadata_fails(tmp_path):
    files = dict(FILES)
    del files["tools/x64/cmc-meta.json"]
    archive = tmp_path / "core.tar.gz"
    sha = make_archive(archive, files)
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ie.ExtractError, match="part metadata .* tools/x64/cmc-meta.json"):
        ie.run(archive, sha, "hosted", dest)


def test_unsafe_member_rejected(tmp_path):
    archive = tmp_path / "core.tar.gz"
    sha = make_archive(archive, {"../escape": b"x", **FILES})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ie.ExtractError, match="unsafe member path"):
        ie.run(archive, sha, "hosted", dest)
    assert not (tmp_path / "escape").exists()


def test_cli_exit_codes(idk, capsys):
    archive, sha, dest = idk
    assert ie.main(["--archive", str(archive), "--sha256", "f" * 64, "--profile", "hosted",
                    "--dest", str(dest)]) == 1
    assert "SHA-256" in capsys.readouterr().err
    assert ie.main(["--archive", str(archive), "--sha256", sha, "--profile", "hosted",
                    "--dest", str(dest)]) == 0
    assert "profile hosted: kept" in capsys.readouterr().out


def test_constants_match_bazelrc():
    """The trim keeps exactly the API levels and CPUs the .bazelrc configs build."""
    rc = (ROOT / ".bazelrc").read_text()
    levels = set(re.findall(r"--(?:default|override)_fuchsia_api_level=(\S+)", rc))
    assert levels == set(it.KEEP_API_LEVELS)
    cpus = set(re.findall(r"^build:fuchsia_(\w+) --platforms=\S+:fuchsia_\1$", rc, re.M))
    assert cpus == set(it.KEEP_TARGET_CPUS)


@pytest.mark.parametrize("target", ["../../../../outside", "/etc/passwd"])
def test_symlink_escaping_dest_rejected(tmp_path, target):
    """Pins the tarfile "data" filter: a link out of the destination is refused.
    (From arch/x64/lib/, "../../outside" would still be inside; four levels leave it.)"""
    archive = tmp_path / "core.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("arch/x64/lib/evil")
        info.type = tarfile.SYMTYPE
        info.linkname = target
        tar.addfile(info)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(tarfile.FilterError):
        ie.run(archive, sha, "large-disk", dest)
    assert not any(p.is_symlink() for p in dest.rglob("*"))
