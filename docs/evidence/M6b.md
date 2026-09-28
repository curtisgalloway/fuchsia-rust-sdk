<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M6b — Pilot 1's crates.io crates build evidence

Design: [design](../design.md), revision "2026-09-27, draft 1", amended 2026-09-27
(C4 BSD-2-Clause, §4.2 "Third-party crates" option A); unchanged in M6b (one wording
note for the orchestrator under "Deviations").
Notebook: [M6b chapter](../notebook/M6b.md)
Starting revision and pre-existing changes: `b242fe5` (origin/main: I1, M1–M5, M2a,
M6a), branch `ms/M6b`; working tree clean. `wip` commits `2124b78` (patched crates in
regen.py; `zx` builds — the plan's split point) and `4449c69` (the 121 crates and the
build list); the checkpoint commit `overlay: M6b — Pilot 1's crates.io crates build`
follows the review.

**Decisions relied on** (in force before M6b, rechecked in the plan and design):
option A for crates (design §4.2 "Third-party crates": upstream's crate_universe BUILD
files reused, no local crate_universe run); patched crates vendored from fuchsia.git by
`regen.py` and committed (D6); `fuchsia_sync_detect_lock_cycles = false` (so
`forks/tracing-mutex-0.3.2` is not in the closure); every `rustc_*` target under
`vendor/` gets `vendored = True`.

## Milestone definition (moved from the plan)

**Design coverage:** R4 (pilot 1 subset), D6, C1, C3, C4; R2 (`zx`, deferred from M5).
**Dependencies:** M6a (`docs/closure/pilot1.json`), M5 (`regen.py`, `@rust_crates`).
Later entries that name "M6" for crates (M7's host crates, M14's crates stage) mean M6b.
**In scope:**
- The patched crates the closure reaches, vendored from fuchsia.git's
  `third_party/rust_crates/{forks,ask2patch}/` at the revision by `regen.py` and
  committed (option A, design §4.2): measured set `ask2patch/byteorder`,
  `ask2patch/memchr`, `forks/libc-0.2.189`, `forks/zeroize` (the plan's earlier `tokio`
  is not reached; `forks/tracing-mutex-0.3.2` is not needed, because the overlay sets
  `fuchsia_sync_detect_lock_cycles = false`, decided after the M6a review).
- `zx`: `sdk/rust/zx upstream` in `vendor/crates.txt`, `//vendor/fuchsia/sdk/rust/zx` in
  `tests/vendor/BUILD.bazel` (its crates.io closure: 12 crates, 6 new, 2 patched).
- The rest of pilot 1's crates.io closure: the 44 direct aliases in `pilot1.json` and
  their 121 crates, from upstream's crate_universe BUILD files with each `.crate` pinned
  by the release `Cargo.lock` SHA-256 (M5's route).

**Out of scope:** in-tree crates beyond `zx` (M8/M9); running crate_universe locally
(decided: option A); per-crate repositories unless disk or fetch time requires them.

### Implementation steps
1. **Patched crates in `regen.py`.** Accept `//third_party/rust_crates/{forks,ask2patch}/
   <dir>` labels in crate BUILD files and aliases (M5 fails closed on them today). Copy
   each directory from fuchsia.git (the M5 `GitSource`) into a regen-owned, committed
   tree — proposed: `third_party/crates/src/<forks|ask2patch>/<dir>/` with the BUILD file
   kept beside the others as `BUILD.<kind>.<dir>.bazel`, so no main-repository package is
   created and `--check` covers the sources. `toolchain/crates.bzl` lays these out in
   `@rust_crates` from the committed files instead of downloading. Each crate keeps its
   own `LICENSE*` files; add `REUSE.toml` annotations per crate and the license texts it
   needs (`LICENSES/MIT.txt`, `Unlicense.txt`; `Apache-2.0.txt` exists). Over the 121
   crates the license kinds are MIT, Apache-2.0, Unicode-3.0, BSD-2-Clause, Unlicense,
   Zlib and BSD-3-Clause (`pilot1.json` `crates_io.transitive[].licenses`).
2. **`zx`** (first checkpoint candidate): vendor it, build for both Fuchsia targets
   (upstream marks it Fuchsia-only), add its `cap_lints` test.
3. **Crate roots from the closure.** A committed input listing the direct aliases to
   generate (proposed: `vendor/crates_io.txt`, checked against `pilot1.json`'s
   `crates_io.direct`), in addition to the aliases vendored BUILD files use.
4. **Build all of them.** `@rust_crates` targets are tagged `manual`, so `//...` skips
   them: add a build list (proposed: a generated test package that depends on every
   direct alias, or `bazel build` over a query of `@rust_crates//vendor:*`) for x64 and
   arm64, and proc macros for host. 15 crates have build scripts (`cargo_build_script`),
   the likeliest failures.
5. Network-off check: after one warm fetch, the three builds pass with
   `--repository_disable_download`.

### Acceptance criteria
- [x] Every crates.io crate in the pilot 1 closure builds for both Fuchsia targets;
  proc-macro crates build for host. — as read in "Criterion 1" below: every crate the
  Fuchsia side needs, in the configuration it is used in (target or exec); all 121 for host.
- [x] Only the closure's crates are generated, not all of `Cargo.lock` (count recorded;
  M6a measured 121: 117 crates.io + 4 patched). — 121, the same set (pytest).
