# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Environment profiles (design C6): the resource limits of the machine the work runs on.

The hosted profile (the Anthropic-hosted cloud container: about 30 GB of writable disk,
4 vCPU, no KVM) is the default. Another environment declares its profile in one of two
places, the first found wins:

1. the environment variable ``OVERLAY_PROFILE``;
2. the file ``$XDG_CONFIG_HOME/fuchsia-rust-sdk/profile`` (``~/.config/...`` when
   ``XDG_CONFIG_HOME`` is unset): the first line that is not blank or a ``#`` comment.

An unknown name is an error rather than a silent fallback to the default.

The profile decides the disk policy that the IDK fetch (``toolchain/repositories.bzl``
through ``scripts/idk_extract.py``) and ``scripts/disk_report.py`` apply:

- ``trim_idk``: extract only what the overlay builds against (see ``idk_extract.py``);
- ``cache_idk_archive``: keep the 3 GB IDK tarball in Bazel's repository cache;
- ``budgets``: disk budgets in bytes for groups of disk-report buckets (None: no limit).

Run ``uv run scripts/overlay_profile.py [--json]`` to see the active profile. The Bazel
repository rule runs it the same way with ``--json``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

ENV_VAR = "OVERLAY_PROFILE"
CONFIG_RELPATH = Path("fuchsia-rust-sdk") / "profile"
DEFAULT = "hosted"
GIB = 1024**3


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    trim_idk: bool
    cache_idk_archive: bool
    # Group name -> budget in bytes, or None for no limit. Groups are defined in
    # disk_report.GROUPS.
    budgets: Mapping[str, int | None] = field(default_factory=dict)


PROFILES: dict[str, Profile] = {
    p.name: p
    for p in (
        Profile(
            name="hosted",
            description=(
                "Anthropic-hosted cloud container: ~30 GB disk, 4 vCPU, no KVM (design C6)"
            ),
            trim_idk=True,
            cache_idk_archive=False,
            # C6: total <= 25 GB (5 GB headroom). The Bazel caches get 12 of them (M2a),
            # leaving the rest for the emulator (M3), the checkout and scratch.
            budgets={"total": 25 * GIB, "bazel": 12 * GIB},
        ),
        Profile(
            name="large-disk",
            description="declared environment with ample disk: no trim, caches kept",
            trim_idk=False,
            cache_idk_archive=True,
            budgets={"total": None, "bazel": None},
        ),
    )
}


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


def _lookup(name: str, source: str) -> Profile:
    if name not in PROFILES:
        known = ", ".join(sorted(PROFILES))
        raise ProfileError(f"{source}: unknown profile {name!r} (known: {known})")
    return PROFILES[name]


def resolve(env: Mapping[str, str] | None = None) -> tuple[Profile, str]:
    """Returns the active profile and where it came from (for reports)."""
    env = os.environ if env is None else env
    name = env.get(ENV_VAR, "").strip()
    if name:
        return _lookup(name, f"${ENV_VAR}"), f"${ENV_VAR}"
    path = config_path(env)
    if path is not None:
        name = _read_config(path)
        if name is not None:
            return _lookup(name, str(path)), str(path)
    return PROFILES[DEFAULT], "default"


def as_json(profile: Profile, source: str) -> str:
    return json.dumps({**asdict(profile), "budgets": dict(profile.budgets), "source": source},
                      sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print the profile as JSON")
    args = parser.parse_args(argv)
    try:
        profile, source = resolve()
    except ProfileError as e:
        print(f"overlay_profile: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(as_json(profile, source))
    else:
        print(f"{profile.name} ({source}): {profile.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
