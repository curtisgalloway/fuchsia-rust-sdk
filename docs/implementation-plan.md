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

**Project checks** (none exist yet; each is created by the milestone named):

| Check | Command | Created in |
|---|---|---|
| Script tests | `uv run pytest` | M1 |
| Build, x64 | `bazel build --config=fuchsia_x64 //...` | M2 (config names proposed) |
| Build, arm64 | `bazel build --config=fuchsia_arm64 //...` | M2 |
| Binary checks | `bazel test //...` (symbol and `DT_NEEDED` tests) | M10 |
| Vendor drift | `scripts/regen.py --check` | M5 |
| License headers | `reuse lint` or an equivalent SPDX check (to be chosen in M1) | M1 |

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
  Material design changes need a new gate before the milestones they affect.
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
| I1 | Documented anonymous lookup: SDK version → `fuchsia.git` revision | — | cloud | pending |
| M1 | Repo scaffold + `resolve_pins.py` writes `overlay.lock.json` (R1) | I1 | cloud | pending |
| M2 | Bazel workspace + Fuchsia Rust toolchains; a Rust binary links for x64 and arm64 (I5, R2) | M1 | cloud | pending |
| M3 | Emulator harness at the lock's release; the M2 binary runs on it (R2) | M2 | cloud (emulator) | pending |
| M4 | `rustc_*` rules with API-level cfgs (R3) | M2 | cloud | pending |
| M5 | Vendor stage of `regen.py` + `--check`; `zx-types`, `zx-sys`, `zx` build (R6 mechanism, R2) | M4 | cloud | pending |
| M6 | Pilot 1 closure measured (D8) + its crates.io crates build (R4) | M5 | cloud | pending |
| I2 | Prebuilt `fidlgen_rust` / `fidlgen_rust_next`: published or not | — | cloud | pending |
| M7 | Both FIDL generators available as Bazel host tools (R5 tools) | I2, M6 | cloud | pending |
| M8 | `fidl_rust.bzl`, `rust` + `rust_next` flavors; pilot 1 FIDL closure compiles (R5) | M7 | cloud | pending |
| M9 | Pilot 1's in-tree crates vendored; `fdf`, `fdf_component` build (R6) | M8 | cloud | pending |
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

Critical path to milestone 1: I1 → M1 → M2 → M4 → M5 → M6 → M7 → M8 → M9 → M10 → M11 → G1.
M3, I2 and I3 run beside it. I4 needs only the lab, so it can run any time before M13.

## Design coverage

| Requirement | Milestones | Verification |
|-------------|------------|--------------|
| R1 pinned lock | I1, M1 (M14 folds into `regen.py`) | pytest with stubbed network; two runs byte-identical; live run for `33.20260927.4.1` |
| R2 toolchain | M2 (link), M3 (runs), M5 (`zx*` build) | both configs build; binary prints on emulator |
| R3 API-level cfgs | M4 | test crate takes the `HEAD` branch on both targets |
| R4 crates.io crates | M6 (pilot 1), M12 (pilot 2) | every closure crate builds for both targets; proc macros for host |
| R5 FIDL bindings | M7 (tools), M8 (rule, pilot 1), M12 (pilot 2 libraries) | bindings for every closure library compile for both targets, both flavors |
| R6 vendored crates | M5 (mechanism), M9 (pilot 1), M12 (pilot 2) | named crates build for both targets; `regen.py --check` clean |
| R7 driver rule | M10 (pilot 1), M12 (`DT_NEEDED` vs in-tree `aml-saradc`) | `llvm-readelf` tests; restricted-symbols check |
| R8a pilot 1 | I3, M11 | `ffx driver list`, `list-devices -v`, `ffx log` on emulator |
| R8b pilot 2 | I4, M13 | `list-devices -v` shows overlay URL; ADC read |
| R9 unit tests | M16 | `aml-saradc` tests pass on emulator |
| R10 regeneration | M14, M15 | two consecutive releases, zero manual edits; failure messages name the patch or crate |
| R11 CI | M17 | one release processed end to end, visible in dashboard |
| R12 closure report | M14 (M15 confirms per release) | report file per release, schema-checked in pytest |
| I5 (rules coupling) | M2 step 1 | empty workspace loads both rule sets |

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

