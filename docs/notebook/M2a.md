<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M2a — Fit the hosted disk budget

Goal: fit the Bazel caches into the hosted environment profile (design C6): a trimmed
IDK extraction, a repository-cache policy, profile detection and a disk report; see the
plan's [M2a entry](../implementation-plan.md).
Verdict record: [M2a evidence](../evidence/M2a.md)

## 2026-09-27T19:30-07:00 — opening
Starting revision: `aaf53b7` (origin/main: I1, M1, M2 and the design/plan amendment),
branch `ms/M2a`. Pre-existing changes: none (tree clean). Relied on (checked):
`scripts/bazel info` puts the output base and repository cache under the user cache
directory (`~/.cache/bazel/_bazel_root/…`); output base 16 GB (extracted IDK 13 GB, of
which `obj/` 8.3 GB; clang 1.9 GB; Rust 1.1 GB), repository cache 3.8 GB (IDK tarball
3.0 GB, clang zip 0.57 GB, three Rust zips 0.37 GB), install base 193 MB, `scripts/bazel`
cache 62 MB; 9.2 GB free. Owner direction (2026-09-27, relayed by the orchestrator): fit
the hosted profile, total ≤ 25 GB; M2a target output base + repository cache ≤ 12 GB.
Implementer is a subagent: stop before the checkpoint commit.
Approach: in the generated `@fuchsia_sdk`, HEAD prebuilts come from `arch/<cpu>/`,
and `obj/<cpu>-api-<N>/` only appears in non-HEAD `select` arms. So extract the IDK
without `obj/` (other levels), riscv64 and host-arm64 tools, after the SHA-256 check;
keep the IDK tarball out of the repository cache in the hosted profile; prove no
reachable `@fuchsia_sdk` file is missing with a cquery over the built configs.

## 2026-09-27T19:32-07:00 — surprise: the SDK's `sdk_host_tool` wrappers depend on every SDK file
A reference cquery on the untrimmed SDK (`kind("source file", deps(//... + @fuchsia_sdk//...))`,
`--config=fuchsia_x64`) reaches 840 `obj/` files and 634 riscv64 files, although HEAD
`select` arms name only `arch/<cpu>/`. The path is `@fuchsia_sdk//:all_files` (a
`glob(["**/*"])`) and the per-package `_EXPORT_SUBPACKAGE_FILEGROUP` globs; rdeps of
`all_files` are `:ffx`, `:cmc` and `:funnel` (`sdk_host_tool`, which puts the
whole SDK in runfiles for `bazel run`). `//...` does not reach `all_files`. So after a
trim those three wrappers fail with missing inputs; the toolchain itself uses
`//tools:x64/cmc` etc. directly. `fuchsia-cloud-dev`'s `dev` runs
`<sdk>/tools/x64/ffx` directly, so M3's port is unaffected. The existence check will
therefore exclude the glob filegroups and the three wrappers from its scope, and the
evidence will show the wrappers failing loudly (not silently).

## 2026-09-27T19:48-07:00 — dead end: Python `tarfile` streaming mode (`r|gz`)
First trial of `scripts/idk_extract.py` on the cached real archive used
`tarfile.open(mode="r|gz")`: after 10 minutes it had written 1 MB (killed). Streaming
mode reads through small fixed blocks; `gzip` alone reads the archive at ~400 MB/s and
`r:gz` iterates 5,287 members in 20 s. Switched to `r:gz`, visiting members in order so
each `extract()` seeks forward only. Do not go back to `r|gz`.

## 2026-09-27T19:48-07:00 — attempt: trimmed extraction of the real IDK, outside Bazel
`idk_extract.py --profile hosted` on the cached `core.tar.gz` (SHA-256 checked first,
2.7 s): 48 s, kept 4,156 files (3.47 GiB), dropped 6,173 files (9.30 GiB): `obj/*` (21
dirs), `arch/riscv64`, `tools/arm64`. `du` 3.5 GB versus 13 GB untrimmed.

## 2026-09-27T19:52-07:00 — surprise: the SDK generator reads metadata of dropped host tools
Editing `toolchain/repositories.bzl` refetched `@fuchsia_idk` with the new trimmed
extraction on the next Bazel command (a cquery), before the planned clean build. The
`@fuchsia_sdk` generation then failed: `FileNotFoundException:
…/fuchsia_idk/tools/arm64/assembly_config-meta.json`. rules_fuchsia reads the metadata
of every part in `meta/manifest.json`, including host tools for arm64 hosts; the
`obj/` and `arch/riscv64` groups hold no part metadata. Fix: `drop_reason` never
drops `*meta.json`, and `idk_extract.py` now fails unless every `parts[].meta` file
exists after extraction (so a later layout change fails at fetch, not at generation).

