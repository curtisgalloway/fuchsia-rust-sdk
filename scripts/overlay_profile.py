# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Environment profiles (design C6): the resource limits of the machine the work runs on.

The hosted profile (the Anthropic-hosted cloud container: about 30 GB of writable disk,
4 vCPU, no KVM) is the default. Another environment declares its profile by name in
``$OVERLAY_PROFILE`` or in ``~/.config/fuchsia-rust-sdk/profile``; the rules for finding
the name, and whether a profile trims the IDK, live in ``idk_trim.py``, because they are
the only part of the profile the IDK fetch depends on. This module adds everything
else, which may change without refetching the IDK:

- ``trim_idk``: from ``idk_trim.TRIM_BY_PROFILE`` (extract only what the overlay builds
  against; see ``idk_extract.py``);
- ``cache_idk_archive``: keep the 3 GB IDK tarball in Bazel's repository cache
  (``scripts/bazel`` and ``disk_report.py --prune`` remove it otherwise);
- ``budgets``: disk budgets in bytes for groups of disk-report buckets (None: no limit);
- ``emulator_accel``: ``auto`` (KVM when ``/dev/kvm`` is usable, else TCG), ``kvm`` or
  ``tcg`` for ``scripts/emu``; ``$OVERLAY_EMU_ACCEL`` overrides it (see ``emu_env.py``).

Run ``uv run scripts/overlay_profile.py [--json]`` to see the active profile.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

import idk_trim

ENV_VAR = idk_trim.ENV_VAR
DEFAULT = idk_trim.DEFAULT
ProfileError = idk_trim.ProfileError
config_path = idk_trim.config_path
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
    # How scripts/emu accelerates QEMU: auto, kvm or tcg (emu_env.choose_accel).
    emulator_accel: str = "auto"


PROFILES: dict[str, Profile] = {
    p.name: p
    for p in (
        Profile(
            name="hosted",
            description=(
                "Anthropic-hosted cloud container: ~30 GB disk, 4 vCPU, no KVM (design C6)"
            ),
            trim_idk=idk_trim.TRIM_BY_PROFILE["hosted"],
            cache_idk_archive=False,
            # C6: total <= 25 GB (5 GB headroom). The Bazel caches get 12 of them (M2a),
            # leaving the rest for the emulator (M3), the checkout and scratch.
            budgets={"total": 25 * GIB, "bazel": 12 * GIB},
            # The hosted container has no /dev/kvm; auto detects that and uses TCG, and
            # would use KVM if a hosted environment ever offered it.
            emulator_accel="auto",
        ),
        Profile(
            name="large-disk",
            description="declared environment with ample disk: no trim, caches kept",
            trim_idk=idk_trim.TRIM_BY_PROFILE["large-disk"],
            cache_idk_archive=True,
            budgets={"total": None, "bazel": None},
            emulator_accel="auto",
        ),
    )
}


def resolve(env: Mapping[str, str] | None = None) -> tuple[Profile, str]:
    """Returns the active profile and where it came from (for reports)."""
    name, source = idk_trim.resolve_name(env)
    return PROFILES[name], source


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
