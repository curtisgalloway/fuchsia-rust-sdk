<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M2a — Fit the hosted disk budget evidence

Design: [design](../design.md), revision "2026-09-27, draft 1", amended 2026-09-27 (C6,
C3, C5; §4.2 "Toolchain")
Notebook: [M2a chapter](../notebook/M2a.md)
Starting revision and pre-existing changes: `aaf53b7` (origin/main: I1, M1, M2 and the
design/plan amendment), branch `ms/M2a`; working tree clean. Crash-insurance commit:
`695841e` (`wip: M2a — …`); the checkpoint commit
`overlay: M2a — Fit the hosted disk budget` follows it.

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
| `scripts/overlay_profile.py` | profiles (`hosted` default, `large-disk`), resolution (`$OVERLAY_PROFILE`, then `$XDG_CONFIG_HOME/fuchsia-rust-sdk/profile` or `~/.config/…`, then default), budgets; `--json` for the repository rule |
| `scripts/idk_extract.py` | SHA-256 of the whole archive, then extraction (trimmed under `trim_idk`), part-metadata check, `.overlay-idk-trim.json` report |
| `toolchain/repositories.bzl` | `idk_repository`: resolves the profile (reads the variables with `rctx.getenv`, watches the profile file and both scripts), `rctx.download` with `sha256`, runs `idk_extract.py`, deletes the tarball |
| `scripts/bazel` | after `build`/`test`/`run`/`fetch`/`query`/`cquery`/`aquery`/…: `disk_report.py --prune-cache <repository_cache>` (skip with `OVERLAY_NO_PRUNE=1`) |
| `scripts/disk_report.py` | buckets `output_base`, `repository_cache`, `bazel_install`, `emulator` (`$OVERLAY_EMULATOR_DIR`, for M3), `scratch`, `checkout`; groups `bazel` and `total` against the profile's budgets; exit 1 when over; `--prune`, `--prune-cache`, `--json` |
| `scripts/check_sdk_files.py` | per config, every source file reachable from `//...` and the SDK's targets exists, and no unexpected target fails analysis |
| `tests/test_overlay_profile.py`, `tests/test_idk_extract.py`, `tests/test_disk_report.py` | 43 new tests (75 → 118) |
| `README.md` | "Disk and environment profiles" |
| `docs/implementation-plan.md` | two project checks (SDK files present, disk budget) |

## Decisions (each has a notebook entry)

- **What the hosted trim drops** (`idk_extract.drop_reason`): `obj/<cpu>-api-<level>/`
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
- **Profile changes refetch the IDK.** The repository rule reads the profile inputs
  through `rctx.getenv` and `rctx.watch`. The extension still returns
  `reproducible = True`; `MODULE.bazel.lock` did not change.

## Verification

All commands from the repo root.

### Disk, before and after

"Before" is the M2 state this milestone started from (opening entry); "after" is
`disk_report.py` after the final clean-state build (below). `du -h` and the report
both use 1024-based units.

| Item | Before (M2) | After (M2a, hosted) |
|---|---|---|
| Output base | 16 GB | 6.75 GiB |
| — `fuchsia_idk` (extracted IDK) | 13 GB (`obj/` 8.3 GB) | 3.6 GB |
| — `fuchsia_clang` | 1.9 GB | 1.9 GB |
| — `fuchsia_rust_toolchain` | 1.1 GB | 1.1 GB |
| Repository cache | 3.8 GB (IDK tarball 3.0 GB) | 0.94 GiB (no IDK tarball) |
| **Output base + repository cache** (budget 12 GiB) | **~20 GB** | **7.69 GiB** |
| Bazel install base + `scripts/bazel` cache | 193 MB + 62 MB | 0.25 GiB |
| Checkout; scratch | — | 0.02 GiB; 4 MB |
| **Total** (budget 25 GiB) | ~20 GB | **7.96 GiB** |
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
checkout              0.02 GiB  <checkout>

group                     used      budget  status
bazel                 7.69 GiB   12.00 GiB  ok
total                 7.96 GiB   25.00 GiB  ok

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
   profile test (107 s / 1 s / 0 s).
