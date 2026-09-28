# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Check that every source file the built configurations can reach exists on disk.

The hosted profile extracts a trimmed IDK (scripts/idk_extract.py). rules_fuchsia still
generates @fuchsia_sdk from the IDK's full metadata, so the trimmed files become dangling
symlinks there. A build that never reads such a file passes anyway, so "the build
passes" does not show that the trim is safe. This check does: for each configuration
the overlay builds, it asks Bazel (cquery, selects resolved) for every source file in
the transitive closure of

- `//...`, and
- for the Fuchsia configs, every target in `@fuchsia_sdk//...` except the ones that
  reach `@fuchsia_sdk//:all_files` (a `glob(["**/*"])` of the whole SDK, used only as
  runfiles of the `bazel run` wrappers `:ffx`, `:cmc` and `:funnel`) and the
  per-package glob filegroups `all_files` collects,

then fails if any of those files is missing (a dangling symlink counts as missing).

    uv run scripts/check_sdk_files.py            # all three configurations
    uv run scripts/check_sdk_files.py --config fuchsia_x64

Exit status: 0 when nothing is missing, 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAZEL = ROOT / "scripts" / "bazel"

SDK = "@fuchsia_sdk"
# Targets excluded from the SDK scope: everything that reaches the whole-SDK glob, and the
# per-package glob filegroups it collects. Neither is used by a build, only by `bazel run`.
SDK_SCOPE = (
    f"({SDK}//... - rdeps({SDK}//..., {SDK}//:all_files)"
    f' - attr(name, "^_EXPORT_SUBPACKAGE_FILEGROUP$", {SDK}//...))'
)
# config name -> the --config flag (None for the host) and the query scope.
CONFIGS: dict[str, tuple[str | None, str]] = {
    "fuchsia_x64": ("fuchsia_x64", f"//... + {SDK_SCOPE}"),
    "fuchsia_arm64": ("fuchsia_arm64", f"//... + {SDK_SCOPE}"),
    # The generated SDK's Fuchsia targets have no host branch; the host build is //...
    "host": (None, "//..."),
}


@dataclass
class Result:
    config: str
    files: list[str]
    missing: list[str] = field(default_factory=list)
    analysis_errors: list[str] = field(default_factory=list)


def query(scope: str) -> str:
    return f'kind("source file", deps({scope}))'


def parse_files(stdout: str) -> list[str]:
    """Paths printed by `cquery --output=files`, one per line, deduplicated and sorted."""
    return sorted({line.strip() for line in stdout.splitlines() if line.strip()})


_ERROR_TARGET = re.compile(r"errors encountered while analyzing target '([^']+)'")


def parse_analysis_errors(stderr: str) -> list[str]:
    """Targets --keep_going skipped because their analysis failed."""
    return sorted(set(_ERROR_TARGET.findall(stderr)))


def resolve(path: str, workspace: Path, output_base: Path) -> Path:
    """Where a cquery file path lives: `external/<repo>/…` under the output base, else
    relative to the workspace."""
    if path.startswith("external/"):
        return output_base / path
    return workspace / path


def find_missing(files: list[str], workspace: Path, output_base: Path) -> list[str]:
    # Path.exists() follows symlinks, so a dangling symlink is reported as missing.
    return [f for f in files if not resolve(f, workspace, output_base).exists()]


def _bazel(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BAZEL), *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def check(name: str, output_base: Path) -> Result:
    config, scope = CONFIGS[name]
    args = ["cquery", "--keep_going", "--output=files"]
    if config is not None:
        args.append(f"--config={config}")
    proc = _bazel([*args, query(scope)])
    files = parse_files(proc.stdout)
    if not files:
        raise SystemExit(f"check_sdk_files: {name}: cquery returned no files:\n{proc.stderr}")
    return Result(
        config=name,
        files=files,
        missing=find_missing(files, ROOT, output_base),
        analysis_errors=parse_analysis_errors(proc.stderr),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", action="append", choices=sorted(CONFIGS),
                        help="configuration to check (repeatable; default: all)")
    parser.add_argument("--list-errors", action="store_true",
                        help="also list targets whose analysis failed (skipped by --keep_going)")
    args = parser.parse_args(argv)
    info = _bazel(["info", "output_base"])
    if info.returncode != 0:
        print(f"check_sdk_files: bazel info failed:\n{info.stderr}", file=sys.stderr)
        return 1
    output_base = Path(info.stdout.strip())
    status = 0
    for name in args.config or list(CONFIGS):
        r = check(name, output_base)
        sdk = sum(1 for f in r.files if f.startswith("external/+fuchsia_repos+fuchsia_sdk/"))
        print(f"{name}: {len(r.files)} source files reachable ({sdk} in {SDK}), "
              f"{len(r.missing)} missing, {len(r.analysis_errors)} targets not analyzable")
        for f in r.missing:
            print(f"  missing: {f}")
        if args.list_errors:
            for t in r.analysis_errors:
                print(f"  not analyzable: {t}")
        if r.missing:
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
