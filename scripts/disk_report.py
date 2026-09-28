# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Disk use per bucket against the active environment profile's budget (design C6).

    uv run scripts/disk_report.py [--json] [--scratch DIR ...]
    uv run scripts/disk_report.py --prune     # hosted profile: drop the cached IDK tarball

Buckets (a bucket with no directory on this machine counts as 0):

- `output_base`: this checkout's Bazel output base (`bazel info output_base`);
- `repository_cache`: Bazel's download cache (`bazel info repository_cache`);
- `bazel_install`: Bazel's install bases and the `scripts/bazel` binary cache;
- `emulator`: emulator state and product bundles, from `$OVERLAY_EMULATOR_DIR`
  (set up in M3);
- `scratch`: directories given with `--scratch` or `$OVERLAY_SCRATCH` (`:`-separated);
- `checkout`: this repository (including `.git`; the `bazel-*` symlinks are not
  followed).

Groups, which the profile budgets (overlay_profile.PROFILES): `bazel` =
`output_base` + `repository_cache`; `total` = every bucket. Sizes are allocated blocks
(like `du`), each inode counted once. Exits 1 when a group is over budget.

`--prune` applies the repository-cache policy: under a profile that does not cache the
IDK archive (hosted), it deletes the lock's 3 GB IDK tarball from Bazel's repository
cache, where Bazel puts every download; under any other profile it does nothing.
`scripts/bazel` applies the same policy (`--prune-cache`) after each command that can
fetch, so the tarball never outlives the fetch. The cost: a refetch of the IDK
downloads it again.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import overlay_profile

ROOT = Path(__file__).resolve().parent.parent
BAZEL = ROOT / "scripts" / "bazel"
LOCK = ROOT / "overlay.lock.json"
GIB = overlay_profile.GIB

BUCKETS = ("output_base", "repository_cache", "bazel_install", "emulator", "scratch", "checkout")
GROUPS: dict[str, tuple[str, ...]] = {
    "bazel": ("output_base", "repository_cache"),
    "total": BUCKETS,
}


@dataclass(frozen=True)
class GroupStatus:
    name: str
    used: int
    budget: int | None

    @property
    def over(self) -> bool:
        return self.budget is not None and self.used > self.budget


def tree_size(paths: Iterable[Path], seen: set[tuple[int, int]]) -> int:
    """Allocated bytes under `paths`, not following symlinks, skipping inodes in `seen`."""
    total = 0
    stack = [p for p in paths]
    while stack:
        path = stack.pop()
        try:
            st = path.lstat()
        except FileNotFoundError:
            continue
        key = (st.st_dev, st.st_ino)
        if key in seen:
            continue
        seen.add(key)
        total += st.st_blocks * 512
        if path.is_dir() and not path.is_symlink():
            try:
                stack.extend(Path(e.path) for e in os.scandir(path))
            except PermissionError:
                continue
    return total


def bucket_paths(
    info: Mapping[str, str], env: Mapping[str, str], scratch: list[str]
) -> dict[str, list[Path]]:
    """Directories per bucket. `info` holds `bazel info` keys (output_base,
    repository_cache, install_base)."""
    cache_home = env.get("XDG_CACHE_HOME") or str(Path(env.get("HOME", "/")) / ".cache")
    install = [Path(info["install_base"]).parent] if info.get("install_base") else []
    scratch_dirs = list(scratch) + [d for d in env.get("OVERLAY_SCRATCH", "").split(":") if d]
    emulator = env.get("OVERLAY_EMULATOR_DIR")
    return {
        "output_base": [Path(info["output_base"])] if info.get("output_base") else [],
        "repository_cache": [Path(info["repository_cache"])] if info.get("repository_cache") else [],
        "bazel_install": install + [Path(cache_home) / "fuchsia-rust-sdk" / "bazel"],
        "emulator": [Path(emulator)] if emulator else [],
        "scratch": [Path(d) for d in scratch_dirs],
        "checkout": [ROOT],
    }


def measure(paths: Mapping[str, list[Path]]) -> dict[str, int]:
    # Buckets are measured in order with one shared inode set, so a file reachable from
    # two buckets (a hard link, a nested directory) is counted once, in the first.
    seen: set[tuple[int, int]] = set()
    return {b: tree_size(paths.get(b, []), seen) for b in BUCKETS}


