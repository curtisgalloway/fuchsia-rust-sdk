# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""The IDK trim spec: everything about the environment profile that @fuchsia_idk uses.

The `fuchsia_idk` repository rule (toolchain/repositories.bzl) watches this file and
scripts/idk_extract.py, and nothing else of the profile code, so editing
scripts/overlay_profile.py (budgets, descriptions, future fields such as KVM) does not
refetch the 3 GB IDK. Keep this file small and change it only when what the IDK
extraction does must change; every edit here refetches the IDK.

It holds:

- how the active profile's *name* is found (design C6; hosted is the default):
  1. the environment variable ``OVERLAY_PROFILE``;
  2. the file ``$XDG_CONFIG_HOME/fuchsia-rust-sdk/profile`` (``~/.config/...`` when
     ``XDG_CONFIG_HOME`` is unset): its first line that is not blank or a ``#`` comment;
  3. otherwise ``hosted``.
  An unknown name is an error rather than a silent fallback;
- whether each profile trims the IDK (``TRIM_BY_PROFILE``);
- what a trim drops (``drop_reason``).

``python3 idk_trim.py --json`` prints ``{"profile", "trim", "source"}`` for the
repository rule.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

ENV_VAR = "OVERLAY_PROFILE"
CONFIG_RELPATH = Path("fuchsia-rust-sdk") / "profile"
DEFAULT = "hosted"

# Profile name -> whether the IDK is extracted trimmed. overlay_profile.PROFILES holds
# the other fields of each profile and must name the same profiles (a test checks).
TRIM_BY_PROFILE: dict[str, bool] = {
    "hosted": True,
    "large-disk": False,
}

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

_OBJ_DIR = re.compile(r"(?P<cpu>[a-z0-9_]+)-api-(?P<level>[A-Za-z0-9_]+)")


class ProfileError(Exception):
    pass


def config_path(env: Mapping[str, str]) -> Path | None:
    """The profile file's path, or None when neither XDG_CONFIG_HOME nor HOME is set."""
    base = env.get("XDG_CONFIG_HOME") or (
        str(Path(env["HOME"]) / ".config") if env.get("HOME") else None
    )
    return Path(base) / CONFIG_RELPATH if base else None


def _read_config(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    raise ProfileError(f"{path}: no profile name in the file")


def _check(name: str, source: str) -> str:
    if name not in TRIM_BY_PROFILE:
        known = ", ".join(sorted(TRIM_BY_PROFILE))
        raise ProfileError(f"{source}: unknown profile {name!r} (known: {known})")
    return name


def resolve_name(env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Returns the active profile's name and where it came from."""
    env = os.environ if env is None else env
    name = env.get(ENV_VAR, "").strip()
    if name:
        return _check(name, f"${ENV_VAR}"), f"${ENV_VAR}"
    path = config_path(env)
    if path is not None:
        name = _read_config(path)
        if name is not None:
            return _check(name, str(path)), str(path)
    return DEFAULT, "default"


def drop_reason(name: str) -> str | None:
    """The trim group an IDK member belongs to, or None to keep it.

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", required=True,
                        help='print {"profile", "trim", "source"} as JSON')
    parser.parse_args(argv)
    try:
        name, source = resolve_name()
    except ProfileError as e:
        print(f"idk_trim: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"profile": name, "trim": TRIM_BY_PROFILE[name], "source": source},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