- [x] A build with the network off, after one warm fetch, succeeds (checksummed and
  cached; no resolution step).
- [x] `zx` builds for both Fuchsia targets.
- [x] Each patched crate's committed files equal fuchsia.git's at the revision
  (`regen.py --check` clean; a one-byte edit fails naming the file); each keeps its
  upstream license files and REUSE lint passes.
- [x] Disk within the hosted budget (C6), recorded. — 10.30 of 25 GiB.

### Testing and review
- Verify with `uv run pytest` (fake-tree tests for patched crates, as M5's), `regen.py
  --check`, the three `//...` builds, the crate build list under both Fuchsia configs,
  `bazel test //...`.
- Review focus: version choice where `Cargo.lock` has two versions (per the GN alias,
  brief A.2 note; `pilot1.json` records each alias's crate directory), patched-crate
  provenance and licenses, build scripts under the overlay's toolchains, `MODULE.bazel.lock`
  stable.

### Session sizing
121 crates against M5's 6; the patched-crate mechanism is new. Split point: steps 1–2
(patched crates + `zx`, 12 crates) as one checkpoint, then steps 3–5. If step 1–2 take
most of the session, stop there with an incomplete handoff rather than starting the full
set.

## What was built

| File | What |
|---|---|
| `scripts/regen.py` | patched crates (`forks/`, `ask2patch/`) followed and copied; `vendor/crates_io.txt` roots; the build list in `third_party/crates/BUILD.bazel`; module docstring updated |
| `toolchain/crates.bzl` | patched crates laid out in `@rust_crates` from the committed files (`rctx.symlink` per file, `rctx.watch`), crates.io crates downloaded as before |
| `vendor/crates_io.txt` | input: the 44 direct aliases of `docs/closure/pilot1.json` (sorted, one per line) |
| `vendor/crates.txt` | `sdk/rust/zx upstream` added |
| `vendor/fuchsia/sdk/rust/zx/` | generated: `zx` from fuchsia.git (upstream `BUILD.bazel`, labels rewritten) |
| `third_party/crates/` | generated: 121 `BUILD.<crate>.bazel` (117 `BUILD.<crate>-<version>.bazel`, 4 `BUILD.<kind>.<dir>.bazel`), `BUILD.vendor.bazel` (44 aliases), `crates.json`, `BUILD.bazel` (exports + build list), `src/<kind>/<dir>/` (the 4 patched crates, 493 files, 5.4 MB) |
| `.bazelignore` | `third_party/crates/src` (patched sources are not main-repo packages) |
| `REUSE.toml`, `LICENSES/MIT.txt`, `LICENSES/Unlicense.txt` | one annotation per patched crate (its own license expression and copyright); texts from `reuse download` |
| `tests/test_regen.py` | +23 cases: patched crates end to end on the fake fuchsia.git (directory and git sources, modes, license file kept, BUILD moved), `crate_dir`, `crates_io.txt` parsing and roots, a fork's self-label and vendor deps, an in-tree label straight into a fork, `--check` naming a one-byte edit under `src/`, `crate_target`, the build list, and five error paths |
| `tests/test_crates_closure.py` | the committed set against `pilot1.json`: roots = direct aliases; generated crates = the 121 of `crates_io.transitive` (name, version, proc-macro, patched); each alias's version = the closure's; patched files committed with a license file |
| `tests/vendor/BUILD.bazel` | `cap_lints_test` for `//vendor/fuchsia/sdk/rust/zx` |

### How patched crates work

- **Upstream:** `third_party/rust_crates/{forks,ask2patch}/<dir>/` hold a crate's
  sources plus a crate_universe-generated `BUILD.bazel` of the same shape as the
  `vendor/` ones (`@rules_rust` loads, `package_info`, self labels such as
  `//third_party/rust_crates/forks/libc-0.2.189:build_script_build`). Aliases in
  `vendor/BUILD.bazel` point at them (`libc` → `forks/libc-0.2.189:libc`), and crate BUILD
  files name them directly (`bstr` → `ask2patch/memchr`). In `Cargo.lock` they are
  packages without a `source` (`[patch.crates-io]`/path).
- **regen.py:** `crate_dir()` maps an upstream package to a crate directory relative to
  `third_party/rust_crates`: `vendor/<crate>-<version>` or `<forks|ask2patch>/<dir>`
  (nested dirs such as `forks/bluetooth/bt-bass` allowed). `rewrite_crate_build` rewrites
  either to `//<dir>` inside `@rust_crates`; `rewrite_upstream_build` maps an in-tree
  label straight into a patched crate to `@rust_crates//<kind>/<dir>` (still failing on a
  `vendor/<crate>` directory named without its alias, and on any other
  `third_party/rust_crates` path). For a patched crate regen checks its `package_info`
  (name, version) against a source-less `Cargo.lock` package, copies every file except
  the top `BUILD.bazel` byte for byte with its mode to
  `third_party/crates/src/<kind>/<dir>/`, writes the rewritten BUILD file as
  `BUILD.<kind>.<dir, / as .>.bazel` (a name collision fails), and lists the files in
  `crates.json`. A nested `BUILD`/`BUILD.bazel`/`WORKSPACE*`/`MODULE.bazel`/`REPO.bazel`
  in a patched crate fails the run (it would split the package in `@rust_crates`).
- **crates.bzl:** for an entry with `files`, links each file from
  `third_party/crates/src/<path>/` into `@rust_crates//<path>` (`rctx.symlink`, so modes
  and binary files survive; `rctx.watch` re-runs the rule if one changes); crates.io
  entries are downloaded by SHA-256 as in M5.
- **--check** covers `third_party/crates/src/` with the rest of `third_party/crates/`.

### Crate roots and the build list

- `generate_crates` roots = the `@rust_crates//vendor:<alias>` labels in vendored BUILD
  files, plus `vendor/crates_io.txt`, plus direct `@rust_crates//<kind>/<dir>` labels.
  `vendor/crates_io.txt` holds pilot 1's 44 direct aliases (a pytest checks it equals
  `pilot1.json`'s `crates_io.direct`); M14 can let the walker drive it.
- `crates.json` records each crate's main `target` and `proc_macro` (from its one
  `rust_library`/`rust_proc_macro`, `crate_target()`), and regen writes two filegroups in
  `third_party/crates/BUILD.bazel`, so the project's three `//...` builds cover the set:
  - `aliases`: the 39 direct aliases that are libraries, in the configuration built (for
    a Fuchsia target, their target-side closure; their proc macros and build scripts,
    and those crates' own deps, are built for the exec platform);
  - `host_all`: all 121 crates' library or proc-macro targets, incompatible on Fuchsia.

### Criterion 1: what "builds for both Fuchsia targets" can mean here

Building every crate for a Fuchsia target is not possible and not needed: upstream's
crate_universe resolves features per platform, and a crate reached only through proc
macros or build scripts gets no Fuchsia feature set that compiles. Observed:
`synstructure` fails for Fuchsia with `use syn::visit` unresolved, because
`BUILD.syn-2.0.119.bazel` enables `visit`/`fold` only under the linux triples. And a
proc macro built as a top-level Fuchsia target is linked as a Fuchsia `.so`
(`ld.lld: unable to find library -lfdio`) — 5 of the 44 aliases failed that way in the
first attempt. So criterion 1 is checked as: every crate the Fuchsia side needs builds
in the configuration it is used in, and every crate builds for host. Measured with
`cquery 'kind("rust_library|rust_proc_macro", deps(//third_party/crates:aliases))'`:

| | x64 | arm64 | host |
|---|---|---|---|
| crates built for the Fuchsia target | 99 | 98 (`cpufeatures` is x86-only) | — |
| crates built for exec (proc macros, build-script deps) | 22 | 22 | — |
| crates built for host (`host_all`) | — | — | 121 |

Not built for a Fuchsia target: the 17 proc macros and 5 host-only libraries (`autocfg`,
`heck`, `syn-1.0.109`, `syn-3.0.3`, `synstructure`). Of those, 7 are built only for host
in M6b, because no Fuchsia-side crate uses them yet: `async-trait`, `derivative`,
`num-derive`, `paste`, `strum_macros` (direct proc-macro aliases; the in-tree crates of
M9 will pull `num-derive` and `paste` into the exec configuration) and `heck`,
`syn-1.0.109` (their deps).

### Build scripts (15)

`crossbeam-utils`, `forks/libc-0.2.189`, `getrandom` 0.3.4 and 0.4.3,
`icu_normalizer_data`, `icu_properties_data`, `libm`, `num-traits` (with `autocfg`),
`paste`, `quote`, `serde`, `serde_core`, `syn-1.0.109`, `thiserror`, `zerocopy`. None
needed an override:
- a static scan of their `build.rs` shows they spawn only `$RUSTC` (`libc`'s
  `freebsd-version` and `emcc` branches are for FreeBSD and Emscripten targets); none
  uses the `cc` crate;
- `aquery` of the 14 in the x64 build: `RUSTC` is the lock's toolchain rustc
  (`fuchsia_rust_toolchain/.../bin/rustc`, target or exec); `CC` is set by rules_rust
  (Fuchsia clang, or `/usr/bin/gcc` for exec — the backlog's "hermetic host C
  toolchain") but not used;
- all ran inside `linux-sandbox` with `--sandbox_default_allow_network=false` after a
  `bazel clean` (below).

## Verification

All commands from the worktree root; `scripts/bazel` is Bazel 8.5.1. Logs are in the
session's scratch run directory (`runs/M6b/`, outside the repository).

### `zx` (criterion 4)

```
$ scripts/bazel build --config=fuchsia_x64 //vendor/fuchsia/sdk/rust/zx
Target //vendor/fuchsia/sdk/rust/zx:zx up-to-date:
  bazel-bin/vendor/fuchsia/sdk/rust/zx/libzx-366207829.rlib
INFO: Build completed successfully, 20 total actions
$ scripts/bazel build --config=fuchsia_arm64 //vendor/fuchsia/sdk/rust/zx
INFO: Build completed successfully, 18 total actions
$ scripts/bazel test --config=fuchsia_x64 //tests/vendor:all      # same for fuchsia_arm64
//tests/vendor:cap_lints_allow_zx_test                                   PASSED in 0.0s
Executed 1 out of 5 tests: 5 tests pass.
```

`zx`'s crates.io closure is 12 crates (6 from M5, plus `bitflags`, `bstr`, `serde_core`,
`static_assertions`, `forks/libc-0.2.189`, `ask2patch/memchr`), as the plan expected.
On host `bazel test //...` skips `cap_lints_allow_zx_test` (zx is
`target_compatible_with = ["@platforms//os:fuchsia"]`).

### The crate set (criteria 1 and 2)

```
$ uv run scripts/regen.py vendor
regen.py: wrote vendor/fuchsia, third_party/crates from fuchsia.git b5274053cc0f1ba03cd0902a3da575ac9c31c152
$ python3 -c '…'   # crates.json paths vs pilot1.json crates_io.transitive[].dir
121 121 extra set() missing set()
4 patched
$ uv run pytest -q tests/test_crates_closure.py
4 passed
```

`Cargo.lock` has 1,000+ packages; only the 121 are generated. Where `Cargo.lock` has
several versions (`syn` 1/2/3, `getrandom` 0.3/0.4), each alias follows upstream's alias
file, which matches the closure's `bazel_actual` for all 44 (pytest).

```
$ scripts/bazel build --config=fuchsia_x64 //third_party/crates:aliases     # explicit: fails if incompatible
INFO: Build completed successfully
$ scripts/bazel build --config=fuchsia_arm64 //third_party/crates:aliases
INFO: Build completed successfully
$ scripts/bazel build //third_party/crates:aliases //third_party/crates:host_all
INFO: Build completed successfully
```

### Network off after a warm fetch (criterion 3)

After the builds above had fetched everything once: `scripts/bazel clean`,
`scripts/bazel shutdown`, deleted `external/+crates+rust_crates` and its marker from the
output base (so `@rust_crates` must be re-created), then with the network blocked for
Bazel (`HTTPS_PROXY`/`HTTP_PROXY` = `http://127.0.0.1:9`; `curl https://static.crates.io/`
exits 7) and downloads disabled:

```
$ scripts/bazel build --repository_disable_download --config=fuchsia_x64 //...
INFO: Elapsed time: 108.578s, Critical Path: 68.60s
INFO: 576 processes: 408 internal, 168 linux-sandbox.
INFO: Build completed successfully
$ scripts/bazel build --repository_disable_download --config=fuchsia_arm64 //...   # 21 s, success
$ scripts/bazel build --repository_disable_download //...                          # 28 s, success
$ scripts/bazel test --repository_disable_download //...
Executed 25 out of 26 tests: 25 tests pass and 1 was skipped.
```

`@rust_crates` was re-created (118 packages under `vendor/`, `forks/`, `ask2patch/`) from
the repository cache by SHA-256 (all 117 `.crate` files present, 6.5 MB) and the
committed patched sources; nothing was resolved. A second `clean` and the three builds
with `--sandbox_default_allow_network=false --repository_disable_download` also pass
(x64 109 s cold), so every build script and compile action ran without network.

### Patched crates (criterion 5)

```
$ uv run scripts/regen.py --check
regen.py --check: vendor/fuchsia, third_party/crates match fuchsia.git b5274053cc0f1ba03cd0902a3da575ac9c31c152
$ printf x >> third_party/crates/src/forks/libc-0.2.189/src/lib.rs; uv run scripts/regen.py --check; echo $?
regen.py --check: third_party/crates/src/forks/libc-0.2.189/src/lib.rs: content differs from upstream plus overlays and patches
regen.py --check: 1 file(s) drift from fuchsia.git b5274053cc0f1ba03cd0902a3da575ac9c31c152 plus overlays/ and patches/fuchsia/; rerun `scripts/regen.py vendor`
1
```

(file restored afterwards). A second `regen.py vendor` is byte-identical (hash over mode
and SHA-256 of every file under `vendor/fuchsia` and `third_party/crates`:
`1c785fbb…` before and after).

| Patched crate | Version | Files | License (Cargo.toml) | License files kept | REUSE copyright |
|---|---|---|---|---|---|
| `forks/libc-0.2.189` | 0.2.189 | 406 | MIT OR Apache-2.0 | `LICENSE-APACHE`, `LICENSE-MIT` | The Rust Project Developers |
| `forks/zeroize` | 1.9.0 | 15 | Apache-2.0 OR MIT | `LICENSE-APACHE`, `LICENSE-MIT` | 2018-2021 The RustCrypto Project Developers; The Fuchsia Authors (the fork keeps only signatures, README.fuchsia) |
| `ask2patch/byteorder` | 1.5.0 | 12 | Unlicense OR MIT | `COPYING`, `LICENSE-MIT`, `UNLICENSE` | 2015 Andrew Gallant |
| `ask2patch/memchr` | 2.8.3 | 60 | Unlicense OR MIT | `COPYING`, `LICENSE-MIT`, `UNLICENSE` | 2015 Andrew Gallant |

`uv run reuse lint`: compliant, 789 / 789 files, licenses used Apache-2.0,
BSD-2-Clause, MIT, Unlicense. The 117 downloaded crates are not committed, so their
licenses (MIT, Apache-2.0, Unicode-3.0, BSD-2-Clause, Unlicense, Zlib, BSD-3-Clause per
`pilot1.json`) need no REUSE entry; their BUILD files are Fuchsia's (BSD-2-Clause, the
existing `third_party/crates/BUILD.*.bazel` annotation).

### Project checks

| Check | Result |
|---|---|
| `uv run pytest` | 340 passed (313 before; +27) |
| `uv run reuse lint` | compliant |
| `scripts/bazel build --config=fuchsia_x64 //...` | success |
| `scripts/bazel build --config=fuchsia_arm64 //...` | success |
| `scripts/bazel build //...` | success |
| `scripts/bazel test //...` | 25 pass, 1 skipped (`cap_lints_allow_zx_test` on host) |
| `scripts/regen.py --check` | clean |
| `uv run scripts/check_sdk_files.py` | 0 missing |
| `uv run scripts/disk_report.py` | total 10.30 GiB of 25, ok |
| `MODULE.bazel.lock` | unchanged (`git diff b242fe5 -- MODULE.bazel.lock` empty) |

### Disk (C6)

| | before (M6a) | after M6b |
|---|---|---|
| Bazel group (output base, repository cache, install) | 8.25 GiB | 9.41 GiB of 12 |
| total | 9.13 GiB (after `zx`) / 8.99 at M6a | 10.30 GiB of 25 |
| free on the checkout's filesystem | 21 GB | 19.0 GiB |

The growth is build outputs: `@rust_crates` outputs are 156 MB (x64), 157 MB (arm64),
514 MB (host) and 561 MB (exec); the `.crate` downloads are 6.5 MB and the extracted
repository 58 MB. One `@rust_crates` repository (all crates fetched together) is fine at
this size, so per-crate repositories are not needed. The committed tree grows by
`third_party/crates/src` (5.4 MB, 493 files) and `vendor/fuchsia/sdk/rust/zx`.

## Deviations from the plan text

- **Build list location.** The plan proposed "a generated test package that depends on
  every direct alias, or `bazel build` over a query". The filegroups are generated into
  `third_party/crates/BUILD.bazel` (regen already owns it) instead of a test package, so
  `//...` builds the set in every project check; and they are split as above because
  not every crate can build for Fuchsia (criterion 1 reading).
- **Design R4 wording** lists the patched crates as "`byteorder`, `memchr`, `libc`,
  `tokio`"; pilot 1 reaches `byteorder`, `memchr`, `libc` and `zeroize`, not `tokio`
  (the plan already says so). The design text is the orchestrator's to amend.
- **Patched BUILD files named `BUILD.<kind>.<dir>.bazel` with `/` as `.`** (the plan's
  `BUILD.<kind>.<dir>.bazel` for nested dirs such as `forks/bluetooth/bt-bass`); a name
  collision fails the run.

## Findings for later milestones (also in the plan backlog)

- A filegroup made incompatible by one member is skipped silently by `//...`: the
  `aliases`/`host_all` groups (and any Fuchsia-only target) could drop out of the
  standard builds without an error. The evidence uses explicit targets; a standing check
  (e.g. an analysis test that the groups are compatible under each config) would make
  it permanent.
- `num-derive` and `paste` are built only for host until M9's in-tree crates use them
  from Fuchsia crates (exec configuration then).

## Limitations and open items

- `regen.py --check` still needs network access to fuchsia.git (unchanged from M5).
- `vendor/crates_io.txt` is maintained by hand against `pilot1.json` (a pytest keeps the
  two equal); M14 can derive it from the walker.
- REUSE annotations for patched crates are hand-written per crate; a new patched crate
  fails `reuse lint` until one is added (fail-closed, but manual).

## Review

*(to be filled in after the orchestrator's review; it precedes the checkpoint commit)*
