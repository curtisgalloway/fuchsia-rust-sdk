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

then fails if

- any of those files is missing (a dangling symlink counts as missing); or
- cquery reports an error (loading or analysis) that `EXPECTED_ERRORS` does not
  explain, a target is skipped that no expected error names, or an expected error's
  target is skipped for no expected reason. A target that fails to load or analyze
  reaches no files at all, so an unexplained failure could hide a missing file (in the
  SDK's root package a label to a vanished file is "no such target", not a missing
  path); or
- cquery exits with a status other than 0 or 1 (1 is its status for errors under
  --keep_going, which the rules above judge).

    uv run scripts/check_sdk_files.py            # all three configurations
    uv run scripts/check_sdk_files.py --config fuchsia_x64

Exit status: 0 when the check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
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


@dataclass(frozen=True)
class ExpectedError:
    """A known cquery error under the Fuchsia configs: which skipped targets it explains,
    and the reason, as a regex over the error line after `normalize()`."""

    why: str
    targets: tuple[str, ...]
    reason: str

    def matches(self, line: str) -> bool:
        return re.search(self.reason, line) is not None


_PACKAGES = (
    "cmd-buf-benchmark-test",
    "fake-build-info",
    "heapdump-collector",
    "intl_property_manager",
    "realm_builder_server",
    "vkcopy-test",
    "vkext-test",
    "vkloop-test",
    "vkproto-driver-test",
    "vkreadback_test",
)

# All but the last fail on the untrimmed IDK too (reference cquery in M2a); the last is
# the trim's own doing.
EXPECTED_ERRORS: tuple[ExpectedError, ...] = (
    *(
        ExpectedError(
            why="prebuilt package: variants only for numbered API levels, none for HEAD",
            targets=(f"{SDK}//packages/{p}:{p}",),
            reason=(
                rf'configurable attribute "actual" in {re.escape(SDK)}//packages/'
                rf"{re.escape(p)}:{re.escape(p)} doesn't match this configuration"
            ),
        )
        for p in _PACKAGES
    ),
    ExpectedError(
        why="the generated root BUILD file names a package the SDK does not contain",
        targets=(f"{SDK}//:fuchsia_platform_sdk", f"{SDK}//:fuchsia_toolchain_version_sdk"),
        reason=rf"no such package '{re.escape(SDK)}//fuchsia/constraints'",
    ),
    ExpectedError(
        why="needs a Python toolchain the overlay does not register",
        targets=(f"{SDK}//python/rtc_conformance_test/unversioned:rtc_conformance_test",),
        reason=(
            r"While resolving toolchains for target "
            rf"{re.escape(SDK)}//python/rtc_conformance_test/unversioned:rtc_conformance_test"
        ),
    ),
    ExpectedError(
        why="trim: riscv64-only Vulkan layers, whose libraries the trim drops",
        targets=(f"{SDK}//pkg/vulkan_layers/riscv64:vulkan_layers",),
        reason=rf"no such target '{re.escape(SDK)}//:arch/riscv64/dist/VkLayer_\w+\.so'",
    ),
)

# Summary lines Bazel prints after the real errors.
_SUMMARY = re.compile(
    r"^ERROR: (command succeeded, but .*|Build did NOT complete successfully"
    r"|Analysis of target .* failed.*)$"
)
_SKIPPED = re.compile(
    r"errors encountered while analyzing target '([^']+)'|Skipping '([^']+)'"
)


@dataclass
class Result:
    config: str
    files: list[str]
    missing: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def query(scope: str) -> str:
    return f'kind("source file", deps({scope}))'


def parse_files(stdout: str) -> list[str]:
    """Paths printed by `cquery --output=files`, one per line, deduplicated and sorted."""
    return sorted({line.strip() for line in stdout.splitlines() if line.strip()})