3. **≤ 12 GB, shown by the disk report:** `bazel` group 7.69 GiB of 12 (report above).
4. **Large-disk skips trim and cache clearing (unit tests):**
   `test_large_disk_skips_trim_and_keeps_caches` (profile flags),
   `test_large_disk_extracts_everything` (every member extracted, `dropped` empty),
   `test_prune_large_disk_is_skipped` (cache entry kept),
   `test_env_var_selects_profile`, `test_file_under_home_config`,
   `test_xdg_config_home_wins_over_home`, `test_cli_json_is_what_the_repository_rule_reads`.
   Live, that the repository rule sees the profile: `OVERLAY_PROFILE=bogus scripts/bazel
   build …` re-ran the `fuchsia_idk` fetch and failed with `overlay_profile:
   $OVERLAY_PROFILE: unknown profile 'bogus' (known: hosted, large-disk)`.
5. **`uv run pytest`:** 118 passed. **`uv run reuse lint`:** compliant (REUSE 3.3).

### The trim hides no file the build can reach

`uv run scripts/check_sdk_files.py` (exit 0), on the final build:

```
fuchsia_x64: 8532 source files reachable (3749 in @fuchsia_sdk), 0 missing, 14 targets not analyzable
fuchsia_arm64: 8555 source files reachable (3749 in @fuchsia_sdk), 0 missing, 14 targets not analyzable
host: 90 source files reachable (0 in @fuchsia_sdk), 0 missing, 0 targets not analyzable
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
  The check therefore fails on any analysis failure outside
  `EXPECTED_ANALYSIS_ERRORS`. Of its 14 entries, 13 fail on the untrimmed IDK too: a
  reference cquery at the start of the milestone listed exactly those 13 (11 prebuilt
  packages, which exist only for numbered API levels; `:fuchsia_platform_sdk`,
  `:fuchsia_toolchain_version_sdk`; `rtc_conformance_test`). The 14th,
  `pkg/vulkan_layers/riscv64:vulkan_layers`, is the trim's: its inputs are
  `arch/riscv64/dist/VkLayer_*.so`.
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
  `resolve_pins.py`. One more script than planned: `scripts/check_sdk_files.py`.
- **Fetching the IDK now needs `python3` ≥ 3.11** on `PATH`.

## For M3

- Add the emulator's state directory as `$OVERLAY_EMULATOR_DIR` (or change
  `disk_report.bucket_paths`); the `emulator` bucket already counts toward `total`.
- The hosted headroom after M2a: 25 − 7.96 ≈ 17 GiB for the emulator, product bundle
  and scratch (plan Risks estimated about 15 GB for `fuchsia-cloud-dev`'s cache).
- `ffx` is `@fuchsia_idk//tools/x64/ffx` (kept); `fuchsia-cloud-dev`'s `dev` runs
  `<sdk>/tools/x64/ffx` directly, which the trim does not affect. `tools/x64/` is kept
  whole.
- Add a KVM field to the profile when M3 needs it (M3's acceptance asks for KVM
  detection; the profile is where a declared environment would say so).

## Review

(Pending: the orchestrator runs the review before the checkpoint commit.)

## Limitations and open items

- **Refetch cost under hosted:** any refetch of `@fuchsia_idk` (lock change, script
  change, profile change, `clean --expunge`) downloads 3 GB again (about 40 s here).
- **Prune depends on `scripts/bazel`** and on `bazel info repository_cache` naming the
  cache the command used; a command-line `--repository_cache` that differs from the
  `.bazelrc` default is not seen.
- **`large-disk` has no budget**, so its disk report never fails. A declared budget per
  environment could come later.
- **The part-metadata rule is a heuristic** (`*meta.json` kept everywhere), backed by
  the post-extraction check against `meta/manifest.json`.
- **`KEEP_API_LEVELS`/`KEEP_TARGET_CPUS` are constants** checked against `.bazelrc` by a
  test. M4's API-level cfgs read `version_history.json`, which is kept.
