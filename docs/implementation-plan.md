<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# Rust drivers out of tree (the overlay) — Implementation Plan

Design: [design](design.md), revision "2026-09-27, draft 1", approved 2026-09-27
including D6 (approval recorded in commit `2ced23a`; file unchanged since).
Brief: [brief](brief.md) (evidence and upstream paths; the design wins where they differ).
Notebook: [index](notebook/index.md); process log: [process log](process-log.md)
Target release for milestone 1: `33.20260927.4.1` (`LATEST_LINUX` on 2026-09-27).

**Project checks** (each is created by the milestone named; M1's two exist):

| Check | Command | Created in |
|---|---|---|
| Script tests | `uv run pytest` | M1 |
| Build, x64 | `scripts/bazel build --config=fuchsia_x64 //... //third_party/crates:aliases //tests/fidl:fuchsia_bindings` | M2 (crate list: M6b; bindings: M8a) |
| Build, arm64 | `scripts/bazel build --config=fuchsia_arm64 //... //third_party/crates:aliases //tests/fidl:fuchsia_bindings` | M2 (crate list: M6b; bindings: M8a) |
| Build, host | `scripts/bazel build //... //third_party/crates:aliases //third_party/crates:host_all` | M2 (crate list: M6b) |
| Binary checks | `scripts/bazel test //...` (symbol and `DT_NEEDED` tests) | M10 |
| Vendor drift | `scripts/regen.py --check` | M5 |
| License headers | `uv run reuse lint` (chosen in M1; `REUSE.toml` covers files without comments) | M1 |
| SDK files present | `uv run scripts/check_sdk_files.py` (every source file the three configs can reach exists after the IDK trim) | M2a |
| Disk budget (C6) | `uv run scripts/disk_report.py` (exit 1 when over the active profile's budget) | M2a |

**Where work runs.** Unless marked, a milestone runs in a Claude Code cloud container.
Its measured limits: 4 vCPU, no KVM, about 30 GB free disk. The container reaches CIPD,
GCS, BCR and git on `fuchsia.googlesource.com`; gitiles web views return 503, but git
itself works. Emulator milestones follow the method in
[`curtisgalloway/fuchsia-cloud-dev`](https://github.com/curtisgalloway/fuchsia-cloud-dev):
`core.x64` in QEMU under TCG, about 1 minute to boot, with 6 container workarounds
documented in its README. **Lab** milestones need the owner's VIM3 bench and cannot run
in the cloud.

## Conventions

- **Working branch:** each session works on the branch its harness assigns (cloud:
  `claude/*`) and opens a PR to `main`, one PR per milestone. Record the branch in the
  checkpoint entry.
- **Checkpoint commit prefix:** `overlay: M<n> — <title>` for milestones,
  `overlay: I<n> — <title>` for investigations, `docs:` for plan and design edits.
- **Design gate:** passed. Design draft 1 was approved 2026-09-27, including D6.
  Amended 2026-09-27 by owner direction (C6, the environment profile) and M2 findings
  (A2 resolved with Bazel 8.5.1; R1/R2 toolchain pins); the owner directed C6 and was
  told of the Bazel change, so no new gate was held. Material design changes need a
  new gate before the milestones they affect.
- **Disk budget (C6):** every milestone's evidence records disk use against the active
  environment profile (hosted default: ≤ 25 GB total). Over budget means verification
  is incomplete.
- **User overrides:** none.
- **Review method:** a reviewer subagent with fresh context (the `Agent` tool), given
  the design, the milestone entry, the evidence file and the diff since the starting
  revision. Its returned findings, pasted into the evidence file, are the artifact.
  `review-swarm` is not installed in cloud sessions. If it becomes available, prefer it
  for M10, M14 and G1, whose review spans more than one concern. Explicit self-review,
  with the per-criterion checklist, is the fallback only when subagents are
  unavailable; record which method was actually used.
- **Review order:** review and fixes come before the checkpoint commit, which is the
  last step.
- **Evidence:** `docs/evidence/<ID>.md`. **Notebook:** `docs/notebook/<ID>.md`.
- **Licensing (C4):** every new file carries an SPDX header (Apache-2.0, Curtis
  Galloway). Vendored files keep their upstream headers and `LICENSE`.
- **No hand edits in `vendor/` or `third_party/crates/`:** changes go through `regen.py`,
  `overlays/` or `patches/` (R6).

## Status

| ID | Outcome | Dependencies | Where | Status |
|----|---------|--------------|-------|--------|
| I1 | Documented anonymous lookup: SDK version → `fuchsia.git` revision | — | cloud | complete |
| M1 | Repo scaffold + `resolve_pins.py` writes `overlay.lock.json` (R1) | I1 | cloud | complete |
| M2 | Bazel workspace + Fuchsia Rust toolchains; a Rust binary links for x64 and arm64 (I5, R2) | M1 | cloud | complete |
| M2a | Fit the hosted disk budget (C6): trimmed IDK extraction, cache policy, disk report | M2 | cloud | complete |
| M3 | Portable emulator harness at the lock's release; the M2 binary runs on it (R2, C6) | M2a | cloud (emulator) | complete |
| M4 | `rustc_*` rules with API-level cfgs (R3) | M2 | cloud | complete |
| M5 | Vendor stage of `regen.py` + `--check`; `zx-types`, `zx-sys`, `zx` build (R6 mechanism, R2) | M4 | cloud | complete |
| M6a | Pilot 1 closure measured (D8, R12 data): `closure.py`, `docs/closure/pilot1.json` | M5 | cloud | complete |
| M6b | Pilot 1's crates.io crates build, incl. the patched ones and `zx` (R4) | M6a | cloud | complete |
| I2 | Prebuilt `fidlgen_rust` / `fidlgen_rust_next`: published or not | — | cloud | complete |
| M7 | Both FIDL generators available as Bazel host tools (R5 tools) | I2, M6b | cloud | complete |
| M8a | `fidl.bzl` + `fidl_rust.bzl`, `rust` flavor; pilot 1's 23 libraries compile for both targets (R5) | M7 | cloud | review pending |
| M8b | `rust_next` flavor + the driver transport; pilot 1's FIDL closure complete (R5) | M8a | cloud | pending |
| M9 | Pilot 1's in-tree crates vendored; `fdf`, `fdf_component` build (R6) | M8b | cloud | pending |
| M10 | `fuchsia_rust_driver` rule; pilot 1 packages and passes symbol checks (R7) | M9 | cloud | pending |
| I3 | Emulator bind target for pilot 1 confirmed at this release | M3 | cloud (emulator) | pending |
| M11 | Pilot 1 binds on the emulator (R8a) | M10, I3 | cloud (emulator) | pending |
| G1 | **Milestone 1 gate**: R1–R7 + R8a from a clean clone | M11 | cloud (emulator) | pending |
| I4 | Method to replace the in-tree `aml-saradc` on the VIM3 | — | **lab** | pending |
| M12 | Pilot 2 closure; `aml_saradc` builds for arm64 and passes R7 checks (R4–R7) | G1 | cloud | pending |
| M13 | Pilot 2 binds on the VIM3 and reads the ADC (R8b) | M12, I4 | **lab** | pending |
| M14 | `regen.py` end to end + closure report (R10, R12) | M12 | cloud | pending |
| M15 | Second release regenerates with zero manual edits (R10) | M14 | cloud (emulator) | pending |
| M16 | Driver unit tests build and pass on the emulator (R9) | M12, M3 | cloud (emulator) | pending |
| M17 | `fuchsia-ci` job runs `regen.py` per mirrored release (R11) | M15 | `fuchsia-ci` repo | pending |
| G2 | **Final system verification** against the full design | M13–M17 | cloud + **lab** | pending |

Critical path to milestone 1: I1 → M1 → M2 → M2a → M4 → M5 → M6a → M6b → M7 → M8a → M8b → M9 → M10 → M11 → G1.
M3, I2 and I3 run beside it. I4 needs only the lab, so it can run any time before M13.

## Design coverage

| Requirement | Milestones | Verification |
|-------------|------------|--------------|
| R1 pinned lock | I1, M1 (M14 folds into `regen.py`) | pytest with stubbed network; two runs byte-identical; live run for `33.20260927.4.1` |
| R2 toolchain | M2 (link), M3 (runs), M5 (`zx*` build) | both configs build; binary prints on emulator |
| R3 API-level cfgs | M4 | test crate takes the `HEAD` branch on both targets |
| R4 crates.io crates | M6 (pilot 1), M12 (pilot 2) | every closure crate builds for both targets; proc macros for host |
| R5 FIDL bindings | M7 (tools), M8a (rule, `rust`), M8b (`rust_next`, driver transport), M12 (pilot 2 libraries) | bindings for every closure library compile for both targets, both flavors |
| R6 vendored crates | M5 (mechanism), M9 (pilot 1), M12 (pilot 2) | named crates build for both targets; `regen.py --check` clean |
| R7 driver rule | M10 (pilot 1), M12 (`DT_NEEDED` vs in-tree `aml-saradc`) | `llvm-readelf` tests; restricted-symbols check |
| R8a pilot 1 | I3, M11 | `ffx driver list`, `list-devices -v`, `ffx log` on emulator |
| R8b pilot 2 | I4, M13 | `list-devices -v` shows overlay URL; ADC read |
| R9 unit tests | M16 | `aml-saradc` tests pass on emulator |
| R10 regeneration | M14, M15 | two consecutive releases, zero manual edits; failure messages name the patch or crate |
| R11 CI | M17 | one release processed end to end, visible in dashboard |
| R12 closure report | M14 (M15 confirms per release) | report file per release, schema-checked in pytest |
| I5 (rules coupling) | M2 step 1 | empty workspace loads both rule sets |
| C6 environment profile | M2a (mechanism); every later milestone (evidence) | disk report against the active profile's budget |

**Gap flagged for the owner (does not block M1–M9).** R7 requires that the driver's
`DT_NEEDED` set match "the in-tree build of the same driver taken from the release's
product bundle". For pilot 1 no such build exists: `examples/drivers/simple/rust` is a
sample and is probably not in the `core.x64` bundle [verify in M10]. The plan
therefore:

- in M10, compares pilot 1 against an in-tree Rust driver that the `core.x64` bundle
  does ship (candidates from design F10), and treats any extra library as a finding
  to explain;
- in M12, applies the like-for-like check to `aml-saradc` against the VIM3 bundle.

Confirm or amend this reading before M10 closes.

---

## I1 — SDK version → release revision

**Design coverage:** I1 (blocks R1). **Dependencies:** none. **Status:** complete.
**Outcome:** `product_bundles.json` for the version → each product build's public
`source_manifest.json` (`fuchsia-public-artifacts-release/builds/<id>/`) gives the
`fuchsia.git` revision; the IDK's CIPD instance (`fuchsia/sdk/core/linux-amd64`,
`version:<V>`) carries `git_revision:<integration commit>`, which must equal every
build's integration commit. `33.20260927.4.1` → `b5274053cc0f…`; `33.20260919.6.1` →
`71dec18ae968…`. IDK FIDL content matches both.
**Evidence:** [I1](evidence/I1.md) · **Notebook:** [I1](notebook/I1.md)
**Open limitations:** fails closed when builds disagree (seen for `20.20240404.1.1`) or
when a release has no product bundles. CIPD `git_revision` tags are *integration*
commits, not `fuchsia.git`, and one integration commit does not fix `fuchsia.git`; the
IDK's own build is not checked, so the FIDL-blob cross-check is the only direct IDK
evidence.

---

## M1 — Repo scaffold and pinned release lock

**Design coverage:** R1, C1, C4. **Dependencies:** I1. **Status:** complete.
**Outcome:** `uv run scripts/resolve_pins.py <V>` writes `overlay.lock.json` with
`sdk_version`, `fuchsia_revision`, `integration_revision`, `rust_host`, `rust_target`,
`bazel_sdk` (the release's IDK `core.tar.gz` SHA-256, plus `url`), `rules_fuchsia` (CIPD
instance at the integration revision) and `cargo_lock_sha256`, each `{value, source[]}`
(CIPD fields add `package`). git runs isolated from user and system config (C1). Two live
runs for `33.20260927.4.1` were byte-identical (`c4e031a8…`); `uv run pytest` (68) and
`uv run reuse lint` pass. An independent review ran before the checkpoint: 1 major and
4 minor findings fixed.
**Evidence:** [M1](evidence/M1.md) · **Notebook:** [M1](notebook/M1.md)
**Open limitations:** I1's limitation stands (the IDK's own build is unchecked); each run
streams the 3 GB IDK to hash it (about 50–85 s per run); `rules_fuchsia` instances are shared by
neighboring releases whose rules did not change.

---

## M2 — Bazel workspace and Fuchsia Rust toolchains

**Design coverage:** I5, R2 (link half), D3, D4, C5, A2. **Dependencies:** M1.
**Status:** complete. An independent review ran before the checkpoint (5 minor findings
and 9 nits, all resolved as the orchestrator decided). The detailed entry is in the
evidence file.
**Outcome:** Bazel 8.5.1 (`scripts/bazel`, `.bazelversion`) with `rules_fuchsia`,
`@fuchsia_sdk` (generated from the release's IDK), `@fuchsia_clang` and the release's
CIPD Rust toolchain, all from `overlay.lock.json` through two module extensions in
`toolchain/`; `rules_rust` 0.69.0 + upstream's patch. `examples/hello_rust` links for
`fuchsia_x64` and `fuchsia_arm64` (`DT_NEEDED` libfdio/libzircon/libc) from a clean
output base; `examples/hello_host` (binary + proc macro) builds with the host toolchain.
The lock gained `rust_host_std` and `clang`.
**Evidence:** [M2](evidence/M2.md) · **Notebook:** [M2](notebook/M2.md)
**Open limitations:** Bazel version deviates from design §4.1 (the orchestrator amends the
design); Bazel caches take about 20 GB, leaving 9 GB free (M3 needs about 15 GB; the IDK
trim is the orchestrator's new M2a under C6); host linking uses the system gcc; no default
build-flags toolchain (M4 may revisit); no Fuchsia proc-macro use yet (M6).

---

## M2a — Fit the hosted disk budget

**Design coverage:** C6. **Dependencies:** M2.
**Status:** complete. An independent review ran before the checkpoint (5 minor findings,
4 nits, 1 backlog item, all resolved as the orchestrator decided). The detailed entry is
in the evidence file.
**Outcome:** environment profiles: `hosted` by default, `large-disk` declared by
`$OVERLAY_PROFILE` or `~/.config/fuchsia-rust-sdk/profile`. `scripts/idk_trim.py` is the
only profile code `@fuchsia_idk` depends on; budgets and other fields are in
`scripts/overlay_profile.py`. Under `hosted`, `@fuchsia_idk` is SHA-256-checked by
`rctx.download`, then extracted by `scripts/idk_extract.py` without `obj/` (non-HEAD
levels), riscv64 libraries and arm64 host tools (3.6 GB instead of 13 GB), and
`scripts/bazel` prunes the IDK tarball from the repository cache after fetching. From a
clean output base all three `//...` builds pass. Output base + repository cache is
7.69 GiB (budget 12) and the total 8.21 GiB (budget 25), by `scripts/disk_report.py`;
`scripts/check_sdk_files.py` shows no reachable SDK file missing and no unexplained
cquery error. pytest 135 and `reuse lint` pass.
**Evidence:** [M2a](evidence/M2a.md) · **Notebook:** [M2a](notebook/M2a.md)
**Open limitations:** a refetch of the IDK downloads 3 GB again; a fresh IDK fetch
peaks at about 10.8 GiB (M3 measures its own peak); the prune needs `scripts/bazel`;
fetching the IDK needs `python3` ≥ 3.11; `large-disk` has no budget.

---

## M3 — Portable emulator harness at the lock's release

**Design coverage:** R2 (runs on emulator), C6, design §7 "Emulator" row, W7.
**Dependencies:** M2a. **Status:** complete. An independent review ran before the
checkpoint (1 major, 4 minor findings, 2 nits, all resolved as the orchestrator and the
owner decided). The detailed entry is in the evidence file.
**Outcome:** `scripts/emu` (setup/verify/start/stop/check/run/driver/log/ffx/env), ported
from `fuchsia-cloud-dev`'s `dev` (BSD notice and Fuchsia `PATENTS` kept), boots the
lock's `core.x64` in QEMU: KVM when `/dev/kvm` is usable, else TCG (about 51 s). ffx and
QEMU come from the lock's IDK (its `qemu_internal` is fuchsia.git's own QEMU pin); the
bundle from the new lock field `product_bundle` (transfer manifest + a digest over every
file's SHA-256, owner decision "yes, pin the bundle by hash"), verified after download.
Host detected, not assumed (`scripts/emu_env.py`: state dirs, socket-path room, KVM,
IPv6, ssh, network preflight naming blocked hosts); README "Emulator" is the host
contract. `examples/hello_rust:pkg` runs as a component and logs. Disk: total 8.8 GiB of
25 (clean-slate peak about 9.6 GiB). pytest 222, reuse lint, three builds pass.
**Evidence:** [M3](evidence/M3.md) · **Notebook:** [M3](notebook/M3.md)
**Open limitations:** `scripts/emu driver` (and workaround 6's reboot) untested until
M11; `dev test` not ported (M16); the emulator disk image can grow toward 10 GiB;
`resolve_pins.py` streams ~364 MB more per run.

---

## M4 — `rustc_*` rules with API-level cfgs

**Design coverage:** R3. **Dependencies:** M2.
**Status:** complete. An independent review ran before the checkpoint (5 minor findings,
2 nits, all docs/backlog, resolved as the orchestrator decided). The detailed entry is
in the evidence file.
**Outcome:** `rules/rustc.bzl` ports upstream's `rustc_library`, `rustc_binary` and
`rustc_proc_macro` (plus `vendored = True` → `--cap-lints=allow`; first-party `deny`,
with upstream's lint configs in `rules/lints`). The API-level cfgs are added by the
toolchains, as upstream does: `rules/rustc_api_level.bzl` (upstream's generator) fed by
`@fuchsia_api_levels`, which `toolchain/api_levels.bzl` writes from the IDK's
`version_history.json`; x64/arm64 `select()` on rules_fuchsia's API level, host gets
PLATFORM. `tests/api_level`: 18 golden tests against upstream's own generator output
(the same code run on two pinned inputs), a build that fails unless the HEAD branch is
taken (both targets), and cap-lints tests. pytest 222, reuse lint, three builds and
`bazel test //...` pass; total disk 8.82 GiB of 25.
**Evidence:** [M4](evidence/M4.md) · **Notebook:** [M4](notebook/M4.md)
**Open limitations:** the unit-test attributes are accepted but generate nothing until
M16 (its acceptance now requires them); host and exec-config code builds at PLATFORM,
and in-scope crates branch on it (M8 decides host FIDL level); goldens are regenerated
by hand (recipe in the evidence).

---

## M5 — Vendor stage of `regen.py`; `zx` crates build

**Design coverage:** R6 (mechanism and `--check`), R2 (`zx-types`, `zx-sys`), D6, D9.
**Dependencies:** M4.
**Status:** complete. An independent review ran before the checkpoint (1 major, 2 minor
findings, 5 nits, all resolved as the orchestrator decided; the major one corrected the
repo's Fuchsia license to BSD-2-Clause). The detailed entry is in the evidence file.
**Outcome:** `scripts/regen.py vendor` copies the paths in `vendor/crates.txt` from
fuchsia.git at the lock's revision (depth-1 blobless fetch, blobs by ID, M1's isolated
git) to `vendor/fuchsia/<path>/`, rewrites upstream `BUILD.bazel` files (parsed with
`ast`, failing closed at file:line on anything unmapped) (rules →
`//rules:rustc.bzl`, lints → `//rules/lints`, `//:license`, in-tree paths →
`//vendor/fuchsia/…`, crates.io → `@rust_crates`), adds `vendored = True` to every
`rustc_*` call, applies `overlays/` and `patches/fuchsia/`, and copies the root
`LICENSE`/`PATENTS`. It also writes `third_party/crates/`: the crates.io closure
(6 crates for `zerocopy`) from upstream's own crate_universe BUILD files, each `.crate`
pinned by the release `Cargo.lock`'s SHA-256 (`@rust_crates`, `toolchain/crates.bzl`).
`--check` regenerates and names every drifting file. `zx-types`, `zx-sys`, `zx-status`,
`zx-status-ext` build for x64, arm64 and host; a second run is byte-identical; a
one-byte edit fails `--check` naming the file. pytest 277, reuse lint, three builds,
`bazel test //...` (25) pass; total disk 8.99 GiB of 25.
**Evidence:** [M5](evidence/M5.md) · **Notebook:** [M5](notebook/M5.md)
**Open limitations:** `zx` deferred to M6 (it needs the patched `libc` fork and
`ask2patch/memchr`, M6's scope); crate_universe is not run locally (upstream's output
is reused, decided: option A; design §4.2 and C4 wording are the orchestrator's to
amend); `--check` needs network access to fuchsia.git; `tests/vendor` lists vendored
crates by hand.

---

## M6a — Pilot 1 closure measured

**Design coverage:** D8, R12 (closure data first produced). **Dependencies:** M5.
**Status:** complete. An independent review ran before the checkpoint (1 blocker,
1 major, 3 minor findings, 2 nits, all resolved as the orchestrator decided); a second
round after the checkpoint (verdict land: 1 minor, 1 record, 2 nits) was fixed in a
follow-up commit. Split from
M6 (accepted by the orchestrator): the transitive crate count and the new patched-crate
mechanism; criteria 2–4 moved to M6b. The detailed M6 entry is in the evidence file.
**Outcome:** `scripts/closure.py` walks GN deps by evaluating BUILD.gn
(`scripts/gn_eval.py`: variables, scope literals and `forward_variables_from`, `foreach`,
same-file templates, relative labels, `proc_macro_deps`, conditions per toolchain
context, build-argument defaults; anything it cannot follow is a recorded gap), follows
`rustc_dylib` (`vfs` found), FIDL deps and the binding templates' deps per flavor, and
resolves crates.io aliases through upstream's crate_universe BUILD files.
`docs/closure/pilot1.json` (roots `//sdk/lib/driver/component/rust`,
`//sdk/lib/driver/runtime/rust`, `//examples/drivers/simple/rust:driver`, with
`fuchsia_sync_detect_lock_cycles = false`): 69 in-tree crates (45 with upstream Bazel;
178,945 `.rs` lines), 44 direct crates.io crates, 121 transitively (117 crates.io + 4
patched: `ask2patch/byteorder`, `ask2patch/memchr`, `forks/libc-0.2.189`,
`forks/zeroize`), 23 FIDL libraries (`fuchsia.sys2` not in the IDK), 1 bind library;
0 gaps, 0 unknown deps, 0 UNKNOWN conditions; upper bound 72 / 50 / 145 / 24. Brief
(dw-spi roots): 67 / 44 / 34. Two fresh runs are byte-identical. pytest 313, reuse lint,
three builds, `bazel test //...` (25), `regen.py --check` pass; disk 8.99 / 25 GiB.
**Evidence:** [M6](evidence/M6.md) · **Notebook:** [M6](notebook/M6.md) (M6a used the
chapter and evidence named `M6`; M6b uses `M6b`)
**Open limitations:** imported templates are not run (only the FIDL binding templates
are modelled, by a table transcribed from the release); build arguments two imports deep
would be UNKNOWN; the report is refreshed by hand until M14.

---

## M6b — Pilot 1's crates.io crates build

**Design coverage:** R4 (pilot 1 subset), D6, C1, C3, C4; R2 (`zx`, deferred from M5).
**Dependencies:** M6a, M5. Later entries that name "M6" for crates (M7's host crates,
M14's crates stage) mean M6b.
**Status:** complete. An independent review ran before the checkpoint (1 major
record, 4 minor findings, 2 nits, all resolved as the orchestrator decided; criterion 1
is read as "every crate builds in the configuration it is used in, Fuchsia target or
exec, and all 121 build for host", decided by the orchestrator). The detailed entry is
in the evidence file.
**Outcome:** `regen.py` follows and commits the patched crates (`forks/`, `ask2patch/`)
under `third_party/crates/src/<kind>/<dir>/` (byte for byte, BUILD file beside the
others as `BUILD.<kind>.<dir>.bazel`), and `toolchain/crates.bzl` links them into
`@rust_crates`; `vendor/crates_io.txt` adds pilot 1's 44 direct aliases as roots. The
generated set is exactly the closure's 121 crates (117 crates.io + `forks/libc-0.2.189`,
`forks/zeroize`, `ask2patch/byteorder`, `ask2patch/memchr`), checked against
`pilot1.json` in pytest. `zx` is vendored and builds for x64 and arm64. A generated build
list (`//third_party/crates:aliases`, `:host_all`, named explicitly in the three build
checks) compiles the set: for Fuchsia every crate the target side needs (x64 99 target + 22 exec, arm64
98 + 22: 114 / 113 distinct crates, of which 7 are built for both target and exec), for
host all 121; crate_universe's per-platform features mean host-only crates
(e.g. `synstructure`) do not build for Fuchsia. With `@rust_crates` deleted, downloads
disabled and the network blocked, the three builds and `bazel test //...` pass; the 15
build scripts need no overrides and run with sandbox networking off. `--check` names a
one-byte edit under `src/`; REUSE annotations per patched crate (+ `MIT`, `Unlicense`
texts). pytest 340, reuse lint, three builds, `bazel test //...` (25 + 1 skipped),
`regen.py --check` pass; disk 10.30 / 25 GiB; `MODULE.bazel.lock` unchanged.
**Evidence:** [M6b](evidence/M6b.md) · **Notebook:** [M6b](notebook/M6b.md)
**Open limitations:** `--check` needs network access to fuchsia.git; `vendor/crates_io.txt`
and the patched crates' REUSE annotations are maintained by hand (pytest and reuse lint
catch drift); `num-derive` and `paste` build only for host until M9 uses them.

---

## I2 — Prebuilt FIDL generators

**Outcome:** split answer for `33.20260927.4.1`. `fidlgen_rust_next` is published
anonymously, but only in the release's public debug-symbol store:
`https://storage.googleapis.com/fuchsia-public-artifacts-release/buildid/ad8c417e211deb69e793b2d354c96c310416fc3c/executable`,
SHA-256 `c03f7086aa6de3dbfa1cc06647d2667455d81c7f539f3d932ec08bd4fe5ee1ae` (decoded
bytes; Bazel's `http_file` verifies it). The release's own build manifests
(`build-ids.json`, 9 of 10 builds) name that build ID. `fidlgen_rust` (Go) is **not
published**: not in the build directories, the debug store, CIPD or the IDK.
**Dependencies:** none. **Status:** complete.
**Evidence:** [I2](evidence/I2.md) · **Notebook:** [I2](notebook/I2.md)
**Open limitations:** the build ID is not recomputable from the file; the store's
lifecycle is not readable anonymously (copies from 2025-04 still exist). M7 route decided
by the orchestrator: fetch `fidlgen_rust_next` by pin, build `fidlgen_rust` from source.

---

## M7 — FIDL generators as Bazel host tools

**Outcome:** `scripts/bazel run //tools/fidlgen_rust -- --help` and
`//tools/fidlgen_rust_next` work. `fidlgen_rust_next` is the release's prebuilt, pinned
by the new lock field `fidlgen_rust_next` (`resolve_pins.py` follows I2's chain per
release and fails closed); `fidlgen_rust` is built from source vendored by `regen.py`
(Go rules mapped, Go tests dropped, fail-closed) with `rules_go` 0.61.1 and the release's
own Go SDK (new lock field `go`, fuchsia.git's `fuchsia/go` CIPD pin, wrapped as upstream
does). Both reproduce upstream's goldens byte for byte (20 `diff_test`s) and generate
both crates from `fuchsia.mem` IR made by the IDK's `fidlc`; nothing builds for Fuchsia
targets; 0 host crates added.
**Design coverage:** R5 (tools), A4, D7. **Dependencies:** I2, M6b.
**Status:** complete (independent review before the checkpoint: land; fixes in the evidence).
**Evidence:** [M7](evidence/M7.md) (definition moved there) · **Notebook:** [M7](notebook/M7.md)
**Open limitations:** fuchsia.mem output checked for content, compiled only in M8;
`tests/fidlgen/testdata` is a hand copy to refresh per release (backlog); rules_go's
`go_sdk` extension asks go.dev for SDK metadata unless `MODULE.bazel.lock` has its
`facts` (kept; nothing is downloaded from go.dev either way).

---

## M8a — FIDL Rust binding rule, `rust` flavor

**Outcome:** split from M8 before starting (accepted in advance by the orchestrator): the
bindings' in-tree runtime closure is 26 crates (21 new), over the ~10 threshold.
`rules/fidl.bzl` (upstream's `fidl_library` as a symbolic macro; IR from the IDK's
`fidlc` at the target API level: Fuchsia at rules_fuchsia's level (HEAD), host at
PLATFORM = `runtime_supported_api_levels`) and `rules/fidl_rust.bzl` (upstream's
`fidl_rust_library` with GN's crate settings: `rust`, `rust_common`, `rust_flex`).
`regen.py` vendors upstream's `sdk/fidl/<lib>/BUILD.bazel` for pilot 1's 23 libraries
(new `idk` mode: sources from the IDK; `fuchsia.sys2`, not in the IDK, from fuchsia.git)
and the `rust` runtime (`fidl`, `rust_constants`, `fuchsia-async(-macro)`,
`fuchsia-sync`; Fuchsia-only by three patches). All 23 libraries' `rust` crates compile
for x64 and arm64; host FIDL is generated at PLATFORM (tested) but not compiled (the host
runtime is outside the closure). The driver transport (feature `driver`, `fidl_driver`,
`fdf`) waits for M8b, as in upstream's Bazel rule.
**Design coverage:** R5, D7, F6, C1, C3, C4. **Dependencies:** M7.
**Status:** implemented; review pending (orchestrator). The detailed entry is in the
evidence file.
**Evidence:** [M8](evidence/M8.md) · **Notebook:** [M8](notebook/M8.md) (M8a uses the
chapter and evidence named `M8`; M8b uses `M8b`)
**Open limitations:** host FIDL crates are not compiled (host `fidl` needs
`fuchsia-emulated-handle`, `forks/tokio`, `futures-lite`); `fdomain` flavor not built;
fidl-lint and IR schema validation not run; `fuchsia.power.broker`'s crates are visible
only to the packages upstream names.

---

## M8b — FIDL Rust binding rule, `rust_next` flavor and the driver transport

**Design coverage:** R5, D7, F6. **Dependencies:** M8a.
**In scope:**
- `rules/fidl_rust.bzl` (or a sibling file): the `rust_next` and `rust_next_common`
  flavors, from `build/rust/fidl_rust_next.gni` and `build/fidl/fidl.gni` at the release:
  crate `fidl_next_<lib>` / `fidl_next_common_<lib>` (targets `<lib>_rust_next`,
  `<lib>_rust_next_common`), edition 2024, `--config configs/{fuchsia,common}.json`,
  `--common-lib fidl_next_common_<lib>` for the regular crate, deps
  `fidl_next` (`:fidl_next_internal`) + `static_assertions` + the dep libraries'
  `_rust_next[_common]` + zx → `zx-types`, feature `fuchsia` on Fuchsia, and with
  `contains_drivers` (not on host) the feature `driver` and
  `//sdk/lib/driver/runtime/rust/fidl`. Upstream's Bazel `fidl_library` has no
  `rust_next` yet (fxbug.dev/454452299), so GN is the reference.
- The `rust_next` runtime: `fidl_next`, `fidl_next_bind`, `fidl_next_codec`,
  `fidl_next_protocol`, `fidl_next_util`, `fuchsia-loom` (6 crates, all with upstream
  `BUILD.bazel`).
- The driver transport, for both flavors: GN's feature `driver` plus
  `//src/lib/fidl/rust/fidl_driver` and `//sdk/lib/driver/runtime/rust` on `rust`
  (`fuchsia.driver.framework`, the only pilot 1 library with `enable_rust_drivers`), and
  `sdk/lib/driver/runtime/rust/fidl` (`fdf_fidl`) on `rust_next` (`fuchsia.driver.framework`,
  `fuchsia.power.broker`). `fidlgen_rust_next` output uses `::fdf_fidl` for driver
  channels without a feature gate (golden `handles.rs`), so the `rust_next` crates of
  those two libraries need it. Crates: `fidl_driver`, `fdf`, `fdf_channel`, `fdf_core`,
  `fdf_sys`, `fdf_fidl`, `libasync`, `libasync_dispatcher`, `libasync_sys`,
  `libasync_fidl` (10, none with upstream `BUILD.bazel`: overlays, and native deps on the
  IDK's driver runtime and `async` libraries). These are also named in M9's scope.
- `rust_next` bindings for the 19 libraries the closure uses in that flavor; the flex
  crate stays as M8a built it.

**Out of scope:** `fdomain` flavors; `fidl_rust_next_convert` crates (no pilot 1 user);
pilot 2 libraries (M12).

### Implementation steps
1. Port the `rust_next` flavor into the macro (`enable_rust_next`), with a
   `tests/fidlgen`-style check that its arguments match `fidlgen.bzl`'s `FLAVORS`.
2. Vendor the 6 `rust_next` crates through `regen.py` (Fuchsia-only patches where their
   host branches leave the closure, as M8a's); build the 17 non-driver libraries.
3. Driver transport: overlays for the 10 crates, native deps mapped to the IDK
   (`@fuchsia_sdk//pkg/async-cpp`, driver runtime; confirm names), then the `driver`
   feature and deps in both flavors.
4. Extend `tests/fidl` (crate names `fidl_next_<lib>`, `fidl_next_common_<lib>`; a
   driver-transport use of `fuchsia.driver.framework`).

### Acceptance criteria
- [ ] Bindings for every FIDL library in `pilot1.json` compile for both targets in each
  flavor the closure uses (`rust_next` 19, `rust_next_common` 19; `rust`/`rust_common`
  now with the driver transport where GN enables it).
- [ ] Crate names match what vendored crates `use` (`fidl_next_fuchsia_io`,
  `fidl_next_common_fuchsia_io`); the evidence records the `rust_next` naming rule.
- [ ] `regen.py --check` is clean; the generated crate set still equals the closure's.

### Testing and review
- Review focus: flags and features parity with `fidl_rust_next.gni` (the `fuchsia` and
  `driver` features, `--common-lib`), the overlays against their `BUILD.gn`, IR
  dependency order.

### Session sizing
16 new crates, 10 of them overlays: over the ~10 threshold. Split point: the `rust_next`
flavor with its 6 crates (no driver transport; the two `contains_drivers` libraries'
`rust_next` crates wait), then the driver transport (10 overlay crates), which could
instead join M9, whose scope already names `sdk/lib/driver/runtime/rust/*` and
`sdk/lib/async/rust/*` (orchestrator's call; see the backlog).

### Evidence and findings
Status: pending · Evidence: [M8b](evidence/M8b.md) · Notebook: [M8b](notebook/M8b.md)

---

## M9 — Pilot 1 in-tree crates vendored

**Design coverage:** R6 (pilot 1 set), D8. **Dependencies:** M8.
**In scope:** the remaining in-tree crates in `pilot1.json`, in particular:
- the `sdk/lib/driver/runtime/rust/*` crates (`fdf` and its parts);
- `sdk/lib/driver/component/rust` (`fdf_component`);
- `sdk/lib/async/rust/*`.

Most have no upstream `BUILD.bazel` (brief A.1), so each gets a reviewed
`overlays/…/BUILD.bazel`. Trims needed to avoid heavyweights go in as patches.

**Out of scope:** pilot 2 crates (`mmio`, `pdev`, `fdf_metadata`).

### Implementation steps
1. For each crate without Bazel, translate `BUILD.gn` (`sources`, `deps`, `edition`,
   `features`, `name`) into `overlays/<path>/BUILD.bazel`, then review it by hand
   (design §4.2).
2. Vendor bottom-up, building each crate before its dependants.
3. Any trim (a conditional dependency the walker counted) becomes a
   `patches/fuchsia/…` file with a comment giving the reason.

### Acceptance criteria
- [ ] `fdf`, `fdf_component` and every other in-tree crate in `pilot1.json` build for
  both targets.
- [ ] `regen.py --check` is clean; every change against upstream is in `overlays/` or
  `patches/`.
- [ ] The evidence lists each patch with its reason and each `overlays/` file.

### Testing and review
- Review focus: overlay BUILD files against their `BUILD.gn` (a missed feature flag
  compiles but changes behavior), and patch minimality.

### Session sizing
Split point: the runtime crates (`fdf*`, `async`) then `fdf_component`. Budget follows
the crate count in `pilot1.json`; split before starting if more than about 12 crates
need overlays.

### Evidence and findings
Status: pending · Evidence: [M9](evidence/M9.md) · Notebook: [M9](notebook/M9.md)

---

## M10 — `fuchsia_rust_driver` rule; pilot 1 packages

**Design coverage:** R7, F3, A3. **Dependencies:** M9.
**In scope:**
- `rules/fuchsia_rust_driver.bzl`: a `cdylib`, linked with
  `-Wl,--version-script=` pointing at `rules_fuchsia`'s `driver.ld`, against
  `@fuchsia_sdk//pkg/driver_runtime_shared_lib`. It returns the providers
  `fuchsia_driver_component` consumes (modeled on `fuchsia_cc.bzl`, with
  `install_root = "driver/"`).
- The restricted-symbols check and an exported-symbols test.
- `drivers/simple_rust/`: the source copied from `examples/drivers/simple/rust` at the
  revision, plus its checked-in `.cml`. A placeholder `.bind` builds now; I3 sets the
  real one.

**Out of scope:** binding on the emulator (M11).

### Implementation steps
1. Write the rule and the providers, and package `drivers/simple_rust:pkg`.
2. A `sh_test`/Python test using `llvm-readelf --dyn-syms` asserts that
   `__fuchsia_driver_registration__` is the only exported defined symbol.
3. Wire `rules_fuchsia`'s restricted-symbols check as a build action.
4. **`DT_NEEDED` reference (see the Design coverage gap):**
   1. List the Rust drivers in the `core.x64` product bundle.
   2. Extract one and compare its `DT_NEEDED` with pilot 1's.
   3. Report differences.
5. If A3 fails (Rust `std` imports a restricted symbol), compare with the in-tree Rust
   driver config (the brief notes `//build/config/rust:bootfs`). Record the fix as a
   decision.

### Acceptance criteria
- [ ] `bazel build --config=fuchsia_x64 //drivers/simple_rust:pkg` and the arm64
  equivalent produce a driver package.
- [ ] The exported-symbols test passes for both targets.
- [ ] The restricted-symbols check passes for both targets.
- [ ] `DT_NEEDED` comparison recorded; any library absent from the reference driver is
  explained or removed. The owner confirms this reading of R7 (see gap).

### Testing and review
- Verify with `bazel test //drivers/simple_rust/...` under both configs.
- Review focus: link flags against `driver.ld`, provider compatibility with
  `fuchsia_driver_component`, and that no test is weakened to pass.
- Review method: `review-swarm` if available (the review spans rule, link and
  packaging); otherwise inherit.

### Session sizing
Starts from brief §3.3, W6, and upstream `fuchsia_cc.bzl`. The main uncertainty is A3.
Split point: the rule plus the symbol tests first, then the `DT_NEEDED` comparison.

### Evidence and findings
Status: pending · Evidence: [M10](evidence/M10.md) · Notebook: [M10](notebook/M10.md)

---

## I3 — Emulator bind target for pilot 1

**Design coverage:** I3 (blocks R8a's "binds"). **Dependencies:** M3.
**Lead (found 2026-09-27, not yet verified at this release):**
`fuchsia-cloud-dev`'s `qemu_edu` driver binds on `core.x64` `33.20260919.6.1` under TCG
with this rule:

```
composite qemu_edu;
using fuchsia.acpi;
using fuchsia.pci;
primary parent "pci" { fuchsia.BIND_PCI_VID == 0x1234; fuchsia.BIND_PCI_DID == 0x11e8; }
optional parent "acpi" { fuchsia.BIND_PROTOCOL == fuchsia.acpi.BIND_PROTOCOL.DEVICE; }
```

The PCI bus publishes composite node specs, so a non-composite rule registers but never
binds. Both bind libraries are in the SDK.
**Evidence to collect:** at the lock's release, confirm the edu device appears
(`ffx driver list-devices -v`, with the QEMU `-device edu` flag used by
`fuchsia-cloud-dev`), and that the rule above still compiles against this IDK's bind
libraries.
**Exit:** a `.bind` file for `drivers/simple_rust`, using only IDK bind libraries, plus
the emulator command line that adds the device, both recorded in `docs/evidence/I3.md`.
**Note for M11:** the edu device is owned by no in-tree driver on `core.x64`. If
`qemu_edu` from `fuchsia-cloud-dev` is also registered, the two compete; register only
the pilot.

---

## M11 — Pilot 1 binds on the emulator

**Design coverage:** R8a. **Dependencies:** M10, I3, M3.
**In scope:**
- The I3 `.bind` in `drivers/simple_rust`.
- Any change to the driver's `Start` needed for a composite parent. It is recorded as
  a patch-like diff against upstream source, in the evidence.
- `scripts/emu driver //drivers/simple_rust:pkg`.

**Out of scope:** device I/O; the pilot only needs to bind and log.

### Implementation steps
1. Apply the I3 bind rule, rebuild and register (`ffx driver register`; the harness
   reboots before re-registering, per `fuchsia-cloud-dev` workaround 6).
2. Check `ffx driver list`, `ffx driver list-devices -v` and `ffx log`.
3. Record the full command sequence in the evidence so G1 can replay it.

### Acceptance criteria
- [ ] `ffx driver list` shows the overlay's package URL loaded.
- [ ] `ffx driver list-devices -v` shows it bound to the edu node (or the node I3
  chose).
- [ ] The driver's start log line appears in `ffx log`.
- [ ] Emulator and package come from the same `sdk_version` (C3), shown in the evidence.

### Testing and review
- Review focus: C3, the driver diff against upstream `simple/rust` (only what binding
  requires), and a replayable sequence.

### Session sizing
Small, if I3 is done. The main risk is a start-time failure in the Rust runtime (for
example a missing `DT_NEEDED` at load); the M10 comparison is where to look.

### Evidence and findings
Status: pending · Evidence: [M11](evidence/M11.md) · Notebook: [M11](notebook/M11.md)

---

## G1 — Milestone 1 gate

**Design coverage:** R1–R7, R8a together (brief "Done (milestone 1)").
**Dependencies:** M11.
**Checks (on a fresh clone in a fresh container):**
1. `uv run pytest` and `scripts/regen.py --check`.
2. `scripts/resolve_pins.py 33.20260927.4.1` leaves `overlay.lock.json` unchanged.
3. `bazel build` and `bazel test` of `//...` under both configs, from an empty output
   base, with no `fuchsia.git` checkout on disk (outcome 1 of design §1).
4. Replay the M11 sequence: the driver loads and binds.
5. Record the disk used, build time, and closure counts (initial R12 data).

**Review:** `review-swarm` if available, otherwise a reviewer subagent over the whole
milestone-1 diff against design §1, §3 and §4.
**Exit:** all pass → milestone 1 declared in the plan and reported to the owner.

---

## I4 — Replacing the in-tree `aml-saradc` on the VIM3 (**lab**)

**Design coverage:** I4 (blocks R8b). **Dependencies:** none (lab access, VIM3 flashed
with the lock's release).
**Candidates (design §8.1):**
- `ffx driver disable` the in-tree URL
  (`fuchsia-pkg://fuchsia.com/aml-saradc#meta/aml-saradc.cm`), then register the
  overlay package and restart the node;
- build the overlay package into a board input bundle in place of the in-tree one.

It can be tried with the in-tree driver's own package re-registered under another URL,
so no overlay build is needed.
**Exit:** a repeatable sequence, run once on the VIM3, that leaves the substitute URL
bound to the ADC node. Recorded in `docs/evidence/I4.md`.

---

## M12 — Pilot 2 builds (closure, bindings, crates, driver checks)

**Design coverage:** R4, R5, R6, R7 for pilot 2; F8, D4 (arm64).
**Dependencies:** G1.
**In scope:**
- Re-run `closure.py` with `//src/devices/adc/drivers/aml-saradc`.
- Add the delta: crates.io crates; FIDL bindings (`fuchsia.hardware.adcimpl`,
  `fuchsia.hardware.platform.device`, …); vendored crates (`mmio`, `pdev`,
  `fdf_metadata`, `fuchsia-async`, `fuchsia-component`, `fuchsia-sync`, per the
  walker).
- `drivers/aml_saradc/` with its upstream `.bind` and `.cml`.
- R7's like-for-like `DT_NEEDED` check against `aml-saradc` extracted from the VIM3
  product bundle of this release.

**Out of scope:** deployment (M13); unit tests (M16).

### Implementation steps
1. Write `docs/closure/pilot2.json`, and diff it against pilot 1 in the evidence.
2. Extend `third_party/crates/`, the binding targets and the vendor list. Use `regen.py
   vendor` and overlays for crates without Bazel (brief A.1 marks `mmio`,
   `platform-device`, `metadata` as having none).
3. Copy the driver source and package it for `fuchsia_arm64` (and x64, per D4).
4. Extract `aml-saradc` from the VIM3 product bundle, then compare `DT_NEEDED` and
   exported symbols.

### Acceptance criteria
- [ ] `bazel build --config=fuchsia_arm64 //drivers/aml_saradc:pkg` and the x64
  equivalent succeed.
- [ ] Exported and restricted symbol tests pass for both.
- [ ] `DT_NEEDED` equals the in-tree VIM3 build's, or each difference is explained.
- [ ] `regen.py --check` is clean; pilot 1 still builds and its tests pass.

### Session sizing
Likely two sessions. Split before starting if the delta has more than about 10 new
crates: M12a covers the closure, crates and bindings; M12b covers the vendored crates,
the driver and the checks.

### Evidence and findings
Status: pending · Evidence: [M12](evidence/M12.md) · Notebook: [M12](notebook/M12.md)

---

## M13 — Pilot 2 binds on the VIM3 (**lab**)

**Design coverage:** R8b. **Dependencies:** M12, I4.
**Steps:**
1. Flash the VIM3 with the lock's release.
2. Apply the I4 sequence with the overlay package.
3. Verify binding.
4. Read an ADC channel through `fuchsia.hardware.adc`. The read method is to be
   discovered: an in-tree tool, or a small component.

### Acceptance criteria
- [ ] `ffx driver list-devices -v` shows the overlay's package URL bound to the ADC
  node.
- [ ] An ADC read returns a value, and the command and output are in the evidence.
- [ ] The in-tree driver is not bound at the same time.

**Blocked outside the lab:** unavailable hardware leaves this `blocked`, not complete.

### Evidence and findings
Status: pending · Evidence: [M13](evidence/M13.md) · Notebook: [M13](notebook/M13.md)

---

## M14 — `regen.py` end to end and the closure report

**Design coverage:** R10 (one command, failure behavior), R12, design §4.4.
**Dependencies:** M12.
**In scope:**
- `scripts/regen.py <sdk-version>` runs:
  1. `resolve_pins`;
  2. crates (the M6 `crate_universe` step, restricted to the walker's closure);
  3. bindings;
  4. vendor;
  5. closure report;
  6. `bazel build` + `bazel test`, both configs.

  It works in a scratch tree and replaces `vendor/`, `third_party/crates/` and the lock
  only after the build passes.
- `docs/closure/<sdk-version>.json`: crates, line counts, patches applied, licenses,
  build time.

**Out of scope:** running for a new release (M15); CI (M17).

### Acceptance criteria
- [ ] `regen.py 33.20260927.4.1` on a clean tree produces no diff.
- [ ] A renamed upstream crate path (simulated in pytest) stops the run, naming it.
- [ ] A failing patch stops the run, naming the patch and file.
- [ ] A failed build leaves the committed tree and lock untouched (pytest with stubs,
  plus one live run with a deliberately broken patch).
- [ ] The closure report validates against a small JSON schema in pytest, and lists
  licenses.

### Testing and review
- Review method: `review-swarm` if available (scripts, failure recovery, report);
  otherwise inherit.

### Evidence and findings
Status: pending · Evidence: [M14](evidence/M14.md) · Notebook: [M14](notebook/M14.md)

---

## M15 — A second release regenerates with zero manual edits

**Design coverage:** R10 check, R12 (per release), C3. **Dependencies:** M14; a newer
release than `33.20260927.4.1` exists (check `LATEST_LINUX`).
**Steps:**
1. `regen.py <next-version>`.
2. Commit the result as one reviewable diff.
3. Rebuild the emulator at that release and re-run the M11 sequence.

### Acceptance criteria
- [ ] The run succeeds with no edit to any file outside what `regen.py` writes. If a
  patch or overlay needs changing, the milestone fails. The fix goes to
  `regen.py`/patches and the run is repeated from a clean tree.
- [ ] Pilot 1 still binds on the emulator of the new release.
- [ ] A closure report exists for both releases, and the diff between them is summarized
  in the evidence (RFC evidence per design §1).

### Evidence and findings
Status: pending · Evidence: [M15](evidence/M15.md) · Notebook: [M15](notebook/M15.md)

---

## M16 — Driver unit tests (R9)

**Design coverage:** R9, D5. **Dependencies:** M12, M3.
**In scope:**
- A test variant of `fuchsia_rust_driver` (upstream's `-test-staticlib` pattern) plus
  the Rust `fdf` test harness crates it needs (from the walker's `test_deps`, which
  M6's walker skipped).
- `aml-saradc`'s own `#[cfg(test)]` tests packaged as a test component, run on the x64
  emulator.
- `scripts/emu test`, ported from `fuchsia-cloud-dev`'s `dev test` (build, publish,
  `ffx test run` each component, extra arguments such as `--realm` passed through);
  M3 did not port it.

### Acceptance criteria
- [ ] `scripts/emu test //drivers/aml_saradc:tests` passes every upstream test, with
  the count equal to the upstream test count at the revision.
- [ ] Production builds are unchanged: the M12 symbol tests still pass.
- [ ] Every `with_unit_tests = True` or `with_host_unit_tests = True` under `vendor/`
  yields a `<name>_test` target; none is silently lost (M4 left these attributes
  accepted but ignored; M4 review finding 4).

### Session sizing
Split point: the test rule with one trivial test, then the `aml-saradc` suite.

### Evidence and findings
Status: pending · Evidence: [M16](evidence/M16.md) · Notebook: [M16](notebook/M16.md)

---

## M17 — CI job in `fuchsia-ci`

**Design coverage:** R11. **Dependencies:** M15; the placement of the C++ out-of-tree
job (design §8.3). **Repository:** `curtisgalloway/fuchsia-ci`, attached for this
milestone.
**Steps:**
1. A job that, for each newly mirrored release, runs `regen.py <version>` in a scratch
   clone of this repo and records pass/fail and the closure report path in the
   `fuchsia-ci` DB.
2. It does not push to this repo (design §6: committed state changes only by reviewed
   commit).

### Acceptance criteria
- [ ] One release is processed end to end by the job and visible in the dashboard.
- [ ] A failing run records the failing stage and the `regen.py` message.

**Decision needed before start:** where the job lives relative to the C++ job.

### Evidence and findings
Status: pending · Evidence: [M17](evidence/M17.md) · Notebook: [M17](notebook/M17.md)

---

## G2 — Final system verification

**Design coverage:** all of §1 outcomes and R1–R12. **Dependencies:** M13–M17.
**Checks:**
1. The G1 checks at the latest regenerated release.
2. Pilot 1 on the emulator.
3. Pilot 2 on the VIM3 at the same release (**lab**).
4. Unit tests.
5. The CI job's latest record.
6. Closure reports for at least two releases.
7. A license audit of `vendor/` and `third_party/crates/`.

**Review:** full-diff review against the design, by the method in Conventions.
**Exit:** every design §1 outcome is shown, with evidence links.

---

## Risks (plan-level; design §8.2 still applies)

| Risk | Affects | Mitigation |
|---|---|---|
| Cloud disk: about 30 GB free. `fuchsia-cloud-dev`'s cache is about 15 GB; this repo adds the Rust toolchain, crates and bindings | M3 onward | Record disk at M2 and M3. Share one Bazel output base. Drop `rules_python`-only deps. If still tight, emulator milestones may need a lab machine or a larger environment. **Measured at M2:** Bazel caches about 20 GB (extracted IDK 13 GB, of which `obj/` 8.3 GB; repository cache 3.8 GB); 9 GB free afterwards. **Response:** constraint C6 and milestone M2a (owner direction 2026-09-27). **After M2a:** Bazel caches 7.7 GiB, total 8.2 GiB of the hosted 25 (peak about 10.8 GiB during a fresh IDK fetch); about 17 GiB left for M3. **After M3:** the emulator adds 0.5 GiB (bundle 0.36 GiB); total 8.8 GiB, peak about 9.6 GiB during a clean-slate fetch |
| TCG emulation is slow | M11, M16 | Budget from `fuchsia-cloud-dev`'s measurements (about 1 min boot, about 2 min driver reload) |
| I1 finds no anonymous mapping | everything | Stop and escalate at I1; do not guess a revision |
| Closure larger than the plan's split thresholds | M6, M8, M9, M12 | Split thresholds are stated per milestone; split before starting |

## Discovered work / backlog

- **Disk before M3 (found in M2) — decided:** the owner requires the hosted profile
  (30 GB); became constraint C6 and milestone M2a (done: 8.2 GiB of 25 after M2a).
- **Bazel version as a lock field (M14).** fuchsia.git pins Bazel in
  `manifests/jiri.lock` (`fuchsia/third_party/3pp/bazel`); `resolve_pins.py` could
  record it so `.bazelversion`/`scripts/bazel.sha256` follow the release automatically.
- **Hermetic host C toolchain.** Host Rust links with the system gcc; a clang host
  toolchain from `@fuchsia_clang` would match upstream.
- **`-pie` linker warning** on every Fuchsia Rust link (from the cc toolchain's flags).
- **Download allowlist as a standing check.** M2 verified with
  `--experimental_downloader_config` (allow BCR, github.com, CIPD, GCS,
  static.crates.io); committing it would catch new unpinned hosts, but M5's crates may
  add hosts. (M5 added only static.crates.io, at fetch time, pinned by SHA-256.)

- **Product bundle pinned by hash — decided and done in M3.** Upstream pins none of the
  `core.x64` bundle's files by content; owner decision 2026-09-27: "yes, pin the bundle
  by hash". The lock's `product_bundle` field (digest over every file's SHA-256) is
  written by `resolve_pins.py` (streams ~364 MB more per resolve) and checked by
  `scripts/emu`.
- **Emulator disk image growth (found in M3).** The instance's `fxfs.sparse.blk` is a
  10 GiB sparse file (133 MB allocated after boot); heavy guest writes could grow the
  `emulator` bucket toward 10.5 GiB, still within the hosted 25 GiB with today's
  caches. Watch it in M11/M16 evidence.
- **`scripts/emu driver` is untested (M3).** Ported from `dev` (including the reboot
  before re-registering), but there is no driver package before M10; M11 exercises it.
- **`fuchsia-cloud-dev` overlap.** `fuchsia-cloud-dev` already solves emulator bring-up
  in cloud containers. After M3, consider whether its `dev` tool and this repo's
  harness should share code. Not needed for milestone 1.
- **RealmBuilder at HEAD (found in M2a review; for M16).** `packages/realm_builder_server`
  in this IDK has variants only for numbered API levels, none for HEAD, so RealmBuilder
  and driver-test-realm tests built at HEAD need another route (not caused by the trim).
- **Other Rust drivers (design F10).** `aml-rtc` and `virtio-gpu-display` are
  candidates for a third pilot or for R7 reference comparisons (see M10).
- **Making `fuchsia-cloud-dev` more useful (owner interest, 2026-09-27).** Its README
  now lists its limits (x64 only, prebuilt image, `edu` only, SDK pin not published for
  every release, C++ only). Follow-ups this project could feed:
  - Follow the newest release by pinning the IDK and `rules_fuchsia` as M1 does,
    instead of the `fuchsia-bazel-rules` CIPD package.
  - Offer this overlay as a Bazel module there for Rust, after G1.
  - Add QEMU devices beyond `edu` for driver work (one `-device` argument each).
  - Take QEMU from the IDK's `tools/x64/qemu_internal` (the release's own pin, found in
    M3) instead of a separate `manifests/qemu.ensure`.
  - Unverified: a `core.arm64` product bundle under TCG for arm64 at run time;
    in-container product assembly for replacing shipped drivers (disk may not allow).
  - Environment profiles (C6): its README limits become the hosted profile's limits;
    other environments (KVM, more disk, attached hardware) relax them.
- **`vendored = True` in M5's label rewrite (found in M4) — decided.** Upstream
  `BUILD.bazel` files call `rustc_library` without it. The overlay builds them at HEAD
  (upstream: PLATFORM) with `-Dwarnings` and the ported lints
  (`unused_crate_dependencies = warn`), which risks unused-import/crate errors. Decision
  (orchestrator, after M4 review): M5's rewrite sets `vendored = True` on every target
  under `vendor/`; now in M5's steps. Done in M5 (`regen.py`; checked by `tests/vendor`).
- **Host FIDL bindings and host cfgs at one level (found in the M4 review; for M8/M16).**
  Host code builds with the PLATFORM cfgs, and in-scope crates branch on PLATFORM
  (`src/lib/fuchsia-fs`, e.g. `src/node.rs:156`; 15 files under `src/storage/lib/vfs`).
  Host FIDL bindings must be generated at the same level as host cfgs (PLATFORM), or the
  host cfgs move to HEAD. M8 decides, with a test. **Decided in M8a:** as upstream, IR
  and bindings follow the target API level (host: PLATFORM =
  `runtime_supported_api_levels`); host cfgs stay at PLATFORM. Tested by
  `tests/fidl` ([M8 evidence](evidence/M8.md)).
- **Unit-test attributes are no-ops until M16 (found in M4).** `rules/rustc.bzl` accepts
  `with_unit_tests`, `with_host_unit_tests`, `test_deps` so upstream files load (e.g.
  `zx-types` sets `with_host_unit_tests = True`), but generates no test target. M16
  ports `generate_unit_tests.bzl` and the host/Fuchsia test wrappers.
- **Script the API-level goldens (found in M4; for M14).** `tests/api_level/golden/`
  came from upstream's own `rustc_api_level.bzl` in a scratch workspace (recipe in
  [M4 evidence](evidence/M4.md)). The fixtures are pinned, so nothing breaks per release;
  a script would let `regen.py` refresh fixtures and goldens together. After each
  release bump it should also check that the IDK's `version_history.json` has the same
  level set as the source tree's (the port's correctness depends on it), and check the
  live `@fuchsia_api_levels` output, not only the pinned fixtures (M4 review finding 5).
- **Design §4.2 "Rust rules" wording (found in M4).** It has the wrapper adding the
  API-level cfgs; upstream (and now the overlay) adds them in the toolchain. An
  orchestrator amendment, not an M4 change.
- **crates.io route for M6 (found in M5) — decided.** M5 created `third_party/crates/`
  without running crate_universe: regen.py reuses upstream's crate_universe-generated
  `third_party/rust_crates/vendor/<crate>/BUILD.bazel` files and downloads each `.crate`
  from static.crates.io by the release `Cargo.lock`'s SHA-256 (`@rust_crates`).
  Decision (orchestrator, after the M5 review; option A): M6 continues this route, and
  the patched crates (`forks/libc`, `ask2patch/memchr`, …), whose sources exist only in
  fuchsia.git, are vendored from fuchsia.git by regen.py and committed (D6). The
  orchestrator amends design §4.2 "Third-party crates". `zx` (deferred from M5)
  needs `libc` (`forks/libc-0.2.189`), `bstr` → `ask2patch/memchr`, `bitflags` (+
  `serde_core` under upstream's features) and `static_assertions`; add
  `sdk/rust/zx upstream` to `vendor/crates.txt` and `//vendor/fuchsia/sdk/rust/zx` to
  `tests/vendor/BUILD.bazel`.
- **Fuchsia's license is BSD-2-Clause (found in the M5 review) — fixed in M5.** The repo
  had `LICENSES/BSD-3-Clause.txt` with Fuchsia's 2-clause text since M2; renamed and
  every Fuchsia-derived label corrected ([M5 evidence](evidence/M5.md)). Design C4 says
  "BSD-3"; the orchestrator amends it.
- **`regen.py` closure over-approximates `select()` (found in M5).** It follows every
  label in an upstream crate BUILD file, including branches for platforms the overlay
  does not build; with M6's larger set it may fetch crates never compiled. `@rust_crates`
  is also one repository (all crates download together).
- **Classify driver protocols by FIDL availability; experiment with our own FIDL
  (owner interest, 2026-09-27).** The overlay only generates bindings for FIDL that
  exists. For each candidate driver or bus, classify every parent protocol as:
  1. *SDK FIDL:* `partner` category, in the IDK; works today (both pilots).
  2. *Non-SDK FIDL:* in `fuchsia.git` (`internal`/`platform` category) but not the IDK.
     Bindings can be generated from `.fidl` sources fetched at the release revision
     (the route M8 uses for `fuchsia.sys2`), but the interface is not a published
     contract; record each such library in the closure report as RFC evidence.
  3. *No FIDL:* the parent serves children only over Banjo (out of scope, C2) or not
     at all; needs a new protocol and a parent-driver migration upstream.
  Also check that the parent or board actually routes the service to the child's node.
  The survey would also inform `fuchsia-ci`'s C++ out-of-tree bus-driver work.
  Follow-up experiment: define our own FIDL library in this repo (compiled with the
  IDK's `fidlc`, bindings via `rules/fidl_rust.bzl` from M8) for a case-3 interface,
  served by a parent driver we control (for example an overlay driver on QEMU's `edu`
  device, publishing a child node), to learn what adding an interface out of tree
  takes. Earliest after M11 (needs M8's rule and a working pilot 1).

- **Build argument in `fuchsia-sync` (found in M6a; for M9) — decided.**
  `src/lib/fuchsia-sync/BUILD.bazel` loads `fuchsia_sync_detect_lock_cycles` from
  `@fuchsia_build_info//:args.bzl` (a load regen.py does not map) and adds
  `forks/tracing-mutex-0.3.2` when it is true (GN default: `compilation_mode == "debug"`).
  Decision (orchestrator, after the M6a review): the overlay's value is false. closure.py
  applies it (`OVERLAY_ARGS`); M9 maps the load to false; M6b does not need
  `tracing-mutex`. **Done in M8a** (`fuchsia-sync` is in the FIDL runtime):
  `regen.py` maps the load to `//rules:build_info.bzl`, and a patch empties
  `DETECT_LOCK_CYCLE_DEPS`.
- **FIDL binding flavors and template deps (found in M6a; for M8).** Every `rust`
  binding depends on its `rust_common` crate and every `rust_next` on its
  `rust_next_common` (pilot 1: `rust` 23 / `rust_common` 23 / `rust_next` 19 /
  `rust_next_common` 19 / `rust_flex` 1, `fuchsia.io` for `vfs`). Libraries with
  `contains_drivers` (`fuchsia.driver.framework`, `fuchsia.power.broker`) add
  `fidl_driver` and `sdk/lib/driver/runtime/rust` to the `rust` flavors (with
  `enable_rust_drivers`) and `sdk/lib/driver/runtime/rust/fidl` to `rust_next`. A FIDL
  dep on `//zircon/vdso/zx` is the `zx-types` crate. M8's rule must reproduce these;
  `closure.FIDL_FLAVORS` is the transcription from `build/fidl/fidl.gni`,
  `build/rust/fidl_rust.gni` and `build/rust/fidl_rust_next.gni` at the release.
- **The pilot's bind library bindings (found in M6a; for I3/M10).** `examples/drivers/
  simple/rust:driver` depends on `//src/devices/bind/fuchsia.test:fuchsia.test_rust`
  (Rust bindings of a bind library, in the IDK). With I3's hand-written bind rule the
  overlay's copy may drop it; otherwise a rule for bind-library Rust bindings is needed.
- **`select()` over-approximation measured (M6a).** For pilot 1's 121 crates, following
  every `select()` branch adds no crate (`crates_io_transitive_unfiltered_select` = 121);
  closure.py filters to the overlay's platforms anyway.
- **closure.py limits (found in M6a; for M14).** It does not run imported templates:
  only the FIDL binding templates are modelled, by a hand-transcribed table that a later
  release could invalidate (M14 could check those three files' blob IDs and fail on a
  change). Build arguments two imports deep would be UNKNOWN; `current_cpu` is UNKNOWN
  for Fuchsia. None mattered for pilot 1 (0 gaps, 0 UNKNOWN conditions). M14 folds the
  walker into `regen.py` and could let it drive the crate roots.

- **Incompatible targets drop out of `//...` silently (found in M6b) — addressed for
  the crate list.** A filegroup with one member incompatible under a config is skipped
  by `//...` without an error, as are Fuchsia-only targets on host. Decision
  (orchestrator, M6b review): the three build checks name `//third_party/crates:aliases`
  (all configs) and `:host_all` (host) explicitly, so an incompatible member fails
  loudly. Other targets (e.g. a future driver package) are still skipped silently; add
  them to the checks the same way when they matter.
- **crates.io roots by hand (found in M6b; for M14).** `vendor/crates_io.txt` copies
  `pilot1.json`'s `crates_io.direct` (pytest keeps them equal); when M14 folds the
  walker into `regen.py`, the closure can drive the roots, and pilot 2's aliases join.
  A new patched crate also needs a hand-written `REUSE.toml` annotation (reuse lint
  fails until then).

- **Generator arguments for M8 (found in M7).** `tests/fidlgen/fidlgen.bzl` (`FLAVORS`)
  runs both generators with upstream's arguments (`build/rust/fidl_rust.gni`,
  `fidl_rust_next.gni`): the release's rustfmt, `//vendor/fuchsia:rustfmt.toml`,
  `--use_common`/`--common` and `--config configs/{fuchsia,common}.json`/`--common-lib`.
  `--api-coverage=true` and `--include-drivers` are per-library GN settings
  (`enable_api_coverage`, `contains_drivers`); M8's rule must carry them.
- **FIDL golden fixtures per release (found in M7; for M14/M15).** `tests/fidlgen/testdata`
  (5 fidlc IR goldens, 10 `fidlgen_rust_next` goldens) is copied by hand, like M4's
  API-level fixtures (recipe and blob IDs in [M7 evidence](evidence/M7.md)); after a
  release bump the golden tests fail until it is refreshed. Script it with the M4 item
  (the `fidlgen_rust` goldens already refresh through `regen.py`).
- **`bazel mod` pollutes `MODULE.bazel.lock` (found in M7).** `bazel mod graph` and
  `mod show_extension` evaluate every module extension and record the results (pip,
  pybind11, rules_fuzzing, crate_universe's `cu_nr`: ~3,000 lines); builds do not need
  them. Check the lockfile diff before committing after any `bazel mod` command.
- **rules_go `go_sdk` facts (found in M7) — decided.** rules_go's extension asks
  `go.dev/dl/?mode=json` for its default SDK's hashes (tolerating failure) unless
  `MODULE.bazel.lock` holds them as `facts`; M7 keeps the facts so builds never contact
  go.dev. A rules_go bump brings a new default SDK version and one more metadata request
  on the next lockfile update.

- **Driver transport: M8b or M9? (found in M8a; question for the orchestrator).** The
  `rust` flavor's driver transport (`fidl_driver`, `fdf`) and the `rust_next` crates of
  `fuchsia.driver.framework`/`fuchsia.power.broker` (`fdf_fidl`, unconditionally) need 10
  in-tree crates without upstream Bazel (`fdf*`, `libasync*`), which M9's scope also
  names. M8b's entry takes them with a split point; the alternative is M8b = `rust_next`
  for the 17 other libraries only, and M9 vendors the 10 crates and then enables the
  transport. Recommendation: the second (M9 already plans those overlays), if M9's
  sizing allows.
- **Host FIDL runtime not built (found in M8a).** `fidl`, `fuchsia-async` and
  `fuchsia-sync` are Fuchsia-only by patch: on host they need
  `//src/lib/fuchsia-emulated-handle`, `forks/tokio-1.53.1` (sources only in fuchsia.git),
  `futures-lite`, `parking_lot(_core)`, none in pilot 1's closure. Host bindings are
  generated (at PLATFORM) but not compiled. Needed before any host FIDL use, e.g. M16's
  host unit tests (`with_host_unit_tests` on these crates).
- **`test_deps` count as crate roots in `regen.py` (found in M8a; for M16).** Crate roots
  are every `@rust_crates` string in a vendored BUILD file, so test-only deps outside the
  closure would be fetched; `fuchsia-async`'s patch drops its `test_deps` for that reason.
  M16 must revisit the patch (and the root rule) when it builds unit tests.
- **`fidl` is visible only to upstream's packages (found in M8a; for M10).** The
  rewritten visibility is `//rules:__subpackages__`, `//vendor/fuchsia/{src,sdk/lib,
  examples,tools,…}:__subpackages__`. The overlay's own driver packages (design:
  `drivers/`) are not in it; M10 needs a patch or a visibility mapping for
  `//drivers`, or to depend on `fidl` only through vendored crates. Same for
  `rust_constants` and `fuchsia.power.broker`'s bindings.
- **Bazel caches near their budget (found in M8a).** After M8a: Bazel 10.81 of 12 GiB
  (total 11.71 of 25). M8b and M9 add about 30 in-tree crates for three configs; watch
  the disk report, and consider pruning `bazel-out` configs (`-ST-` transition dirs) or
  raising the Bazel group's share if it tips over.
- **`regen.py` crate stage with no crates (found in M8a) — fixed in M8a.**
  `generate_crates` left `crates_json` unset when no crate is named at all
  (`UnboundLocalError`); only a test tree hit it.

## Next session

- Current milestone and status: **M8a implemented, review pending** (M8 split into M8a
  `rust` and M8b `rust_next`, accepted in advance by the orchestrator). Branch `ms/M8`
  from `9a453a8`; `wip` commit `5450c75` and later working-tree changes; the checkpoint
  commit `overlay: M8a — FIDL Rust binding rule, rust flavor` follows the review.
- Completed work and evidence: [M8 evidence](evidence/M8.md) (Review section pending).
- Remaining work, blockers, and decisions: the orchestrator's review and fixes; the
  backlog question "Driver transport: M8b or M9?". Unchanged: the R7 reading for pilot 1
  (before M10); M17 placement.
- Context boundary: normal.
- Resume action: after M8a lands, begin **M8b** (I3 can run beside it).
- Read first for M8b: the M8b entry, [M8 evidence](evidence/M8.md) ("Findings for later
  milestones"), `rules/fidl.bzl`, `rules/fidl_rust.bzl`, `tests/fidlgen/fidlgen.bzl`,
  `tests/fidl/BUILD.bazel`, the backlog items "Driver transport: M8b or M9?" and "Host
  FIDL runtime not built", [notebook index](notebook/index.md).
