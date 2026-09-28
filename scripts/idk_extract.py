# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Verify the release's IDK archive by SHA-256, then extract it, trimmed per the profile.

Run by the `fuchsia_idk` repository rule (toolchain/repositories.bzl) on the downloaded
core.tar.gz:

    idk_extract.py --archive core.tar.gz --sha256 <lock bazel_sdk.value> \\
        --profile hosted --dest <repository directory>

1. The SHA-256 of the whole archive must equal the lock's value (design C3). Nothing is
   written before this check passes.
2. Under a profile with ``trim_idk`` (the hosted default, design C6), members the
   overlay never builds against are not extracted (see ``drop_reason``). Under a
   profile without it, everything is extracted.
3. ``.overlay-idk-trim.json`` in the destination records the profile and what was kept
   and dropped, per group, in files and bytes.

What the trim keeps is tied to the build: ``.bazelrc`` targets API level HEAD, whose
prebuilts the generated @fuchsia_sdk takes from ``arch/<cpu>/`` (``obj/<cpu>-api-<N>/``
holds the other levels), for the ``fuchsia_x64`` and ``fuchsia_arm64`` configs, on a
linux-amd64 build host (C5). ``tests/test_idk_extract.py`` checks these constants
against ``.bazelrc``; ``scripts/check_sdk_files.py`` checks that every file the built
configurations can reach in @fuchsia_sdk exists after the trim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import overlay_profile

# Fuchsia target CPUs the overlay builds for (.bazelrc configs fuchsia_x64/fuchsia_arm64,
# design D4). Other target CPUs (riscv64) are dropped.
KEEP_TARGET_CPUS = ("x64", "arm64")
# API levels the configs target (.bazelrc --default/--override_fuchsia_api_level). HEAD
# prebuilts live in arch/<cpu>/; obj/<cpu>-api-<level>/ holds every other level.
KEEP_API_LEVELS = ("HEAD",)
# The build host's CPU in IDK naming (design C5: linux-amd64). tools/<cpu>/ for any other
# known CPU holds host tools for other build hosts.
HOST_CPU = "x64"
KNOWN_CPUS = ("x64", "arm64", "riscv64")

REPORT_NAME = ".overlay-idk-trim.json"
_OBJ_DIR = re.compile(r"(?P<cpu>[a-z0-9_]+)-api-(?P<level>[A-Za-z0-9_]+)")
_CHUNK = 1 << 20


