<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M6b — Pilot 1's crates.io crates build

Goal: [M6b](../implementation-plan.md#m6b--pilot-1s-cratesio-crates-build): every
crates.io crate in pilot 1's closure (121, incl. 4 patched) builds, plus `zx`.
Verdict record: [M6b evidence](../evidence/M6b.md)

## 2026-09-27T23:37-07:00 — opening
Starting revision: `b242fe5` (origin/main: I1, M1–M5, M2a, M6a), branch `ms/M6b`.
Pre-existing changes: none (tree clean). Relying on (verified by the orchestrator, rechecked
here): option A for crates; patched crates vendored from fuchsia.git and committed (D6);
`fuchsia_sync_detect_lock_cycles = false`; `vendored = True` for everything under `vendor/`.
Approach: steps 1–2 first (patched crates in `regen.py` under
`third_party/crates/src/<kind>/<dir>/`, then `zx`), a WIP commit at that split point, then
`vendor/crates_io.txt` roots, a build list for the whole set, and the network-off check.
Disk at start: 21 GB free.

## 2026-09-27T23:44-07:00 — decision: patched crates as symlinked files in `@rust_crates`
Upstream's `forks/`/`ask2patch/` crates carry crate_universe BUILD files of the same
shape as `vendor/` ones (loads of `@rules_rust`, self labels
`//third_party/rust_crates/forks/libc-0.2.189:build_script_build`), so
`rewrite_crate_build` maps `//third_party/rust_crates/<kind>/<dir>` to `//<kind>/<dir>`
inside `@rust_crates` and follows them like vendor crates; deps are now rust_crates-relative
dirs (`vendor/x`, `forks/y`). Sources go to `third_party/crates/src/<kind>/<dir>/` (the
plan's path), BUILD to `BUILD.<kind>.<dir with / as .>.bazel`. `crates.bzl` symlinks each
listed file (`rctx.symlink`, `rctx.watch`) rather than `rctx.read`+`rctx.file`, which is
text-only and would lose modes. `.bazelignore` gets `third_party/crates/src`, and regen
fails on a nested BUILD/WORKSPACE/MODULE/REPO file in a patched crate. Patched crates are
checked against Cargo.lock's source-less packages (`libc 0.2.189`, `memchr 2.8.3` there).
Alternatives: a directory symlink (would make regen-owned files writable from the repo
rule; BUILD.bazel would land in the source tree), per-file labels (need a package there).

## 2026-09-27T23:44-07:00 — attempt: `zx` and its 12 crates build
`vendor/crates.txt` + `sdk/rust/zx upstream`; `vendor/crates_io.txt` created empty (an
input regen now requires). `regen.py vendor` (27 s): 12 crates (6 from M5 + bitflags, bstr,
serde_core, static_assertions, forks/libc-0.2.189 [406 files], ask2patch/memchr [60]);
`third_party/crates/src` 7.1 MB. `bazel build --config=fuchsia_x64|arm64
//vendor/fuchsia/sdk/rust/zx` both succeed first time (9 s / 7 s), incl. libc's build script
for exec. Logs: runs/M6b/zx_x64.log, zx_arm64.log.

## 2026-09-27T23:48-07:00 — attempt: split point (steps 1–2) green
pytest 335 (+22 regen tests: patched crates end to end on the fake tree incl. git source,
`crate_dir`, `crates_io.txt` parsing/roots, error paths), `regen.py --check` clean and a
one-byte edit in `third_party/crates/src/forks/libc-0.2.189/src/lib.rs` fails naming it,
reuse lint compliant (655/655; annotations per patched crate, `LICENSES/MIT.txt`,
`Unlicense.txt` via `reuse download`), three `//...` builds, `bazel test //...` 26 (25 pass,
the zx cap_lints test skipped on host as zx is Fuchsia-only; it passes under both Fuchsia
configs). Disk 9.13/25 GiB. WIP commit next; then steps 3–5 — the session has room.