**Design coverage:** I1 (blocks R1). **Dependencies:** none.
**Question:** which published, anonymously readable artifact maps `33.20260927.4.1` to
a `fuchsia.git` commit?
**Evidence to collect (in order; stop at the first that works for two releases):**
1. The IDK's `meta/manifest.json`. Stream it without downloading 3 GB:
   `curl -sS https://storage.googleapis.com/fuchsia/development/33.20260927.4.1/sdk/linux-amd64/core.tar.gz | tar -xzf - meta/manifest.json`.
   Look for a revision or `jiri` snapshot field.
2. The GCS release directory: list `gs://fuchsia/development/33.20260927.4.1/` over
   the JSON API (`https://storage.googleapis.com/storage/v1/b/fuchsia/o?prefix=development/33.20260927.4.1/&delimiter=/`),
   and look for `jiri.snapshot`, `source_manifest.json` or similar.
3. The Bazel SDK CIPD package: `fuchsia-cloud-dev` pins
   `fuchsia/sdk/core/fuchsia-bazel-rules/linux-amd64` by `git_revision:`. Check
   whether the SDK packages' CIPD tags (`git_revision`, `version`) link the version
   string to a commit.
4. Git tags or refs on `fuchsia.googlesource.com/fuchsia` named after the release
   (`git ls-remote … | grep 20260927`).
5. The Buildbucket recipes in `fuchsia-ci`'s `fuchsia-release-artifacts-ci-handoff.md`
   (needs that private repo attached).

**Exit:** a lookup that returns the revision for `33.20260927.4.1` and one earlier
release, documented in `docs/evidence/I1.md` with the exact requests. If none works
anonymously, stop and report. R1 and everything after it are blocked.
**Sizing:** half a session. If it resolves early, begin M1 in the same session only
with the owner's go-ahead (the one-milestone boundary still applies).

---

## M1 — Repo scaffold and pinned release lock

**Design coverage:** R1, C1, C4. **Dependencies:** I1.
**In scope:** repo basics; `scripts/resolve_pins.py`; `overlay.lock.json` for
`33.20260927.4.1`; pytest suite.
**Out of scope:** any Bazel file; `regen.py`.

### Implementation steps
1. Add `LICENSE` (Apache-2.0), `README.md` (one paragraph plus a link to
   design/plan), `.gitignore` (`bazel-*`, `.dev/`, `__pycache__`), and `pyproject.toml`
   for `uv` with `pytest` as a dev dependency. All carry SPDX headers.
2. `scripts/resolve_pins.py <sdk-version> [--out overlay.lock.json]`, with these steps:
   1. Get the revision by the I1 method.
   2. Fetch `manifests/toolchain` at that revision: `git fetch --depth 1` of that
      commit with a sparse, blobless checkout, or `git archive`-style reads through
      git. Never gitiles.
   3. Parse the two Rust packages and their `git_revisions:` version.
   4. Resolve instance IDs with CIPD `ResolveVersion` (brief App. B step 3). The host
      package is resolved for `linux-amd64`.
   5. Record the Bazel SDK / `rules_fuchsia` CIPD identifiers for that release; the
      method follows I1 step 3 and `fuchsia-cloud-dev/manifests/*.ensure`.
   6. Take the SHA-256 of `third_party/rust_crates/Cargo.lock` at the revision.
   7. Write the lock with sorted keys and a trailing newline, via temp file then
      `os.replace`.