def normalize(text: str, mapping: dict[str, str], output_base: Path | None = None) -> str:
    """Rewrites canonical repository names (`@@+ext+repo//`, `<output
    base>/external/+ext+repo/`) to apparent ones (`@repo//`, `@repo/`), so the expected
    errors do not depend on how Bazel spells the canonical name. `mapping` is the main
    repository's mapping (`bazel mod dump_repo_mapping ''`), apparent -> canonical."""
    for apparent, canonical in sorted(mapping.items(), key=lambda kv: -len(kv[1])):
        if not apparent or not canonical:
            continue
        if output_base is not None:
            text = text.replace(f"{output_base}/external/{canonical}/", f"@{apparent}/")
        text = text.replace(f"@@{canonical}//", f"@{apparent}//")
    return text


def judge(
    stderr: str, returncode: int, expected: tuple[ExpectedError, ...] = EXPECTED_ERRORS
) -> tuple[list[str], list[str]]:
    """Returns (skipped targets, problems) for normalized cquery stderr."""
    problems = []
    if returncode not in (0, 1):
        problems.append(f"cquery exited with status {returncode}")
    skipped = sorted({a or b for a, b in _SKIPPED.findall(stderr)})
    errors = [
        line for line in stderr.splitlines()
        if line.startswith("ERROR: ") and not _SUMMARY.match(line)
    ]
    matched: set[ExpectedError] = set()
    for line in errors:
        hits = [e for e in expected if e.matches(line)]
        if not hits:
            problems.append(f"unexpected error: {line}")
        matched.update(hits)
    explained = {t for e in expected for t in e.targets}
    for t in skipped:
        if t not in explained:
            problems.append(f"unexpected skipped target: {t}")
    for e in expected:
        for t in e.targets:
            if t in skipped and e not in matched:
                problems.append(f"{t} skipped, but not for the expected reason ({e.why})")
    if returncode == 1 and not errors:
        problems.append("cquery exited with status 1 but reported no error")
    return skipped, problems


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


def check(name: str, output_base: Path, mapping: dict[str, str]) -> Result:
    config, scope = CONFIGS[name]
    args = ["cquery", "--keep_going", "--output=files"]
    if config is not None:
        args.append(f"--config={config}")
    proc = _bazel([*args, query(scope)])
    files = parse_files(proc.stdout)
    if not files:
        raise SystemExit(f"check_sdk_files: {name}: cquery returned no files:\n{proc.stderr}")
    skipped, problems = judge(normalize(proc.stderr, mapping, output_base), proc.returncode)
    return Result(
        config=name,
        files=files,
        missing=find_missing(files, ROOT, output_base),
        skipped=skipped,
        problems=problems,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", action="append", choices=sorted(CONFIGS),
                        help="configuration to check (repeatable; default: all)")
    parser.add_argument("--list-errors", action="store_true",
                        help="also list the skipped targets that expected errors explain")
    args = parser.parse_args(argv)
    info = _bazel(["info", "output_base"])
    mapping_proc = _bazel(["mod", "dump_repo_mapping", ""])
    if info.returncode != 0 or mapping_proc.returncode != 0:
        print(f"check_sdk_files: bazel failed:\n{info.stderr}{mapping_proc.stderr}",
              file=sys.stderr)
        return 1
    output_base = Path(info.stdout.strip())
    mapping = json.loads(mapping_proc.stdout)
    sdk_dir = f"external/{mapping['fuchsia_sdk']}/"
    status = 0
    for name in args.config or list(CONFIGS):
        r = check(name, output_base, mapping)
        sdk = sum(1 for f in r.files if f.startswith(sdk_dir))
        print(f"{name}: {len(r.files)} source files reachable ({sdk} in {SDK}), "
              f"{len(r.missing)} missing, {len(r.skipped)} targets skipped, "
              f"{len(r.problems)} unexplained errors")
        for f in r.missing:
            print(f"  missing: {f}")
        for p in r.problems:
            print(f"  {p}")
        if args.list_errors:
            for t in r.skipped:
                print(f"  skipped: {t}")
        if r.missing or r.problems:
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
