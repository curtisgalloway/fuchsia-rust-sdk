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

## 2026-09-27T23:51-07:00 — surprise: proc-macro aliases fail when built as top-level Fuchsia targets
`vendor/crates_io.txt` = the 44 direct aliases of `pilot1.json`; regen now writes exactly the
121 crates of `crates_io.transitive` (4 patched, 7.9 MB committed under `src/`). Building all
44 aliases explicitly with `--config=fuchsia_x64`: 5 fail — the proc macros (`async-trait`,
`derivative`, `num-derive`, `paste`, `strum_macros`), linked as Fuchsia `.so`s
(`ld.lld: unable to find library -lfdio`). Expected: a proc macro only makes sense for the
exec/host platform, where consumers' `proc_macro_deps` build it. The 39 library aliases
build for x64 and arm64 (their proc-macro deps built for exec), and all 44 build for host.
Logs: runs/M6b/all_x64_try1.log, libs_*.log, all_host_try1.log. So the build list splits
libraries (all configs) from proc macros (host only).

## 2026-09-27T23:55-07:00 — surprise: not every crate compiles for Fuchsia, by upstream's design
A first build list (every crate's library target in all configs, proc macros host-only)
fails for Fuchsia at `synstructure`: `syn::visit` is gated behind a feature that upstream's
crate_universe output enables only under `select` for the linux triples
(`BUILD.syn-2.0.119.bazel` `crate_features`). crate_universe resolves features per
platform; `synstructure` is reached only through proc macros (exec), so it has no Fuchsia
feature set that compiles. Same class as `heck`, `syn-1.0.109`, `autocfg`.

## 2026-09-27T23:55-07:00 — decision: build list = library aliases (all configs) + every crate (host)
regen writes two filegroups in `third_party/crates/BUILD.bazel` (so the three `//...`
builds cover the set): `aliases` (the 39 direct aliases that are libraries; for Fuchsia
their target closure, with proc macros/build scripts built for exec) and `host_all`
(every crate's library/proc-macro target, incompatible on Fuchsia). crates.json records
each crate's `target` and `proc_macro`. The acceptance reading this implies: "builds for
both Fuchsia targets" = every crate the Fuchsia side needs, built in the Fuchsia
configuration it is used in (target or exec); proc macros and host-only crates build
for host. Alternative (hand-picked per-crate lists by context) rejected: regen can derive
this from upstream's files alone.

## 2026-09-28T00:03-07:00 — attempt: network-off and build-script checks pass
Warm fetch had happened; then `bazel clean`, `shutdown`, deleted the `@rust_crates` repo
directory and marker, and built with `--repository_disable_download` and
`HTTPS_PROXY`/`HTTP_PROXY` pointing at 127.0.0.1:9 (curl to static.crates.io fails): the
three `//...` builds (x64 109 s cold, arm64 21 s, host 28 s) and `bazel test //...` (25 pass,
1 skipped) pass; `@rust_crates` is rebuilt from the repository cache by SHA-256 (117
.crate files, 6.5 MB). A second clean + three builds with
`--sandbox_default_allow_network=false` pass too, so all 15 build scripts run without
network. Static scan of the build.rs files: they spawn only `$RUSTC` (libc's
`freebsd-version`/`emcc` branches are for other targets); aquery shows RUSTC = the lock's
toolchain rustc; CC is set (clang for Fuchsia, /usr/bin/gcc for exec: backlog "hermetic
host C toolchain") but no build script compiles C. No overrides needed. Disk 10.30/25 GiB.
Logs: runs/M6b/netoff_*.log, nonet_sandbox_*.log, aquery_bs_x64.txt.

## 2026-09-28T00:08-07:00 — checkpoint (awaiting review)
State: in progress — all six criteria verified ([evidence](../evidence/M6b.md)); the
independent review, its fixes and the checkpoint commit remain. Added since the last
entry: `tests/test_crates_closure.py` (roots = `pilot1.json` direct aliases, generated =
the 121 transitive crates with names/versions/proc-macro/patched, alias versions =
`bazel_actual`), per-config cquery counts (x64 99 target + 22 exec, arm64 98 + 22, host
121), evidence, plan entry/backlog/handoff. A second `regen.py vendor` is byte-identical.
pytest 340. Next: stop for the orchestrator's review.
