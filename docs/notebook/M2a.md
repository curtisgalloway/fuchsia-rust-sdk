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