class ExtractError(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def verify(path: Path, expected: str) -> None:
    """Fails unless the SHA-256 of the whole file equals `expected`."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ExtractError(f"expected SHA-256 {expected!r} is not 64 lowercase hex digits")
    actual = sha256_file(path)
    if actual != expected:
        raise ExtractError(
            f"{path.name}: SHA-256 {actual}, expected {expected} (overlay.lock.json "
            "bazel_sdk.value); nothing was extracted"
        )


def drop_reason(name: str) -> str | None:
    """The trim group a member belongs to, or None to keep it.

    Only three kinds of path are dropped; anything with another layout is kept, so a new
    IDK layout errs toward using more disk, never toward a missing file.
    """
    parts = PurePosixPath(name).parts
    # Atom metadata (`*-meta.json`, `meta.json`) is always kept: rules_fuchsia reads every
    # part's metadata from meta/manifest.json when it generates @fuchsia_sdk, including
    # parts for dropped CPUs (tools/arm64/cmc-meta.json, …). The files are small.
    if len(parts) < 3 or parts[-1].endswith("meta.json"):
        return None
    top, sub = parts[0], parts[1]
    if top == "obj":
        m = _OBJ_DIR.fullmatch(sub)
        if m and (m["cpu"] not in KEEP_TARGET_CPUS or m["level"] not in KEEP_API_LEVELS):
            return f"obj/{sub}"
    elif top == "arch":
        # The generated SDK's root BUILD file globs arch/<cpu>/sysroot/{include,lib}/**
        # for every target CPU in the IDK, and an empty glob fails the whole package. The
        # sysroot of a dropped CPU is therefore kept (riscv64: 26 MB of 597 MB).
        if sub not in KEEP_TARGET_CPUS and parts[2] != "sysroot":
            return f"arch/{sub}"
    elif top == "tools":
        if sub in KNOWN_CPUS and sub != HOST_CPU:
            return f"tools/{sub}"
    return None


def _member_name(member: tarfile.TarInfo) -> str:
    name = member.name
    while name.startswith("./"):
        name = name[2:]
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ExtractError(f"unsafe member path {member.name!r}")
    return name


def extract(
    archive: Path,
    dest: Path,
    drop: Callable[[str], str | None] | None,
) -> dict:
    """Extracts `archive` into `dest`, skipping members `drop` names a group for.

    Returns counts per group. `drop=None` extracts everything.
    """
    if not hasattr(tarfile, "data_filter"):
        raise ExtractError("this Python's tarfile has no extraction filters; need >= 3.11.4")
    kept = {"files": 0, "bytes": 0}
    dropped: dict[str, dict[str, int]] = {}
    # "r:gz", not the streaming "r|gz": streaming reads the 13 GB of content in 10 KB
    # blocks and took over 10 minutes on the real IDK. Members are still visited in
    # archive order, so each extract() only seeks forward.
    with tarfile.open(archive, mode="r:gz") as tar:
        for member in tar:
            name = _member_name(member)
            group = drop(name) if drop and not member.isdir() else None
            if group is not None:
                g = dropped.setdefault(group, {"files": 0, "bytes": 0})
                g["files"] += 1
                g["bytes"] += member.size
                continue
            # The "data" filter refuses links out of dest, device files and setuid bits.
            tar.extract(member, dest, filter="data")
            if not member.isdir():
                kept["files"] += 1
                kept["bytes"] += member.size
    return {"kept": kept, "dropped": dict(sorted(dropped.items()))}


def check_metadata(dest: Path) -> None:
    """Fails unless the manifest and every part's metadata file were extracted."""
    manifest = dest / "meta" / "manifest.json"
    if not manifest.is_file():
        raise ExtractError("meta/manifest.json missing after extraction")
    parts = json.loads(manifest.read_text(encoding="utf-8")).get("parts", [])
    missing = [p["meta"] for p in parts if not (dest / p["meta"]).is_file()]
    if missing:
        raise ExtractError(
            f"{len(missing)} part metadata file(s) from meta/manifest.json missing after "
            f"extraction, e.g. {missing[0]}"
        )


def run(archive: Path, sha256: str, profile_name: str, dest: Path) -> dict:
    profile = overlay_profile.PROFILES.get(profile_name)
    if profile is None:
        raise ExtractError(f"unknown profile {profile_name!r}")
    verify(archive, sha256)
    counts = extract(archive, dest, drop_reason if profile.trim_idk else None)
    check_metadata(dest)
    report = {
        "archive_sha256": sha256,
        "profile": profile.name,
        "trimmed": profile.trim_idk,
        "keep": {
            "target_cpus": list(KEEP_TARGET_CPUS),
            "api_levels": list(KEEP_API_LEVELS),
            "host_cpu": HOST_CPU,
        },
        **counts,
    }
    (dest / REPORT_NAME).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--profile", required=True, choices=sorted(overlay_profile.PROFILES))
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args.archive, args.sha256, args.profile, args.dest)
    except (ExtractError, tarfile.TarError, OSError) as e:
        print(f"idk_extract: {e}", file=sys.stderr)
        return 1
    dropped = sum(g["bytes"] for g in report["dropped"].values())
    print(
        f"idk_extract: profile {report['profile']}: kept {report['kept']['files']} files "
        f"({report['kept']['bytes'] / 1024**3:.2f} GiB), dropped "
        f"{sum(g['files'] for g in report['dropped'].values())} files "
        f"({dropped / 1024**3:.2f} GiB)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