3. The lock schema has one object per field, each with `value` and `source` (the URL
   or git path it came from, per R1). Proposed keys: `sdk_version`, `fuchsia_revision`,
   `rust_host`, `rust_target`, `bazel_sdk`, `rules_fuchsia`, `cargo_lock_sha256`.
4. `tests/test_resolve_pins.py`: HTTP and git are stubbed behind one small interface.
5. Commit `overlay.lock.json` for `33.20260927.4.1`.

### Acceptance criteria
- [ ] Two consecutive live runs produce byte-identical `overlay.lock.json`.
- [ ] Every field has a `source` naming its upstream artifact.
- [ ] If any lookup fails (stubbed 404 for CIPD, unknown version), the script exits
  non-zero naming the field, and an existing lock file is unchanged.
- [ ] `rust_host`/`rust_target` instance IDs match the brief's `3a8ffdbe…`/`4fe0f40e…`
  if the release still pins `c26ce708…,3493720e…`. Otherwise the difference is
  explained in evidence.
- [ ] `uv run pytest` passes; SPDX check passes.

### Testing and review
- Tests: happy path, each field's failure path, determinism (same stubs → same bytes),
  atomic write (simulate failure between temp write and replace).
- Verify with: `uv run pytest`; `uv run scripts/resolve_pins.py 33.20260927.4.1 && git diff --exit-code overlay.lock.json` (second run).
- Review focus: C1 (no credentials, no gitiles), the lock as the only per-release
  input, and a readable schema for M14.
- Review method: inherit.

### Session sizing
Starts from the design §4.2 "Pin resolution", brief §3.5–3.6 and App. B, and
`evidence/I1.md`. The main uncertainty is fetching one file at a commit without a
full clone; brief App. B's sparse clone is the fallback. Split point: land the lock
schema, the stubbed tests and the fields other than the Bazel SDK first, and add
`bazel_sdk`/`rules_fuchsia` in a follow-up.

### Evidence and findings
Status: pending · Evidence: [M1](evidence/M1.md) · Notebook: [M1](notebook/M1.md)

---

## M2 — Bazel workspace and Fuchsia Rust toolchains

**Design coverage:** I5, R2 (link half), D3, D4, C5, A2.
**Dependencies:** M1.
**In scope:**
- `MODULE.bazel` and `.bazelversion`, with Bazel matching the release's
  `sdk-samples/drivers`.
- `rules_fuchsia` + `@fuchsia_sdk` at the lock's version.
- `rules_rust` 0.69.0 with upstream's patch in `patches/rules_rust/`.
- `toolchain/`: a CIPD repository rule, plus `rust_toolchain()` targets for
  `x86_64-unknown-fuchsia`, `aarch64-unknown-fuchsia` and host.
- `.bazelrc` with `fuchsia_x64` / `fuchsia_arm64` configs.
- `examples/hello_rust/` (proposed): a `rust_binary` that calls into `libfdio.so`.

**Out of scope:** running on a device (M3); `rustc_*` wrappers (M4); any vendored crate
(M5).

### Implementation steps
1. **I5 first:** an empty workspace with both rule sets that resolves `@fuchsia_clang`
   and `@fuchsia_sdk`. Record the Bazel version and any `MODULE.bazel` conflicts.
   `fuchsia-cloud-dev/MODULE.bazel` is a working reference for the `rules_fuchsia`
   half.
2. Copy upstream's `rules_rust` patch from `fuchsia.git` at the lock revision (path from
   brief §3.4) with its license header. Apply it via `single_version_override(patches=…)`.
3. `toolchain/cipd.bzl` (proposed): a repository rule that downloads a CIPD instance by
   ID over anonymous HTTPS, then checks it by the content hash the instance ID encodes.
4. `toolchain/BUILD.bazel`: port `build/bazel/toolchains/rust/rust.BUILD.bazel`, and
   link through `@fuchsia_clang` with `@fuchsia_sdk//pkg/sysroot`.