def evaluate(sizes: Mapping[str, int], profile: overlay_profile.Profile) -> list[GroupStatus]:
    return [
        GroupStatus(g, sum(sizes[b] for b in members), profile.budgets.get(g))
        for g, members in GROUPS.items()
    ]


def idk_cache_entry(repository_cache: Path, sha256: str) -> Path:
    """Where Bazel's repository cache keeps a download with this SHA-256."""
    return repository_cache / "content_addressable" / "sha256" / sha256


def prune(repository_cache: Path, sha256: str, profile: overlay_profile.Profile) -> str:
    """Applies the profile's IDK cache policy to an existing repository cache."""
    if profile.cache_idk_archive:
        return f"prune: skipped; the {profile.name} profile keeps the IDK archive cached"
    entry = idk_cache_entry(repository_cache, sha256)
    if not entry.exists():
        return "prune: the IDK archive is not in the repository cache"
    shutil.rmtree(entry)
    return f"prune: removed the IDK archive from the repository cache ({entry})"


def _gib(n: int | None) -> str:
    return "none" if n is None else f"{n / GIB:.2f} GiB"


def bazel_info() -> dict[str, str]:
    keys = ["output_base", "repository_cache", "install_base"]
    proc = subprocess.run(
        [str(BAZEL), "info", *keys], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(f"disk_report: bazel info failed:\n{proc.stderr}")
    info = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(": ")
        info[key.strip()] = value.strip()
    return info


def render(
    profile: overlay_profile.Profile,
    source: str,
    paths: Mapping[str, list[Path]],
    sizes: Mapping[str, int],
    groups: list[GroupStatus],
) -> str:
    lines = [f"profile: {profile.name} ({source})", ""]
    lines.append(f"{'bucket':<18} {'size':>11}  directories")
    for b in BUCKETS:
        dirs = ", ".join(str(p) for p in paths.get(b, []) if p.exists()) or "(none)"
        lines.append(f"{b:<18} {_gib(sizes[b]):>11}  {dirs}")
    lines.append("")
    lines.append(f"{'group':<18} {'used':>11} {'budget':>11}  status")
    for g in groups:
        status = "OVER BUDGET" if g.over else ("ok" if g.budget is not None else "no budget")
        lines.append(f"{g.name:<18} {_gib(g.used):>11} {_gib(g.budget):>11}  {status}")
    free = shutil.disk_usage(ROOT).free
    lines.append("")
    lines.append(f"free on the checkout's filesystem: {_gib(free)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--scratch", action="append", default=[], metavar="DIR",
                        help="a scratch directory to count (repeatable)")
    parser.add_argument("--prune", action="store_true",
                        help="apply the profile's repository-cache policy, then report")
    parser.add_argument("--prune-cache", metavar="REPOSITORY_CACHE",
                        help="only apply the policy to this repository cache, quietly "
                        "(run by scripts/bazel after commands that can fetch)")
    args = parser.parse_args(argv)
    try:
        profile, source = overlay_profile.resolve()
    except overlay_profile.ProfileError as e:
        print(f"disk_report: {e}", file=sys.stderr)
        return 1
    if args.prune_cache:
        sha256 = json.loads(LOCK.read_text())["bazel_sdk"]["value"]
        msg = prune(Path(args.prune_cache), sha256, profile)
        if "removed" in msg:
            print(f"scripts/bazel: {profile.name} profile: {msg}", file=sys.stderr)
        return 0
    info = bazel_info()
    if args.prune:
        sha256 = json.loads(LOCK.read_text())["bazel_sdk"]["value"]
        print(prune(Path(info["repository_cache"]), sha256, profile), file=sys.stderr)
    paths = bucket_paths(info, os.environ, args.scratch)
    sizes = measure(paths)
    groups = evaluate(sizes, profile)
    if args.json:
        print(json.dumps({
            "profile": profile.name,
            "source": source,
            "buckets": {b: {"bytes": sizes[b], "paths": [str(p) for p in paths[b]]}
                        for b in BUCKETS},
            "groups": {g.name: {"bytes": g.used, "budget": g.budget, "over": g.over}
                       for g in groups},
        }, indent=2, sort_keys=True))
    else:
        print(render(profile, source, paths, sizes, groups))
    return 1 if any(g.over for g in groups) else 0


if __name__ == "__main__":
    sys.exit(main())
