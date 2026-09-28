<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M2a — Fit the hosted disk budget evidence

Design: [design](../design.md), revision "2026-09-27, draft 1", amended 2026-09-27 (C6,
C3, C5; §4.2 "Toolchain")
Notebook: [M2a chapter](../notebook/M2a.md)
Starting revision and pre-existing changes: `aaf53b7` (origin/main: I1, M1, M2 and the
design/plan amendment), branch `ms/M2a`; working tree clean. Crash-insurance commits:
`695841e` and `56dd031` (`wip: M2a — …`, reviewed); the checkpoint commit
`overlay: M2a — Fit the hosted disk budget` follows them and carries the review fixes.

## Milestone definition (moved from the plan)

**Design coverage:** C6. **Dependencies:** M2.
**Why:** M2 measured the Bazel output base at 16 GB (extracted IDK 13 GB, of which
`obj/` 8.3 GB) plus a 3.8 GB repository cache, leaving 9 GB of the hosted profile's 30.
**In scope:**
- Extract only what the overlay builds against from the pinned IDK: the API level(s)
  the configs use (HEAD) and the x64/arm64 architectures, dropping other API levels'
  prebuilts and riscv64. The archive stays pinned and verified by SHA-256 before any
  trim.
- A repository-cache policy (clear or bound it after fetching).
- `scripts/disk_report` (proposed): disk use per bucket (output base, repository
  cache, emulator state, scratch) against the active profile's budget.
- Profile detection and declaration (hosted by default; a declared large-disk profile
  skips the trim and keeps caches).

**Out of scope:** emulator assets (M3 measures them with the same report).

### Acceptance criteria
- [x] A tampered IDK archive still fails its SHA-256 check; the trim runs only after
  verification.
- [x] From a clean output base, `//...` builds under `fuchsia_x64`, `fuchsia_arm64`
  and host.
- [x] Output base plus repository cache ≤ 12 GB under the hosted profile, shown by
  the disk report.