5. Build `hello_rust` under both configs, and read its `DT_NEEDED` with `llvm-readelf`
   from `@fuchsia_clang`.

### Acceptance criteria
- [ ] `bazel build --config=fuchsia_x64 //examples/hello_rust` and `--config=fuchsia_arm64`
  both succeed from a clean output base.
- [ ] `llvm-readelf -d` shows `libfdio.so` in `DT_NEEDED`, and the ELF machine matches each
  target.
- [ ] Changing the instance ID in the lock by one character fails the fetch with a
  hash/ID error (then revert).
- [ ] A host-side `rust_binary` builds (proves the host toolchain for later proc macros).

### Testing and review
- Verify with the two build commands, `llvm-readelf -h -d` on each output, and the
  tamper test.
- Review focus: toolchain definitions against upstream's `rust.BUILD.bazel`, the link
  line (sysroot, clang target), nothing fetched outside the lock, and the patch
  carrying its license header.
- Record Bazel output-base size (disk budget; see Risks).

### Session sizing
Starts from the design §4.2 "Toolchain", brief §3.4–3.5, `overlay.lock.json`, and
upstream `rust.BUILD.bazel`. This is the highest-uncertainty build milestone (A2 and
I5). Split point: land I5 plus the host toolchain first (step 1–3 and the host binary),
then add the Fuchsia targets.

### Evidence and findings
Status: pending · Evidence: [M2](evidence/M2.md) · Notebook: [M2](notebook/M2.md)

---

## M3 — Emulator harness at the lock's release

**Design coverage:** R2 (runs on emulator), design §7 "Emulator" row, W7 of the brief.
**Dependencies:** M2.
**In scope:**
- `scripts/emu` (proposed name). It fetches QEMU and the `core.x64` product bundle for
  the lock's `sdk_version`, starts the emulator, and publishes a package. It also runs
  a component and registers a driver.
- The 6 container workarounds from `fuchsia-cloud-dev`'s README.

**Out of scope:** driver binding (I3, M11); the VIM3.

### Implementation steps
1. Read `fuchsia-cloud-dev/dev` and decide: port the needed functions into this repo,
   keeping its BSD notice on ported code (C4), or call it as a pinned external tool.
   Record the decision in the M3 chapter. Porting is the default, so one repo carries
   one lock.
2. The product-bundle and QEMU versions derive from `overlay.lock.json`, not a second
   pin.
3. Package `hello_rust` as a component with `rules_fuchsia`. Its `.cml` uses
   `LogSink` from `parent/diagnostics` (per `fuchsia-cloud-dev`).
4. `scripts/emu start`, then `scripts/emu run //examples/hello_rust:pkg`.

### Acceptance criteria
- [ ] The emulator boots the product bundle whose version equals the lock's
  `sdk_version`; show the `ffx target show` version.
- [ ] `hello_rust` runs and its line appears in `ffx log`.
- [ ] A second `scripts/emu start` with the bundle cached takes under 2 minutes.
- [ ] Setup failure (a blocked host) exits non-zero naming the host.

### Testing and review
- Verify with the commands above, recording boot time and total disk after setup.
- Review focus: no second version pin, workarounds commented with their reason, and
  license of ported code.

### Session sizing
Starts from `fuchsia-cloud-dev` README and `dev`, plus the lock. The main risk is disk:
that repo measures about 15 GB of Bazel cache, and this repo adds the Rust toolchain
(see Risks). Split point: land the boot and the version check first, then add
package run.

### Evidence and findings
Status: pending · Evidence: [M3](evidence/M3.md) · Notebook: [M3](notebook/M3.md)

---

## M4 — `rustc_*` rules with API-level cfgs

**Design coverage:** R3. **Dependencies:** M2.
**In scope:**
- `rules/rustc.bzl`: `rustc_library`, `rustc_proc_macro` and `rustc_binary` wrappers
  over `rules_rust`, ported from upstream `build/bazel/rules/rust/`.