## 2026-09-27T19:52-07:00 — attempt: clean slate for the measured build
Before: output base 6.8 GB (already the trimmed IDK from the accidental refetch above;
the untrimmed figure, 16 GB, is in the opening entry), repository cache 3.8 GB (still
holding M2's cached IDK tarball), install base 193 MB, `scripts/bazel` cache 62 MB;
`df`: 19 GB free. Ran `scripts/bazel clean --expunge` and deleted the repository cache
directory (`…/_bazel_root/cache/repos`). After: cache 4 KB, install base 193 MB; 29 GB
free.

## 2026-09-27T19:55-07:00 — surprise: Bazel caches a download even without a checksum
The hosted path called `rctx.download` without `sha256` (comparing the returned
digest instead) so the 3 GB tarball would stay out of the repository cache. During the
clean build the cache still grew to 2.9 GB:
`content_addressable/sha256/043104ba…/file`, 3,012,334,939 bytes. Bazel 8.5.1 stores
every download under its computed SHA-256. So there is no fetch-time way to keep it out.
Decision: always pass `sha256` (Bazel then checks the whole archive before writing it
out, as in M2), and implement the hosted cache policy as a prune after fetching: remove
that one content-addressed entry. `scripts/bazel` runs it after commands that can
fetch, when the profile does not cache the archive; `disk_report.py --prune` does the
same by hand.

## 2026-09-27T19:56-07:00 — attempt: first clean build fails at load: empty sysroot glob
The clean `--config=fuchsia_x64 //...` build (149 s, fetches included) failed loading
`@fuchsia_sdk//:BUILD.bazel`: `glob pattern 'arch/riscv64/sysroot/include/**' didn't
match anything`. The generated root package globs each target CPU's sysroot
`include/**` and `lib/**`, and Bazel's glob skips dangling symlinks, so the trim left it
empty. Loud, not silent. Fix: keep `arch/<dropped cpu>/sysroot/` (riscv64: 26 MB of
597 MB). Also noted: since globs skip dangling symlinks, `:all_files` just omits the
trimmed files instead of failing. Also added the post-fetch prune to `scripts/bazel`
(previous entry). Next: expunge and clear the cache again, then the measured build.

## 2026-09-27T19:59-07:00 — attempt: measured clean build passes under the hosted profile
From an expunged output base and an empty repository cache: `scripts/bazel build
--lockfile_mode=error --config=fuchsia_x64 //...` exit 0 in 162 s (all fetches,
download, SHA-256, trimmed extraction), then `--config=fuchsia_arm64 //...` 2 s and host
`//...` 1 s; `MODULE.bazel.lock` unchanged. The post-fetch prune ran once, after the
x64 build (`removed the IDK archive from the repository cache`). `disk_report.py`:
output base 6.66 GiB (IDK 3.6 GB, clang 1.9 GB, Rust 1.1 GB), repository cache 0.91 GiB,
bazel group 7.57 of 12 GiB, total 7.84 of 25 GiB; 21.3 GiB free.

## 2026-09-27T20:01-07:00 — surprise: a missing IDK file shows up as an analysis error, not a missing path
`check_sdk_files.py` on the trimmed build: 0 missing in all three configs, but under
the Fuchsia configs 14 targets fail analysis, versus 13 on the untrimmed IDK (the
reference cquery at the start). The new one is `pkg/vulkan_layers/riscv64:vulkan_layers`
(`no such target //:arch/riscv64/dist/VkLayer_image_pipe_swapchain.so`): in the SDK's
root package a label to a file that no longer exists is `no such target` at analysis.
Negative test: moving `arch/x64/lib/libfdio.so` out of the IDK gave 0 "missing" but 37
new analysis failures (`pkg/fdio:fdio`, `//examples/hello_rust`, …). So a failed
target hides its files from the query; the check now fails on any analysis error
outside a listed set (the 13 pre-existing ones plus the riscv64-only vulkan layer), and
the negative test exits 1. File restored; check back to exit 0.

## 2026-09-27T20:06-07:00 — attempt: live tamper test, profile change, final measurement
- Lock `bazel_sdk.value` last digit `6`→`7`: the `fuchsia_idk` fetch fails in
  `rctx.download` (`Checksum was 043104ba…78f6 but wanted …78f7`), exit 2 after 41 s;
  no extraction ran. Lock restored (`git diff --exit-code` clean); nothing for that hash
  was left in the repository cache.
- `OVERLAY_PROFILE=bogus`: the `fuchsia_idk` fetch re-ran and failed with
  `unknown profile 'bogus' (known: hosted, large-disk)`, and `scripts/bazel` warned that
  the cache policy was not applied. So the repository rule does see profile changes.
- Rebuilt after both (107 s x64, 1 s arm64, 0 s host, `--lockfile_mode=error`, lock
  file unchanged); `check_sdk_files.py` exit 0; `disk_report.py` exit 0: output base
  6.75 GiB, repository cache 0.94 GiB, bazel 7.69/12 GiB, total 7.96/25 GiB.

## 2026-09-27T20:06-07:00 — correction of 2026-09-27T19:32-07:00 (sdk_host_tool wrappers)
The 19:32 entry predicted `:ffx`, `:cmc` and `:funnel` would fail after the trim.
They do not: Bazel globs skip dangling symlinks, so `:all_files` just omits the trimmed
files, and `scripts/bazel build --config=fuchsia_x64 @fuchsia_sdk//:ffx` succeeds. The
check still leaves them out of scope, because their only extra inputs are the whole-SDK
globs.

## 2026-09-27T20:08-07:00 — checkpoint
State: in progress, review pending. All five acceptance criteria verified (evidence
"Verification"); evidence written except "Review"; plan entry, Risks and Next session
updated; README gained "Disk and environment profiles". Branch `ms/M2a`: wip
`695841e`, later changes uncommitted. Next: the orchestrator's reviewer subagent, fixes,
the evidence Review section, then the checkpoint commit.

## 2026-09-27T20:16-07:00 — direction: review findings (orchestrator)
A reviewer subagent (fresh context, launched by the orchestrator) reviewed `695841e`,
`56dd031`: land after fixes. Five minor findings and four nits, with decisions: validate
the lock hash in `prune()` and keep the path inside the cache; make
`check_sdk_files.py` fail on cquery's exit code and loading errors; make
`@fuchsia_idk` depend only on a small trim spec, so general profile edits (budgets,
M3's KVM) do not refetch 3 GB; record peak fetch disk as a limitation; fix stale commit
lists and the rebuild-time mismatch. Nits: count the uv cache and a worktree's main
`.git`; match expected analysis errors on target and reason without the canonical repo
name; a symlink-escape test; tick boxes after the fixes; M16 backlog note on
`realm_builder_server`.

## 2026-09-27T20:16-07:00 — correction of 2026-09-27T20:06-07:00 (rebuild times)
That entry says "Rebuilt after both (107 s x64, …)". There were two rebuilds: after
the tamper test (116 s x64, 1 s arm64, 1 s host) and after the `bogus` profile test
(107 s, 1 s, 0 s). The evidence's figures are right.

## 2026-09-27T20:24-07:00 — attempt: review fixes applied and verified
- Findings 1–3 and nits done: `prune()` validates the hash and containment;
  `check_sdk_files.py` judges every cquery ERROR line, skipped target and exit status
  against `EXPECTED_ERRORS` (target + reason, apparent repo names through `bazel mod
  dump_repo_mapping`); the name-resolution rules, profile→trim map and `drop_reason`
  moved to `scripts/idk_trim.py`, the only profile code `@fuchsia_idk` watches;
  disk report adds `uv_cache` and the worktree's shared `.git`.
- Surprise while pinning the `data` filter: a symlink `arch/x64/lib/evil ->
  ../../outside` is *inside* the destination (it resolves to `arch/outside`); the test
  needs four levels, or an absolute target, to escape. Both are refused.
- Expunged, cleared the repository cache, rebuilt: x64 167 s, arm64 2 s, host 1 s, all
  `--lockfile_mode=error`, lock unchanged. **Peak** `df` use during that fetch, sampled
  every second: 10.81 GiB above the empty-cache baseline (7.57 GiB at the end).
- `check_sdk_files.py` exit 0 (14 skipped, 0 unexplained, 0 missing); disk report
  bazel 7.69/12, total 8.21/25 GiB (now with uv cache 0.26 GiB).
- No refetch on a general profile edit: changed the hosted `bazel` budget and appended a
  comment to `overlay_profile.py`, rebuilt x64 `//...` in 2 s; the
  `@+lock_repos+fuchsia_idk.marker` and `.overlay-idk-trim.json` mtimes were
  unchanged and the log mentions no IDK fetch. Edit reverted. pytest 135.

## 2026-09-27T20:25-07:00 — checkpoint (closing)
State: complete. Review ran before the checkpoint; all findings resolved as the
orchestrator decided and verified (evidence "Review"). Branch `ms/M2a`: wip
`695841e`, `56dd031`, then the checkpoint commit
`overlay: M2a — Fit the hosted disk budget`. Hosted: Bazel caches 7.69 GiB of 12,
total 8.21 of 25; fresh-fetch peak 10.8 GiB. Next: M3 or M4, as the orchestrator names.