- [x] Under a declared large-disk profile, trim and cache clearing are skipped
  (covered by the script's unit tests, not a second full build).
- [x] `uv run pytest` and `uv run reuse lint` pass.

### Testing and review
- Review focus: the trim cannot hide a missing file the generated SDK needs (a build
  that never references it passes anyway); the SHA-256 check still covers the whole
  archive; profile logic.
- Review method: inherit (a reviewer subagent with fresh context).

### Session sizing
One session. The main risk is that `rules_fuchsia`'s generated SDK references other API
levels' prebuilts. Split point: the trim and measurement first, then the profile and
cache policy. (The whole milestone fit; the split point was not needed.)

## Owner direction this milestone rests on

2026-09-27, relayed by the orchestrator: the work must fit the Anthropic-hosted
environment so it can run there; the limit is a property of the environment profile,
and other environments (self-hosted, more disk, KVM) may relax it. Budget for the
hosted profile: total ≤ 25 GB; M2a's target: output base + repository cache ≤ 12 GB.
(Design C6.)

## What was built

| File | Purpose |
|---|---|
| `scripts/idk_trim.py` | the IDK trim spec, the only profile code `@fuchsia_idk` depends on: profile-name resolution (`$OVERLAY_PROFILE`, then `$XDG_CONFIG_HOME/fuchsia-rust-sdk/profile` or `~/.config/…`, then `hosted`), profile → trim on/off, `drop_reason`; `--json` for the repository rule |
| `scripts/overlay_profile.py` | the profiles' other fields (`cache_idk_archive`, budgets, description); editing it does not refetch the IDK |
| `scripts/idk_extract.py` | SHA-256 of the whole archive, then extraction (trimmed under `trim_idk`), part-metadata check, `.overlay-idk-trim.json` report |
| `toolchain/repositories.bzl` | `idk_repository`: resolves the profile with `idk_trim.py --json` (reads the variables with `rctx.getenv`; watches the profile file, `idk_trim.py` and `idk_extract.py`), `rctx.download` with `sha256`, runs `idk_extract.py`, deletes the tarball |
| `scripts/bazel` | after `build`/`test`/`run`/`fetch`/`query`/`cquery`/`aquery`/…: `disk_report.py --prune-cache <repository_cache>` (skip with `OVERLAY_NO_PRUNE=1`) |
| `scripts/disk_report.py` | buckets `output_base`, `repository_cache`, `bazel_install`, `emulator` (`$OVERLAY_EMULATOR_DIR`, for M3), `scratch`, `uv_cache`, `checkout` (with a worktree's shared `.git`); groups `bazel` and `total` against the profile's budgets; exit 1 when over; `--prune`, `--prune-cache`, `--json` |
| `scripts/check_sdk_files.py` | per config, every source file reachable from `//...` and the SDK's targets exists; every cquery error, skipped target and exit status is explained by `EXPECTED_ERRORS` (target and reason) |
| `tests/test_overlay_profile.py`, `tests/test_idk_extract.py`, `tests/test_disk_report.py` | 60 new tests (75 → 135) |
| `README.md` | "Disk and environment profiles" |
| `docs/implementation-plan.md` | two project checks (SDK files present, disk budget) |

## Decisions (each has a notebook entry)

- **What the hosted trim drops** (`idk_trim.drop_reason`): `obj/<cpu>-api-<level>/`
  unless the CPU is x64/arm64 and the level is in `KEEP_API_LEVELS` (only `HEAD`, whose
  prebuilts the generated SDK takes from `arch/<cpu>/`, so all of `obj/`); `arch/riscv64/`
  except its `sysroot/`; and `tools/arm64/` (host tools for arm64 build hosts; C5 says
  linux-amd64). Always kept: every `*meta.json`, and any path whose layout the rules do
  not recognize (a new layout costs disk, never a file). A pytest checks
  `KEEP_API_LEVELS` and the target CPUs against `.bazelrc`.
- **Keep the sysroot of a dropped CPU.** The generated root `BUILD.bazel` globs
  `arch/<cpu>/sysroot/{include,lib}/**` for every IDK target CPU, and an empty glob
  fails the whole package (first clean build, notebook 19:56). 26 MB.
- **Keep part metadata.** rules_fuchsia reads every `parts[].meta` in
  `meta/manifest.json`, including `tools/arm64/*-meta.json` (notebook 19:52);
  `idk_extract.py` fails if any is missing after extraction.
- **Extraction in Python, run by the repository rule.** Bazel's `extract` has no member
  filter. `python3` ≥ 3.11 on `PATH` is now needed to fetch the IDK (the scripts already
  need it). `tarfile` mode `r:gz`; streaming `r|gz` took over 10 minutes (dead end).
- **Cache policy = prune after fetching.** Bazel 8.5.1 writes every download to the
  repository cache under its SHA-256, even without a `sha256` argument (notebook 19:55),
  so there is no fetch-time way to keep the 3 GB tarball out. `rctx.download` therefore
  always gets `sha256` (Bazel rejects a wrong archive before writing it), and
  `scripts/bazel` removes the lock's content-addressed entry afterwards when the profile
  has `cache_idk_archive = False`. Only that entry: clang and Rust zips (0.9 GB) stay.
- **Profile declaration.** Env var first, then a per-machine file (the profile belongs
  to the environment, not the checkout), then `hosted`. Unknown names fail; there is no
  auto-detection (the owner's rule is "hosted unless declared"). Budgets are GiB:
  `hosted` total 25, `bazel` 12; `large-disk` none.
- **Profile changes refetch the IDK; profile *code* changes mostly do not** (review
  finding 3). The repository rule reads the profile inputs through `rctx.getenv` and
  `rctx.watch`, and of the profile code watches only `idk_trim.py` (name resolution,
  profile → trim, `drop_reason`) and `idk_extract.py`. Budgets and future fields (M3's
  KVM) live in `overlay_profile.py`, which neither imports (a pytest checks). Adding a
  profile name does touch `idk_trim.py` and so refetches. The extension still returns
  `reproducible = True`; `MODULE.bazel.lock` did not change.
- **Prune refuses bad input** (review finding 1): the lock hash must be 64 lowercase hex
  digits and the entry must resolve inside `content_addressable/sha256/`; otherwise
  nothing is deleted and `scripts/bazel` warns.

## Verification

All commands from the repo root.

### Disk, before and after

"Before" is the M2 state this milestone started from (opening entry); "after" is
`disk_report.py` after the final clean-state build, which ran after the review fixes
(below). `du -h` and the report both use 1024-based units.

| Item | Before (M2) | After (M2a, hosted) |
|---|---|---|
| Output base | 16 GB | 6.75 GiB |
| — `fuchsia_idk` (extracted IDK) | 13 GB (`obj/` 8.3 GB) | 3.6 GB |
| — `fuchsia_clang` | 1.9 GB | 1.9 GB |
| — `fuchsia_rust_toolchain` | 1.1 GB | 1.1 GB |
| Repository cache | 3.8 GB (IDK tarball 3.0 GB) | 0.94 GiB (no IDK tarball) |
| **Output base + repository cache** (budget 12 GiB) | **~20 GB** | **7.69 GiB** |
| Bazel install base + `scripts/bazel` cache | 193 MB + 62 MB | 0.25 GiB |
| uv cache | (not counted) | 0.26 GiB |
| Checkout (with the main clone's `.git`); scratch | — | 0.01 GiB; 4 MB |
| **Total** (budget 25 GiB) | ~20 GB | **8.21 GiB** |
| Peak during a fresh IDK fetch (`df`, 1 s samples, above an empty-cache baseline) | not measured | 10.81 GiB (7.57 GiB after the build) |
| Free on `/` | 9.2 GB | 21.2 GiB |

The extraction report of the final build (`.overlay-idk-trim.json` in `@fuchsia_idk`,
profile `hosted`) kept 4,427 files (3.50 GiB) and dropped 5,902 (9.28 GiB): the 21
`obj/*-api-*` directories, `arch/riscv64` except its sysroot (42 files, 572 MB) and
`tools/arm64` except its metadata (71 files, 500 MB). Out of Bazel, extraction of the
real archive took 48 s and its SHA-256 2.7 s.

`uv run scripts/disk_report.py --scratch <scratch dir>` (exit 0):

```
profile: hosted (default)

bucket                    size  directories
output_base           6.75 GiB  <user cache>/bazel/_bazel_root/7d0c41cc…
repository_cache      0.94 GiB  <user cache>/bazel/_bazel_root/cache/repos/v1
bazel_install         0.25 GiB  <user cache>/bazel/_bazel_root/install, <user cache>/fuchsia-rust-sdk/bazel
emulator              0.00 GiB  (none)
scratch               0.00 GiB  <scratch dir>
uv_cache              0.26 GiB  <user cache>/uv
checkout              0.01 GiB  <checkout>, <main clone>/.git

group                     used      budget  status
bazel                 7.69 GiB   12.00 GiB  ok
total                 8.21 GiB   25.00 GiB  ok

free on the checkout's filesystem: 21.17 GiB
```

### Acceptance criteria

1. **Tampered archive fails before any trim.**
   - Live: lock `bazel_sdk.value` last digit `6`→`7`, then
     `scripts/bazel build --config=fuchsia_x64 //examples/hello_rust`: exit 2 after 41 s,
     `Error in download: … Checksum was 043104ba…a5078f6 but wanted 043104ba…a5078f7`,
     raised by `rctx.download` before `idk_extract.py` runs; the `fuchsia_idk` directory
     did not exist afterwards. Lock restored (`git diff --exit-code overlay.lock.json`).
   - Unit (`tests/test_idk_extract.py`): one flipped byte in the middle of the archive
     fails with `SHA-256 … expected …` under both profiles, and the destination stays
     empty; a wrong or malformed expected hash fails likewise. Hashing covers the whole
     file (`sha256_file` reads to EOF) before `tarfile` opens it.
2. **Clean output base, three configs.** `scripts/bazel clean --expunge` and the
   repository cache directory deleted (4 KB left, 29 GB free), then:

   | Command | Result |
   |---|---|
   | `scripts/bazel build --lockfile_mode=error --config=fuchsia_x64 //...` | exit 0, 162 s (all fetches) |
   | `scripts/bazel build --lockfile_mode=error --config=fuchsia_arm64 //...` | exit 0, 2 s |
   | `scripts/bazel build --lockfile_mode=error //...` | exit 0, 1 s |

   `MODULE.bazel.lock` unchanged. After the x64 build `scripts/bazel` printed
   `hosted profile: prune: removed the IDK archive from the repository cache (…/sha256/043104ba…)`.
   Rebuilt the same way after the tamper test (116 s / 1 s / 1 s) and after the
   profile test (107 s / 1 s / 0 s). **After the review fixes**, expunged and cleared
   the repository cache again: 167 s / 2 s / 1 s, all exit 0, lock unchanged, one prune.
3. **≤ 12 GB, shown by the disk report:** `bazel` group 7.69 GiB of 12 (report above).
4. **Large-disk skips trim and cache clearing (unit tests):**
   `test_large_disk_skips_trim_and_keeps_caches` (profile flags),
   `test_large_disk_extracts_everything` (every member extracted, `dropped` empty),
   `test_prune_large_disk_is_skipped` (cache entry kept),
   `test_env_var_selects_profile`, `test_file_under_home_config`,
   `test_xdg_config_home_wins_over_home`, `test_trim_spec_cli_is_what_the_repository_rule_reads`,
   `test_profiles_and_trim_spec_agree`.
   Live, that the repository rule sees the profile: `OVERLAY_PROFILE=bogus scripts/bazel
   build …` re-ran the `fuchsia_idk` fetch and failed with `overlay_profile:
   $OVERLAY_PROFILE: unknown profile 'bogus' (known: hosted, large-disk)` (before the
   review restructuring; the same check now lives in `idk_trim.py`).
   Live, that general profile edits do not refetch (after the fixes): changing the
   hosted `bazel` budget and appending a comment to `overlay_profile.py`, then
   `scripts/bazel build --lockfile_mode=error --config=fuchsia_x64 //...`: 2 s; the
   `@+lock_repos+fuchsia_idk.marker` and `.overlay-idk-trim.json` mtimes unchanged, no IDK
   fetch in the log. Reverted.
5. **`uv run pytest`:** 135 passed. **`uv run reuse lint`:** compliant (REUSE 3.3).

### The trim hides no file the build can reach

`uv run scripts/check_sdk_files.py` (exit 0), on the final build after the review fixes:

```
fuchsia_x64: 8532 source files reachable (3749 in @fuchsia_sdk), 0 missing, 14 targets skipped, 0 unexplained errors
fuchsia_arm64: 8555 source files reachable (3749 in @fuchsia_sdk), 0 missing, 14 targets skipped, 0 unexplained errors
host: 90 source files reachable (0 in @fuchsia_sdk), 0 missing, 0 targets skipped, 0 unexplained errors
```

Scope per Fuchsia config: `//...` plus every `@fuchsia_sdk` target except those reaching
`:all_files` (`:all_files`, `:ffx`, `:cmc`, `:funnel`) and the per-package
`_EXPORT_SUBPACKAGE_FILEGROUP` globs. So it covers SDK libraries the overlay does not
use yet, not only what `//...` builds today.

- **A dangling symlink is missing** (`Path.exists` follows links; unit test).
- **A target that fails analysis reaches no files, so it could hide one.** Negative test:
  moving `arch/x64/lib/libfdio.so` out of the extracted IDK gave `0 missing` but 37
  unexpected analysis failures (`pkg/fdio:fdio`, `//examples/hello_rust`, …), exit 1.
  In the SDK's root package, a label to a file that does not exist is `no such target`.
  The check therefore judges all of cquery's diagnostics against `EXPECTED_ERRORS`
  (after review finding 2 and the nit): every `ERROR:` line (loading or analysis) must
  match an expected reason, every skipped target (`errors encountered while analyzing
  target`, `Skipping '…'`) must be named by an expected entry, an expected target must
  be skipped for its own reason, and the exit status must be 0 or 1. Labels are
  compared in apparent form (`@fuchsia_sdk//…`, from `bazel mod dump_repo_mapping ''`),
  not the canonical `@@+fuchsia_repos+fuchsia_sdk`. The 14 skipped targets: 13 fail on
  the untrimmed IDK too (the reference cquery at the start listed exactly those: 10
  prebuilt packages with variants only for numbered API levels;
  `:fuchsia_platform_sdk` and `:fuchsia_toolchain_version_sdk`, from the loading error
  `no such package '@fuchsia_sdk//fuchsia/constraints'`; `rtc_conformance_test`, no
  Python toolchain). The 14th, `pkg/vulkan_layers/riscv64:vulkan_layers`, is the
  trim's: `no such target '@fuchsia_sdk//:arch/riscv64/dist/VkLayer_*.so'`. Unit tests
  cover an unexpected failure, an expected target failing for another reason, a loading
  error, and exit statuses 1 (with no error) and 2.
- **Selects:** under a config, cquery resolves every `variant_select` to the HEAD arm
  (`arch/<cpu>/…`); `obj/…` appears only in non-HEAD arms. Another API level would need
  `KEEP_API_LEVELS` changed, which a pytest ties to `.bazelrc`.
- **The `bazel run` wrappers still build:** `scripts/bazel build --config=fuchsia_x64
  @fuchsia_sdk//:ffx` succeeds. Globs skip dangling symlinks, so `:all_files` just omits
  the trimmed files.

## Deviations from the plan text

- **`tools/arm64/` is also dropped** (500 MB), beyond "other API levels and riscv64".
  Reason: those are host tools for arm64 build hosts, and C5 fixes the host as
  linux-amd64. Their `*-meta.json` files stay.
- **`arch/riscv64/sysroot/` is kept** (26 MB); see Decisions.
- **Cache policy is a prune, not a fetch-time exclusion**, and it runs automatically in
  `scripts/bazel` (Decisions). Commands run with a bare `bazel` do not prune;
  `disk_report.py --prune` does it by hand.
- **Name:** `scripts/disk_report.py` (the plan proposed `scripts/disk_report`), matching
  `resolve_pins.py`. Two more scripts than planned: `scripts/check_sdk_files.py`, and
  (after review finding 3) `scripts/idk_trim.py`.
- **Fetching the IDK now needs `python3` ≥ 3.11** on `PATH`.

## For M3

- Add the emulator's state directory as `$OVERLAY_EMULATOR_DIR` (or change
  `disk_report.bucket_paths`); the `emulator` bucket already counts toward `total`.
- The hosted headroom after M2a: 25 − 8.21 ≈ 17 GiB for the emulator, product bundle
  and scratch (plan Risks estimated about 15 GB for `fuchsia-cloud-dev`'s cache).
  Measure the peak during M3's first fresh fetch too: the IDK fetch alone peaks at about
  10.8 GiB (below).
- `ffx` is `@fuchsia_idk//tools/x64/ffx` (kept; the reviewer ran `ffx sdk version`
  against the trimmed IDK: `33.20260927.4.1`); `fuchsia-cloud-dev`'s `dev` runs
  `<sdk>/tools/x64/ffx` directly, which the trim does not affect. `tools/x64/` is kept
  whole.
- A KVM field (M3's acceptance asks for KVM detection) belongs in
  `scripts/overlay_profile.py`, not `idk_trim.py`: fields there do not refetch the IDK.

## Review

**Method:** a reviewer subagent with fresh context, launched by the orchestrator, per
the plan's conventions. It read the design, the milestone entry, this evidence and the
diff of `695841e` and `56dd031` against `aaf53b7`, and modified nothing. It ran
**before the checkpoint commit.** The orchestrator relayed its findings with a decision
for each; this list is the artifact.

**What the reviewer re-verified independently:** all five acceptance criteria
(`disk_report.py`: bazel 7.71/12, total 7.98/25 GiB, and `du` agrees). It resolved every
path in every part's metadata against the trimmed IDK: 5,963 missing, all under
`obj/*-api-*`, `tools/arm64` or `arch/riscv64`; `tools/x64` (including `bindc`, `cmc`,
`configc`, `fidlc`, `ffx`, `qemu_internal`, `zbi`) and `version_history.json` are kept.
It ran `ffx sdk version` against the trimmed IDK (`33.20260927.4.1`). It confirmed that
the 13 known analysis failures do not depend on the trim, and it checked the
`filter="data"` extraction and the member-path checks.
**Verdict: land after fixes; no blocker or major finding.**

| # | Severity | Finding | Resolution (decided by orchestrator) |
|---|---|---|---|
| 1 | minor | `prune()` builds `…/content_addressable/sha256/<lock value>` from an unvalidated lock value and runs even after Bazel failed on a malformed lock: `''` would delete every cached download, `'../../..'` escapes the cache | Fixed: the value must be `[0-9a-f]{64}` and the entry must resolve inside `content_addressable/sha256/`, else `PruneError` and nothing is deleted; `scripts/bazel` warns. Tests: five malformed values, and a symlinked entry pointing outside |
| 2 | minor | `check_sdk_files.py` ignores cquery's exit status and loading-phase errors | Fixed: every `ERROR:` line, skipped target (analysis or `Skipping '…'`) and exit status must be explained by `EXPECTED_ERRORS`; exit 0 on the final build; unit tests for each failure kind |
| 3 | minor | `@fuchsia_idk` watches `overlay_profile.py`, so any profile edit (e.g. M3's KVM field) refetches 3 GB | Fixed: new `scripts/idk_trim.py` holds name resolution, profile → trim and `drop_reason`; the rule watches only it and `idk_extract.py`. Verified: editing the hosted budget in `overlay_profile.py` did not refetch (marker mtime unchanged, 2 s build). "For M3" updated |
| 4 | minor | Peak disk during the IDK fetch is not measured | Recorded as a limitation with a measurement (10.81 GiB peak above the baseline, 1 s `df` samples); the tarball is already deleted from the repository directory right after extraction; M3 measures its own peak |
| 5 | minor | Stale text: plan "Next session" and this file name only `695841e`; rebuild times differ between evidence and notebook | Fixed: both commits and the checkpoint named; notebook correction entry appended (two rebuilds: 116 s and 107 s) |
| n1 | nit | Disk report misses `~/.cache/uv` and, from a worktree, the main clone's `.git` | Fixed: bucket `uv_cache`; `checkout` adds `git rev-parse --git-common-dir` when outside the checkout |
| n2 | nit | `EXPECTED_ANALYSIS_ERRORS` matches targets only, by canonical repo name | Fixed: `EXPECTED_ERRORS` pairs targets with a reason regex; labels normalized to apparent names via `bazel mod dump_repo_mapping ''` |
| n3 | nit | No test pins the `data` filter against symlinks escaping `dest` | Fixed: relative (`../../../../outside`) and absolute (`/etc/passwd`) links raise `tarfile.FilterError`, nothing written. (Writing it showed `../../outside` from `arch/x64/lib/` stays inside `dest`.) |
| n4 | nit | Acceptance boxes ticked before the fixes | The boxes stand after re-running every check below |
| b1 | backlog | `packages/realm_builder_server` has no HEAD variant in this IDK, so RealmBuilder / driver-test-realm tests at HEAD need another route (not caused by the trim) | Added to the plan backlog for M16 |

**After the fixes** (all after expunging the output base and deleting the repository
cache): the three `//...` builds with `--lockfile_mode=error` pass (167 s / 2 s / 1 s,
lock unchanged); `uv run pytest` 135 passed; `uv run reuse lint` compliant;
`disk_report.py` exit 0 (bazel 7.69/12, total 8.21/25 GiB); `check_sdk_files.py` exit 0
(0 missing, 14 expected skips, 0 unexplained). The fixes are small and each is verified
above, so the orchestrator did not ask for a second review round.

## Limitations and open items

- **Refetch cost under hosted:** any refetch of `@fuchsia_idk` (lock change, a change
  to `idk_trim.py` or `idk_extract.py`, profile change, `clean --expunge`) downloads 3 GB
  again (about 40 s here).
- **Peak disk during a fresh IDK fetch is well above the steady state** (review finding
  4, recorded). While `@fuchsia_idk` is fetched, Bazel holds the tarball in the
  repository cache and in the repository directory, alongside the growing extraction and
  the other toolchains: sampled every second with `df` during the final clean build,
  use peaked 10.81 GiB above the empty-cache baseline, against 7.57 GiB once the build
  and prune finished (so the budget's 25 GiB must leave about 3 GiB for that transient).
  The tarball is already deleted from the repository directory as soon as extraction
  returns; the cache copy lasts until `scripts/bazel` prunes after the command. M3
  measures the peak during its own first fresh fetch.
- **Prune depends on `scripts/bazel`** and on `bazel info repository_cache` naming the
  cache the command used; a command-line `--repository_cache` that differs from the
  `.bazelrc` default is not seen.
- **`large-disk` has no budget**, so its disk report never fails. A declared budget per
  environment could come later.
- **The part-metadata rule is a heuristic** (`*meta.json` kept everywhere), backed by
  the post-extraction check against `meta/manifest.json`.
- **`KEEP_API_LEVELS`/`KEEP_TARGET_CPUS` are constants** checked against `.bazelrc` by a
  test. M4's API-level cfgs read `version_history.json`, which is kept.