- `--cap-lints` for vendored code.
- API-level cfg generation from the IDK's `version_history.json`, targeting `HEAD`.
- `tests/api_level/`, a test crate.

**Out of scope:** the test wrapper (`rustc_test`, R9 → M16); the driver rule.

### Implementation steps
1. Port `rustc_api_level.bzl`. The input is `version_history.json` from
   `@fuchsia_sdk`. Emit `--cfg=fuchsia_api_level_at_least="N"` for every supported
   level ≤ target, and `…_less_than` for the rest, exactly as upstream does. Record
   the upstream file and revision in a header comment.
2. Wrappers apply cfgs, edition default, and `--cap-lints=allow` when a `vendored = True`
   attribute (proposed) is set.
3. Test crate: `#[cfg(fuchsia_api_level_at_least = "HEAD")] const BRANCH: &str = "head";`
   and an `#[cfg(not(...))]` counterpart. A Bazel `rust_test` on host, or a build-time
   `static_assert`, checks the `HEAD` branch.

### Acceptance criteria
- [ ] The test crate builds for both Fuchsia targets and takes the `HEAD` branch
  (checked by a build assertion, not by inspection).
- [ ] The generated cfg list for a pinned `version_history.json` matches upstream's
  output for the same input (golden file from upstream's generator, or a hand-checked
  golden).
- [ ] A lint that is denied by default in first-party code is allowed under
  `vendored = True`.

### Testing and review
- Verify with `bazel build --config=fuchsia_x64 //tests/api_level/...` (and arm64) and
  `bazel test //tests/api_level/...`.
- Review focus: cfg semantics against upstream (off-by-one on `less_than`), and the
  handling of `HEAD`/`NEXT`/`PLATFORM` named levels.

### Session sizing
Small and well-bounded. It can share a session with M5's first steps only by owner
override. Starts from upstream `build/bazel/rules/rust/`.

### Evidence and findings
Status: pending · Evidence: [M4](evidence/M4.md) · Notebook: [M4](notebook/M4.md)

---

## M5 — Vendor stage of `regen.py`; `zx` crates build

**Design coverage:** R6 (mechanism and `--check`), R2 (`zx-types`, `zx-sys`, `zx`
build), D6, D9. **Dependencies:** M4.
**In scope:**
- `scripts/regen.py vendor` and `scripts/regen.py --check`. A vendor list file,
  `vendor/crates.txt` (proposed): upstream path → how its `BUILD.bazel` is made.
- Label rewriting for upstream `BUILD.bazel` files; `overlays/` and
  `patches/fuchsia/` application; `LICENSE`/`METADATA` carried.
- The first three crates: `sdk/rust/zx-types`, `sdk/rust/zx-sys` and `sdk/rust/zx`,
  all with upstream Bazel builds.

**Out of scope:**
- the crates.io repository (M6). `zx`'s crates.io deps (`bitflags`,
  `static_assertions`, `zerocopy`…) are either provided by the smallest possible
  `crate_universe` subset here, or `zx` alone waits for M6 (decide by inspection,
  record it).
- the full `regen.py` pipeline (M14).

### Implementation steps
1. Git access: sparse, blobless fetch of `fuchsia.git` at `fuchsia_revision` into a
   scratch directory outside the repo (brief App. B step 1).
2. Copy each listed crate directory to `vendor/fuchsia/<upstream path>/` (D9).
3. For crates with upstream `BUILD.bazel`, rewrite labels:
   - `//<path>` → `//vendor/fuchsia/<path>`
   - `//third_party/rust_crates:<x>` → the crate-universe label
   - upstream rule loads → `//rules:rustc.bzl`

   Otherwise, copy `overlays/<path>/BUILD.bazel`.
4. Apply `patches/fuchsia/<path>/*.patch` in order. A failing patch stops the run and
   names the patch and the file.
5. `--check`: regenerate into scratch and diff against `vendor/`; exit non-zero on drift.
6. pytest for label rewriting, patch failure and drift detection, using a tiny fake
   upstream tree.

### Acceptance criteria
- [ ] `regen.py vendor` reproduces `vendor/` byte-for-byte on a second run.
- [ ] `regen.py --check` passes on a clean tree, and fails naming the file after a
  one-byte hand edit in `vendor/`.
- [ ] A patch that no longer applies fails with the patch name and file (pytest).
- [ ] `zx-types` and `zx-sys` build for both Fuchsia targets. `zx` builds too, or is
  explicitly deferred to M6 with the reason recorded.
- [ ] Each vendored crate carries upstream `LICENSE` (C4).

### Testing and review
- Verify with `uv run pytest`, `scripts/regen.py --check`, and both build configs on
  `//vendor/fuchsia/sdk/rust/...`.
- Review focus: D6 (only generated content committed), D9 layout, determinism, and no
  network access at build time.

### Session sizing
Starts from the design §4.2 "Vendored crates", brief App. A.1 (the `zx*` rows) and
App. B. The main uncertainty is label-rewrite coverage for upstream Bazel files. Split
point: land the mechanism with `zx-types` alone, then add the other two.

### Evidence and findings
Status: pending · Evidence: [M5](evidence/M5.md) · Notebook: [M5](notebook/M5.md)

---

## M6 — Pilot 1 closure and its crates.io crates

**Design coverage:** D8, R4 (pilot 1 subset), R12 (closure data first produced).
**Dependencies:** M5.
**In scope:**
- `scripts/closure.py`: the brief's App. B walker. Extend it to follow `rustc_dylib`
  (for `vfs`) and to record GN conditionals it skipped.
- Run it from `//sdk/lib/driver/component/rust`, `//sdk/lib/driver/runtime/rust` and
  `//examples/drivers/simple/rust`.
- `third_party/crates/`: `crate_universe` over the release's `Cargo.toml`/`Cargo.lock`,
  restricted to the closure's direct crates.
- The patched crates the closure needs (of `byteorder`, `memchr`, `libc`, `tokio`) as
  local repositories from `third_party/rust_crates/` at the revision.

**Out of scope:** vendoring the in-tree crates (M8/M9); pilot 2's closure (M12).

### Implementation steps
1. Port the walker from brief App. B into `scripts/closure.py` with pytest over a fake GN
   tree. Add `rustc_dylib`, and output which conditionals were ignored.
2. Run it for pilot 1 and write `docs/closure/pilot1.json` (proposed) with in-tree
   crates, crates.io crates and FIDL libraries. Compare the counts with the brief's
   67 / 44 / 34 in the evidence.
3. Generate `third_party/crates/` with `crate_universe` in vendored mode, so the output
   is committed (D6); build output needs only checksummed downloads.
4. Build every crate for both Fuchsia targets, and proc-macro crates for host.
5. If `zx` was deferred in M5, finish it here.

### Acceptance criteria
- [ ] `docs/closure/pilot1.json` exists, and the walker's pytest passes, including a
  `rustc_dylib` case.
- [ ] Every crates.io crate in the pilot 1 closure builds for both Fuchsia targets;
  proc-macro crates build for host.
- [ ] Only the closure's crates are generated, not all of `Cargo.lock` (count recorded).
- [ ] A build with the network off, after one warm fetch, succeeds (checksummed and
  cached; no resolution step).

### Testing and review
- Verify with `uv run pytest`, and `bazel build --config=fuchsia_x64 //third_party/crates/...`
  (and arm64).
- Review focus: version choice where `Cargo.lock` has two versions (per the GN alias,
  brief A.2 note), patched-crate provenance, and walker correctness on conditionals.

### Session sizing
This is the largest unknown in milestone 1: the transitive crate count. Split point:
the walker and closure report as one session (M6a), and `crate_universe` plus the
builds as the next (M6b). Split before starting if the closure has more than 44 direct
crates.

### Evidence and findings
Status: pending · Evidence: [M6](evidence/M6.md) · Notebook: [M6](notebook/M6.md)

---

## I2 — Prebuilt FIDL generators

**Design coverage:** I2 (shapes R5). **Dependencies:** none; run any time before M7.
**Evidence to collect:**
- The GCS listing of the release's build directory (the method from I1).
- CIPD package search for `fidlgen` (`https://chrome-infra-packages.appspot.com/prpc/cipd.Repository/ListPrefix`
  on `fuchsia/`).
- Whether the IDK's `tools/` has either generator (brief F1 says no; recheck at this
  release).

**Exit:** either a pinned anonymous URL plus hash for each generator for linux-amd64,
or "not published" recorded, which selects the build-from-source route in M7. Evidence
goes in `docs/evidence/I2.md`.

---

## M7 — FIDL generators as Bazel host tools

**Design coverage:** R5 (tools), A4, D7. **Dependencies:** I2, M6.
**In scope:** `tools/fidlgen_rust` and `tools/fidlgen_rust_next`, either fetched by pin
(I2 found prebuilts, added to the lock) or built from source at the revision. If built
from source:
- `fidlgen_rust` (Go) uses `rules_go` and upstream's `BUILD.bazel`.
- `fidlgen_rust_next` (Rust, askama templates) needs a hand-written
  `overlays/tools/fidl/fidlgen_rust_next/BUILD.bazel` and host crates.

**Out of scope:** the binding rule (M8).

### Implementation steps
1. If prebuilt, add the entries to `resolve_pins.py` and the lock, plus a repository
   rule; done.
2. Otherwise, vendor `tools/fidl/fidlgen_rust`, `tools/fidl/lib/fidlgen` and
   `tools/fidl/fidlgen_rust_next` via `regen.py vendor`. Add `rules_go` to
   `MODULE.bazel`, and extend `third_party/crates/` with `fidlgen_rust_next`'s host
   crates (from its `BUILD.gn`).
3. Run both on the IR of one small IDK library (`fuchsia.mem`), produced by the IDK's
   `fidlc`.

### Acceptance criteria
- [ ] `bazel run //tools/fidlgen_rust -- --help` and the same for `fidlgen_rust_next`
  succeed.
- [ ] Each generates Rust from `fuchsia.mem` IR. The output diffs cleanly against the
  same generator's output upstream, where a reference is available; otherwise it
  compiles in M8.
- [ ] Host-only crates do not leak into the Fuchsia target builds.

### Testing and review
- Review focus: C1 for any Go module downloads (checksummed via `go.sum`), and the size
  of the host crate tree (record the count; a risk in design §8.2).

### Session sizing
The build-from-source route is two tools in two languages, and too much for one
session. If I2 says "not published", split before starting: M7a covers
`fidlgen_rust_next`, which is on the critical path for every pilot (F6); M7b covers
`fidlgen_rust`.

### Evidence and findings
Status: pending · Evidence: [M7](evidence/M7.md) · Notebook: [M7](notebook/M7.md)

---

## M8 — FIDL Rust binding rule, both flavors

**Design coverage:** R5, D7, F6. **Dependencies:** M7.
**In scope:**
- `rules/fidl_rust.bzl`:
  - the `rust` flavor, ported from upstream `fidl_rust_library.bzl`;
  - the new `rust_next` flavor, whose crate naming and flags come from the GN template
    that produces `_rust_next` targets (find it:
    `git grep -n rust_next -- build/fidl`).
- The FIDL runtime crates the bindings need, vendored through M5's mechanism:
  `src/lib/fidl/rust/fidl`, `rust_next/fidl_next*`, `fidl/rust_constants`, and their
  deps (`fuchsia-async` and so on, per `pilot1.json`).
- Binding targets for every FIDL library in pilot 1's closure.

**Out of scope:** `fdomain` flavor unless pilot 1 needs it (record if it does); pilot 2
libraries (M12).

### Implementation steps
1. Locate the `rust_next` GN template and record its path and flags in the M8 chapter.
2. The rule runs the IDK's `fidlc` over IDK FIDL sources and dependency IR to produce
   JSON IR, then the generator, then a `rust_library` with the flavor's deps.
3. Vendor the runtime crates in dependency order, building each.
4. Declare bindings for the pilot 1 FIDL list, both flavors where the closure uses them.
5. If a library is not in the IDK (as `fuchsia.sys2` was for the brief's closure),
   record it. Trim the dependency with a patch, or take the FIDL source from the
   revision, and record the choice.

### Acceptance criteria
- [ ] Bindings for every FIDL library in `pilot1.json` compile for both targets, in
  each flavor the closure uses.
- [ ] Crate names match what vendored crates `use` (e.g. `fidl_fuchsia_io`,
  `fidl_next_fuchsia_io`); the evidence records the `rust_next` naming rule.
- [ ] `regen.py --check` is clean after vendoring the runtime crates.

### Testing and review
- Review focus: flags and features parity with upstream's GN template, and the IR
  dependency order (a library's deps compiled first).

### Session sizing
Split point: the `rust` flavor with its runtime crates (M8a), then the `rust_next`
flavor (M8b). Split before starting if the runtime crate list in `pilot1.json` is
longer than about 10 crates.

### Evidence and findings
Status: pending · Evidence: [M8](evidence/M8.md) · Notebook: [M8](notebook/M8.md)

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

### Acceptance criteria
- [ ] `scripts/emu test //drivers/aml_saradc:tests` passes every upstream test, with
  the count equal to the upstream test count at the revision.
- [ ] Production builds are unchanged: the M12 symbol tests still pass.

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
| Cloud disk: about 30 GB free. `fuchsia-cloud-dev`'s cache is about 15 GB; this repo adds the Rust toolchain, crates and bindings | M3 onward | Record disk at M2 and M3. Share one Bazel output base. Drop `rules_python`-only deps. If still tight, emulator milestones may need a lab machine or a larger environment |
| TCG emulation is slow | M11, M16 | Budget from `fuchsia-cloud-dev`'s measurements (about 1 min boot, about 2 min driver reload) |
| I1 finds no anonymous mapping | everything | Stop and escalate at I1; do not guess a revision |
| Closure larger than the plan's split thresholds | M6, M8, M9, M12 | Split thresholds are stated per milestone; split before starting |

## Discovered work / backlog

- **`fuchsia-cloud-dev` overlap.** `fuchsia-cloud-dev` already solves emulator bring-up
  in cloud containers. After M3, consider whether its `dev` tool and this repo's
  harness should share code. Not needed for milestone 1.
- **Other Rust drivers (design F10).** `aml-rtc` and `virtio-gpu-display` are
  candidates for a third pilot or for R7 reference comparisons (see M10).

## Next session

- Current milestone and status: none started; the plan is derived (draft 1) and awaits
  the owner's read.
- Completed work and evidence: design approved; this plan.
- Commits: the plan commit on `claude/quirky-mayer-b1vuym` (message
  `docs: derive implementation plan from approved design`).
- Remaining decisions:
  - the R7 reading for pilot 1 (see Design coverage gap), needed before M10 closes;
  - the M17 placement, needed before M17.
- Context boundary: normal.
- Resume action: **start I1**. First command:
  `curl -sS https://storage.googleapis.com/fuchsia/development/33.20260927.4.1/sdk/linux-amd64/core.tar.gz | tar -xzf - meta/manifest.json && grep -n -i -E 'revision|snapshot|commit' meta/manifest.json`.
- Read first: this plan's I1 and M1 entries, [design](design.md) §4.2 "Pin resolution"
  and §8.1 I1, and the [notebook index](notebook/index.md).
