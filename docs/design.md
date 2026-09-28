<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# Rust drivers out of tree (the overlay) — Design

Revision: 2026-09-27, draft 1 — approved by the owner 2026-09-27, including D6;
amended 2026-09-27 per owner direction and M2/M3 findings (C4, C6, A2, R1, R2, §4.1, §4.2 toolchain, Rust rules and third-party crates)

Source brief: [`brief.md`](brief.md), copied from `curtisgalloway/fuchsia-ci` at `b061204`
(`docs/drivers/rust-driver-oot-plan.md`) (the
"brief"). It holds the upstream evidence, with paths relative to `fuchsia.git`.
This document restates only what the design depends on; section references like
"brief §3.4" point there.

**Terms**

- **SDK / IDK:** the released Fuchsia SDK. The IDK is its build-system-neutral
  core (`core.tar.gz`); the Bazel SDK (`rules_fuchsia` plus a `@fuchsia_sdk`
  repository) is built from it.
- **Atom:** one item in the IDK (a FIDL library, a prebuilt `.so`, a host tool).
- **DFv2:** Fuchsia's current driver framework. A driver is a shared library
  plus a component manifest (`.cml`) and bind rules (`.bind`).
- **Bind rules:** the predicate that decides which device node a driver attaches
  to. "Binds" means the driver framework matched and started it on a node.
- **FIDL bindings, `rust` vs `rust_next`:** two generated Rust APIs for the same
  FIDL library, produced by two different generators (`fidlgen_rust`,
  `fidlgen_rust_next`). Driver crates use both.
- **Overlay:** this repo. A Bazel workspace that sits beside a released SDK and
  adds what the SDK lacks for Rust.
- **Release / SDK version:** a string like `33.20260927.4.1`. Each maps to one
  `fuchsia.git` commit, the **release revision**.
- **CIPD:** Chrome Infrastructure Package Deployment, the package store that
  hosts Fuchsia's prebuilt Rust toolchain.
- **Closure:** every crate, FIDL library and native library a driver needs,
  transitively.

---

## 1. Goal and non-goals

**Goal.** Build Fuchsia DFv2 drivers written in Rust outside `fuchsia.git`,
against one released SDK, and run them on a device or emulator whose OS came
from the same release.

**Who benefits.** Out-of-tree driver authors (first: this project's own lab
work), and a future upstream RFC for Rust in the SDK, which needs measured
evidence of the minimal closure and per-release cost (brief §8).

**Observable outcomes.**

- A `bazel build` in this repo produces a Fuchsia driver package from Rust
  source, with no `fuchsia.git` checkout present.
- That package loads on an emulator and binds on a real node.
- A second Rust driver binds on real hardware (the lab VIM3).
- One command regenerates the workspace for a new release, and CI runs it.

**Non-goals.**

- Getting Rust into the official SDK. The overlay is the prototype for that
  proposal, not the proposal.
- Banjo, or DFv1. DFv2 only.
- Cross-release compatibility. Each overlay state targets exactly one release
  (constraint C3).
- Driver unit tests in milestone 1 (decided 2026-09-27). They are a later
  requirement (R9), not dropped.
- Cargo as a build system. Cargo metadata may be generated for IDE use later;
  it is not a supported build path.
- macOS or Windows hosts. The build host is linux-amd64.

## 2. Current state and constraints

### 2.1 Observed facts

Facts carried from the brief (evidence at `fuchsia.git` `40c25c2c` and IDK
`33.20260927.4.1`):

- **F1.** The IDK has no Rust atom type, no `fidlgen_rust` or
  `fidlgen_rust_next` host tool, and `rules_fuchsia` has no Rust driver rule
  (brief §3.1).
- **F2.** The IDK does ship what Rust links against: `driver_runtime_shared_lib`,
  `fdio`, `async-default`, `sysroot`, plus `fidlc`, the FIDL sources, and clang
  via `@fuchsia_clang` (brief §3.2).
- **F3.** The driver ABI is one exported C symbol,
  `__fuchsia_driver_registration__`, enforced by the version script
  `fuchsia/private/driver.ld` in `rules_fuchsia` (brief §3.3).
- **F4.** Upstream's platform-internal Bazel build already has `rules_rust`
  0.69.0 (one patch), Fuchsia Rust toolchain definitions, `rustc_library`
  wrappers, API-level cfg generation, and a `fidl_rust_library` rule for the
  `fidl`/`common`/`fdomain` flavors. It has **no `rust_next` flavor**
  (brief §3.4).
- **F5.** Upstream's pinned Rust toolchain (host + Fuchsia target std) resolves
  anonymously from CIPD at the pin in `manifests/toolchain` (brief §3.5).
  Re-confirmed in the local tree at `b5274053` (2026-09-27): same pin,
  `git_revisions:c26ce708…,3493720e…`.

Facts found for this design (local tree at `b5274053`, 2026-09-27):

- **F6. `rust_next` is on the critical path for every pilot.**
  `sdk/lib/driver/component/rust/BUILD.gn` depends on `_rust_next` bindings for
  `fuchsia.component.decl`, `fuchsia.component.runner`,
  `fuchsia.driver.framework` and `fuchsia.io`. So even the smallest driver needs
  `fidlgen_rust_next`, which has no Bazel build upstream.
- **F7. `examples/drivers/simple/rust` binds only in a test realm.** Its bind
  rule is `gizmo.example.TEST_NODE_ID == "simple_rust_driver"`, generated from
  a DML file by `dmlc` (not in the SDK). `gizmo.example` is an example bind
  library (`examples/drivers/bind/bindlib`), not an SDK atom. No node on a stock
  emulator carries that property.
- **F8. `aml-saradc` needs no DML.** `src/devices/adc/drivers/aml-saradc` has
  hand-written `meta/aml-saradc.bind` and `.cml`, 474 lines of Rust, and its
  bind libraries (`fuchsia.platform`, `fuchsia.amlogic.platform`) and FIDL
  (`fuchsia.hardware.adcimpl`) are `sdk_category = "partner"`, so they are in
  the IDK.
- **F9. The VIM3 board already ships `aml-saradc`.** `boards/vim3/BUILD.gn:50`
  puts it in the board's driver packages, and
  `src/devices/board/drivers/vim3-dml/meta/adc.shard.dml` references
  `fuchsia-pkg://fuchsia.com/aml-saradc#meta/aml-saradc.cm`. An out-of-tree
  copy competes with the in-tree one for the same node.
- **F10.** Other in-tree Rust drivers exist that could serve later
  (`fuchsia_rust_driver(` in 34 `BUILD.gn` files), including `aml-rtc` and
  `virtio-gpu-display`. Recorded for the backlog, not used here.

### 2.2 Constraints (fixed)

- **C1. Anonymous access only** for every upstream fetch: git from
  `fuchsia.googlesource.com`, GCS, CIPD.
- **C2. DFv2 only; no Banjo.**
- **C3. Version lock.** Hardware FIDL is `@available(added=HEAD)`, so a driver
  built at release N runs only on an OS from release N. Every artifact is
  pinned to one release and regenerated, never kept compatible.
- **C4. Licensing.** This repo's own code is Apache 2.0 with SPDX headers.
  Vendored Fuchsia code keeps its `LICENSE` (the BSD-2-Clause text at the
  release revision; corrected in M5 from "BSD-3") and `PATENTS`; vendored crates keep theirs.
- **C5. Build host is linux-amd64.** The CIPD host toolchain and the IDK are
  fetched for that platform.
- **C6. Environment profile; the hosted profile is the default.** Resource limits
  belong to the environment the work runs in, not to the project (owner direction
  2026-09-27). The default profile is the Anthropic-hosted cloud container: about
  30 GB of writable disk, 4 vCPU, no KVM, linux-amd64. Every milestone must pass under
  it, with total disk use at most 25 GB (5 GB headroom). Other profiles (self-hosted
  runners, dev VMs, lab boxes) may declare more disk, KVM or attached hardware; the
  scripts detect or read the profile and relax to match (for example skip the IDK
  trim, keep caches, use KVM).

### 2.3 Assumptions (not yet verified)

- **A1.** An SDK version maps to its `fuchsia.git` revision through a published
  artifact (brief §3.6 [verify]). Investigation I1.
- **A2 (resolved in M2, amended).** `rules_rust` 0.69.0 with upstream's patch loads
  with this release's `rules_fuchsia` under Bazel 8.5.1, the version `fuchsia.git`
  pins at the release revision (`manifests/jiri.lock`). The Bazel that
  `sdk-samples/drivers` pins (8.1.0) cannot load this SDK: its native `cc_import`
  lacks `strip_include_prefix` (added in Bazel 8.3.0), which the generated
  `@fuchsia_sdk` uses. See [M2 evidence](evidence/M2.md).
- **A3.** The pinned toolchain's Rust `std` for `*-unknown-fuchsia` imports no
  symbols on `rules_fuchsia`'s driver restricted-symbols list, or upstream has a
  known config that avoids them. Checked when the driver rule is written.
- **A4.** `fidlgen_rust` (Go) and `fidlgen_rust_next` (Rust) build from source
  at the release revision without a `fuchsia.git` build environment. I2 checks
  for a prebuilt route first.

## 3. Requirements and acceptance criteria

- **R1. Pinned release lock.** Given an SDK version, a script produces
  `overlay.lock.json` with: the release revision, the CIPD instance IDs of the
  toolchain packages (Rust host, Rust Fuchsia target std, Rust host std, clang), the
  `rules_fuchsia`/Bazel SDK version, the emulator product bundle (`core.x64`) pinned
  by a digest over its files' SHA-256s (owner decision 2026-09-27, added in M3), and
  the SHA-256 of the release's
  `third_party/rust_crates/Cargo.lock`. *Check:* running it twice gives
  byte-identical output; each field names the upstream artifact it came from.
- **R2. Fuchsia Rust toolchain.** The overlay registers Rust toolchains for
  `x86_64-unknown-fuchsia` and `aarch64-unknown-fuchsia` from the pinned CIPD
  packages, linking through `@fuchsia_clang` and the IDK sysroot, plus a host
  toolchain from the same pinned toolchain revision (the host compiler package plus
  upstream's separate `x86_64-unknown-linux-gnu` std package) for proc macros and
  build tools.
  *Check:* `zx-types`, `zx-sys` and `zx` build for both targets; a hello-world
  binary links against `libfdio.so` and runs on the emulator.
- **R3. Library rules with API-level cfgs.** `rustc_library`,
  `rustc_proc_macro` and `rustc_binary` equivalents set
  `--cfg=fuchsia_api_level_at_least="…"` / `…_less_than="…"` from the IDK's
  `version_history.json`, targeting `HEAD`. *Check:* a test crate with
  `#[cfg(fuchsia_api_level_at_least = "HEAD")]` compiles the `HEAD` branch.
- **R4. Third-party crates.** Every crates.io crate in the closure builds at the
  version in the release's `Cargo.lock`, including the locally patched ones
  (`byteorder`, `memchr`, `libc`, `tokio`, taken from `third_party/rust_crates/`
  at the release revision). *Check:* each builds for both targets; proc-macro
  crates build for the host.
- **R5. FIDL Rust bindings, both flavors.** A rule generates `rust` and
  `rust_next` bindings from IDK FIDL sources with the IDK's `fidlc`. *Check:*
  bindings for every FIDL library in the pilots' closures compile for both
  targets.
- **R6. Vendored in-tree crates.** The in-tree crates in the pilots' closures
  are copied from `fuchsia.git` at the release revision with a `BUILD.bazel`
  each; local changes are patch files, never hand edits. *Check:*
  `fdf_component`, `fdf` and (for pilot 2) `mmio`, `pdev`, `fdf_metadata`
  build for both targets; `regen.py --check` reports no drift from upstream
  plus patches.
- **R7. `fuchsia_rust_driver` rule.** Produces a `cdylib` driver and hands it to
  `rules_fuchsia`'s `fuchsia_driver_component`. *Check:* the `.so` exports only
  `__fuchsia_driver_registration__` (`llvm-readelf --dyn-syms`); passes
  `rules_fuchsia`'s restricted-symbols check; its `DT_NEEDED` set matches the
  in-tree build of the same driver taken from the release's product bundle.
- **R8a. Pilot 1 on the emulator.** A Rust driver derived from
  `examples/drivers/simple/rust` builds, packages, loads and **binds on a real
  node** on an emulator running the same release. *Check:* `ffx driver list`
  shows it loaded; `ffx driver list-devices -v` shows it bound to the node
  chosen by I3; its log line appears in `ffx log`.
- **R8b. Pilot 2 on the VIM3.** `aml-saradc` built by the overlay replaces the
  in-tree copy and binds on the lab VIM3 running the same release. *Check:*
  `ffx driver list-devices -v` shows the overlay's package URL bound to the ADC
  node; an ADC read through `fuchsia.hardware.adc` returns a value.
- **R9. Unit tests (after milestone 1).** The driver rule can also build a Rust
  unit-test binary (upstream's `-test-staticlib` pattern) and run it on the
  emulator. *Check:* `aml-saradc`'s own `#[cfg(test)]` tests pass.
- **R10. One-command regeneration.** `regen.py <sdk-version>` refreshes the lock,
  crates, vendored sources and patches, then builds. *Check:* two consecutive
  releases regenerate and build with zero manual edits; a failed patch or a
  renamed upstream crate stops the run with a message naming it.
- **R11. CI.** A `fuchsia-ci` job runs R10 for each newly mirrored release and
  records pass/fail in its database. *Check:* one release processed end to end
  by the job, visible in the dashboard.
- **R12. Closure report.** Regeneration writes a machine-readable report of the
  closure (crate list, line counts, patches applied). *Check:* the report exists
  per release and is what the upstream RFC cites.

Milestone 1 (brief §1) is R1–R7 plus R8a. Milestone 2 is R8b, R9–R12.

## 4. Architecture

### 4.1 Layout (proposed)

```
fuchsia-rust-sdk/
├── MODULE.bazel             # rules_fuchsia + fuchsia_sdk at the lock's version; rules_rust 0.69.0 + patch
├── .bazelversion            # the Bazel fuchsia.git pins at the release revision
├── overlay.lock.json        # R1: the only per-release input; everything else derives from it
├── toolchain/               # R2: CIPD repo rule + rust_toolchain() for x64/arm64 Fuchsia + host
├── rules/
│   ├── rustc.bzl            # R3: library/proc-macro/binary wrappers + api-level cfgs
│   ├── fidl_rust.bzl        # R5: rust + rust_next binding rules
│   └── fuchsia_rust_driver.bzl  # R7
├── patches/
│   ├── rules_rust/          # upstream's rules_rust patch, copied
│   └── fuchsia/             # per-crate patches applied to vendor/ by regen.py
├── overlays/                # hand-written BUILD.bazel for crates upstream has none for, keyed by path
├── third_party/crates/      # R4: generated crate_universe repo definitions
├── vendor/fuchsia/          # R6: generated copy of in-tree crates at the release revision (committed)
├── tools/
│   ├── fidlgen_rust/        # R5: build or fetch (per I2)
│   └── fidlgen_rust_next/
├── drivers/
│   ├── simple_rust/         # R8a
│   └── aml_saradc/          # R8b
├── scripts/
│   ├── resolve_pins.py      # R1
│   └── regen.py             # R10, R12
└── docs/
```

### 4.2 Components and responsibilities

**Pin resolution (`scripts/resolve_pins.py`, R1).** Input: SDK version. Steps:
map the version to the release revision (method from I1); read
`manifests/toolchain` at that revision and resolve both CIPD packages to
instance IDs with the anonymous `ResolveVersion` call (brief App. B step 3);
record the Bazel SDK version; hash `Cargo.lock`. Output: `overlay.lock.json`.
All later steps read only this file, so a build is reproducible from the repo
alone. Fails loudly if any field cannot be resolved; never writes a partial
lock.

**Toolchain (`toolchain/`, R2).** A repository rule downloads the pinned CIPD
instances by instance ID (content-addressed, so the SHA is the pin) over
anonymous HTTPS and defines `rust_toolchain()` targets, a port of upstream's
`build/bazel/toolchains/rust/rust.BUILD.bazel`. Linking uses `@fuchsia_clang`
and `@fuchsia_sdk//pkg/sysroot`. The host toolchain comes from the same host
package and serves proc macros and host tools.

**Rust rules (`rules/rustc.bzl`, R3).** Thin wrappers over `rules_rust`, ported
from upstream's `build/bazel/rules/rust/`, adding `--cap-lints` for vendored
code and upstream's lint configs. The API-level cfg list from
`rustc_api_level.bzl`, fed by the IDK's `version_history.json`, is applied by the
Rust toolchains, as upstream does: the Fuchsia toolchains at the configured level
(HEAD), the host toolchain at PLATFORM (amended after M4).

**Third-party crates (`third_party/crates/`, R4).** `regen.py` takes upstream's own
`crate_universe`-generated BUILD files for `third_party/rust_crates` at the release
revision, restricted to the crates the closure needs, and rewrites their labels; no
local `crate_universe` run and no crate-index resolution (amended after M5, option
A). Each `.crate` is downloaded from crates.io pinned by the SHA-256 in the release's
`Cargo.lock`, which is itself checked against the lock. The locally patched crates
(`forks/libc`, `ask2patch/memchr`, …) are copied from `third_party/rust_crates/` at
the release revision by `regen.py` and committed (D6). Generated output is committed
so the build needs no resolution step, only downloads pinned by checksum.

**FIDL bindings (`rules/fidl_rust.bzl` + `tools/`, R5).** One rule, two flavors.
Both run the IDK's `fidlc` on IDK FIDL sources to get JSON IR, then the flavor's
generator, then compile the output as a `rust_library`. The `rust` flavor is a
port of upstream's `fidl_rust_library.bzl`. The `rust_next` flavor is new; its
crate naming and flags come from the GN template that produces `_rust_next`
targets (location to find in the first FIDL milestone). Generators are built
from source at the release revision unless I2 finds published prebuilts.

**Vendored crates (`vendor/`, `overlays/`, `patches/fuchsia/`, R6).** `regen.py`
copies each crate directory from `fuchsia.git` at the release revision
(anonymous sparse fetch), then: for crates with upstream `BUILD.bazel`, copies
it and rewrites labels to overlay paths; for crates without, uses the
hand-written file from `overlays/`; then applies `patches/fuchsia/`. The
starting file for an `overlays/` entry can be translated from `BUILD.gn`, but
the committed file is reviewed by hand.

**Driver rule (`rules/fuchsia_rust_driver.bzl`, R7).** A `rust_shared_library`
(crate type `cdylib`) linked with `-Wl,--version-script=` pointing at
`rules_fuchsia`'s `driver.ld`, against
`@fuchsia_sdk//pkg/driver_runtime_shared_lib`. It returns the providers
`fuchsia_driver_component` consumes (modeled on how `fuchsia_cc.bzl` builds
`FuchsiaPackageResourcesInfo`/`FuchsiaUnstrippedBinaryInfo` with
`install_root = "driver/"`), and runs the restricted-symbols check. Bind rules
and `.cml` use `rules_fuchsia`'s existing `fuchsia_driver_bind_bytecode` and
component rules unchanged.

**Pilots (`drivers/`, R8a/R8b).**

- *Pilot 1, `simple_rust`.* Source copied from `examples/drivers/simple/rust`.
  Its DML-generated bind rule targets a test-only node (F7), so the overlay's
  copy gets a hand-written `.bind` targeting a node that really exists on the
  emulator, chosen by I3. The `.cml` is the checked-in generated file. This
  pilot keeps the closure small: `fdf_component`, `fdf` runtime, `zx`,
  `fidl`, and the `rust_next` core (F6).
- *Pilot 2, `aml_saradc`.* Source copied from `src/devices/adc/drivers/
  aml-saradc` with its upstream `.bind` and `.cml` (F8). Adds `mmio`, `pdev`,
  `fdf_metadata`, `fuchsia-async`, `fuchsia-component`, `fuchsia-sync`. Because
  the VIM3 board already ships this driver (F9), deployment needs the
  replacement method from I4.

**Regeneration and CI (`scripts/regen.py`, R10–R12).** Runs R1 → R4 → R5
(bindings) → R6 for a version, writes the closure report, then builds and runs
the R7 checks. Keyed on upstream paths and GN labels so a rename fails loudly.
A `fuchsia-ci` job invokes it per mirrored release, alongside the C++
out-of-tree rebuild job proposed in `fuchsia-ci`'s
`docs/drivers/out-of-tree-bus-drivers.md` §7.

### 4.3 Main flows

**Build (developer, milestone 1).**
`bazel build //drivers/simple_rust:pkg --config=fuchsia_x64` → toolchain repo
fetched by instance ID → crates fetched by checksum → FIDL bindings generated
→ vendored crates compiled → `cdylib` linked with `driver.ld` → packaged by
`rules_fuchsia`. No network access beyond pinned, content-addressed downloads.

**Deploy (pilot 1).** Start the emulator from the release's product bundle
(already mirrored by `fuchsia-ci`) → `ffx driver register` the package
(ephemeral drivers work on `eng` products, brief W7) → the driver framework
matches the I3 node → check `ffx driver list-devices -v` and `ffx log`.

**Deploy (pilot 2).** Flash the VIM3 with the same release → replace the
in-tree `aml-saradc` by the I4 method → verify binding and an ADC read.

**Release bump.** `regen.py <new-version>` → review the diff of `vendor/`,
`third_party/crates/` and the lock → commit. Patches that no longer apply stop
the run with the patch name and the conflicting file.

### 4.4 Error handling and recovery

- Every fetch is pinned by content hash; a mismatch fails the build, never
  silently re-resolves.
- `resolve_pins.py` writes the lock atomically (temp file then rename), so a
  failed resolution leaves the previous lock intact.
- `regen.py` works in a scratch tree and replaces `vendor/` and
  `third_party/crates/` only after the build passes; a failed release bump
  leaves the last good state on disk and in git.
- The restricted-symbols and exported-symbols checks run as Bazel actions, so a
  bad link fails the build rather than the device.

## 5. Key decisions

- **D1. Bazel, not Cargo** (brief §5). Packaging, bind bytecode and board
  assembly exist only as Bazel rules; upstream's Rust Bazel rules exist to port.
- **D2. Pilot sequence: `simple_rust` on the emulator, then `aml-saradc` on the
  VIM3** (user decision 2026-09-27). Replaces the brief's `dw-spi`, which has no
  DesignWare SPI hardware in the lab to bind on. Consequence: pilot 1 needs a
  retargeted bind rule (I3), and pilot 2 needs a replacement path for an
  already-shipped driver (I4).
- **D3. Upstream's pinned CIPD toolchain** (user decision 2026-09-27). rustup
  stable remains a documented fallback if CIPD access changes (brief §3.5); not
  built or tested.
- **D4. Both x64 and arm64 from the start** (user decision 2026-09-27). Pilot 1
  runs on x64, pilot 2 on arm64; every build requirement checks both.
- **D5. Production builds only in milestone 1** (user decision 2026-09-27).
  Unit tests are R9, in milestone 2.
- **D6. Vendored source is committed.** *Approved at the design gate 2026-09-27.*
  `vendor/` and `third_party/crates/` are generated but committed, one release
  at a time on `main`, with git history keeping earlier releases.
  *Alternative:* a Bazel repository rule that sparse-fetches `fuchsia.git` at
  the release revision during the build and overlays BUILD files and patches.
  That keeps the repo small, but makes every clean build depend on
  `fuchsia.googlesource.com` and conflicts with the brief's "no `fuchsia.git`
  checkout at build time". *Why committed:* the build then needs only
  content-addressed downloads; a release bump shows up as a reviewable diff of
  upstream changes, which is itself RFC evidence (R12). *Cost:* tens of
  thousands of lines of vendored Rust in the repo (closure size after
  trimming, measured in the vendor milestone).
- **D7. Generate FIDL bindings from IDK FIDL sources with the IDK's `fidlc`.**
  Upstream does not publish pre-generated bindings.
- **D8. Size the closure from the pilots, not the brief's three roots.** The
  brief's 67-crate closure was computed for `dw-spi`. Vendoring follows what
  `simple_rust`, then `aml-saradc`, actually need, so the first milestones carry
  less than the brief's upper bound. The closure walker (brief App. B) is
  re-run per pilot and extended to handle `rustc_dylib` (the missed `vfs`
  crate).
- **D9. Keep the layout close to a plausible upstream atom layout** (brief §8):
  one directory per crate under `vendor/`, keyed by its `fuchsia.git` path, so
  the structure can be proposed as-is.

## 6. Cross-cutting concerns

- **Security.** All fetches are anonymous HTTPS, pinned by content hash (CIPD
  instance IDs, crate checksums, git revisions). No credentials anywhere in the
  build or CI path.
- **Licensing.** `vendor/` keeps each upstream `LICENSE` and `METADATA` file;
  `third_party/crates/` records each crate's license. The closure report (R12)
  lists licenses.
- **Operational.** CI regeneration writes to a scratch directory and records
  pass/fail in the `fuchsia-ci` DB; the repo's committed state changes only by
  human-reviewed commit.
- **Performance.** Not a goal. Build time is recorded per release in the
  closure report so growth is visible.

## 7. Verification strategy

| Level | What | How |
|---|---|---|
| Unit (scripts) | `resolve_pins.py`, `regen.py` logic with network stubbed | `uv run pytest` |
| Build | Each requirement's target set builds for both Fuchsia targets | `bazel build --config=fuchsia_x64 …` and `--config=fuchsia_arm64 …` (config names proposed) |
| Binary checks | Exported symbols, restricted symbols, `DT_NEEDED` vs the in-tree build | Bazel test actions plus `llvm-readelf` from `@fuchsia_clang` |
| Emulator | Pilot 1 loads and binds | `ffx emu start` with the release's product bundle; `ffx driver register`; `ffx driver list-devices -v`; `ffx log` |
| Hardware | Pilot 2 binds and reads the ADC | The lab VIM3 via `fuchsia-ci`'s bench tooling; `ffx driver list-devices -v`; an ADC read |
| Regeneration | Two consecutive releases, zero manual edits | `regen.py <v1>`, `regen.py <v2>`, both green |

The exact `ffx` flows for driver registration and replacement are outputs of
I3 and I4, not assumed here.

## 8. Risks and open questions

### 8.1 Bounded investigations

Each blocks only the work named.

- **I1. SDK version → release revision.** *Question:* which published artifact
  maps `33.20260927.4.1` to a `fuchsia.git` commit? *Evidence:* the IDK
  tarball's metadata, the GCS release directory, and the Buildbucket recipes in
  `fuchsia-ci`'s `fuchsia-release-artifacts-ci-handoff.md`. *Exit:* a
  documented, anonymous lookup that returns the revision for two releases.
  *Blocks:* R1, and everything derived from the lock.
- **I2. Prebuilt FIDL generators.** *Question:* are `fidlgen_rust` and
  `fidlgen_rust_next` host binaries published for a release (GCS build
  artifacts, CIPD)? *Evidence:* listings of the release's GCS build directory
  and CIPD package names. *Exit:* either a pinned anonymous URL for each, or a
  recorded "not published" and the build-from-source route. *Blocks:* how R5 is
  implemented, not whether.
- **I3. A real bind target for pilot 1 on the emulator.** *Question:* which node
  on an `eng` emulator of this release can the overlay's `simple_rust` bind to?
  *Candidates:* the QEMU `edu` PCI device (vendor `0x1234`, device `0x11e8`),
  which `sdk-samples/drivers`' C++ `qemu_edu` driver uses and the emulator adds
  with an extra QEMU flag; or an existing unbound node
  (`ffx driver list-devices --unbound`). *Exit:* a `.bind` rule using only IDK
  bind libraries and an emulator command line that makes it match. *Blocks:*
  R8a's "binds" criterion (not the build).
- **I4. Replacing an in-tree driver on the VIM3.** *Question:* how does the
  overlay's `aml-saradc` take the ADC node from the in-tree copy the board
  ships (F9)? *Candidates:* `ffx driver disable` the in-tree URL, then register
  the overlay package and restart the node; or build the overlay package into a
  board input bundle in place of the in-tree one. *Exit:* a repeatable sequence
  that leaves the overlay's URL bound, tested once on the VIM3. *Blocks:* R8b.
- **I5. Toolchain and rule coupling.** *Question:* does `rules_rust` 0.69.0 plus
  upstream's patch load alongside this release's `rules_fuchsia` under the
  Bazel version `sdk-samples/drivers` pins? *Exit:* an empty workspace with both
  loads and resolves `@fuchsia_clang`. *Blocks:* R2. Done as the first step of
  the toolchain milestone, not separately.

### 8.2 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Closure larger than needed (GN conditionals ignored by the walker) | High | D8: size per pilot; carry trims as patches |
| `fidlgen_rust_next` build pulls a large host crate tree | Medium | I2 first; it is on every pilot's path (F6), so it is scheduled early |
| Rust `std` imports restricted libc symbols (A3) | Medium | R7 check runs in the first driver milestone; compare with in-tree Rust driver configs |
| Overlay `aml-saradc` cannot displace the in-tree one without re-assembling the board | Medium | I4 before pilot 2 work begins |
| Upstream renames or moves crates between releases | Medium | `regen.py` fails loudly by path; CI catches it within one release |
| CIPD toolchain pin changes format or stops being anonymous | Low | D3 fallback: rustup stable |

### 8.3 Open questions for the owner

None blocking the plan. D6 (commit the vendored source) is the one proposed
decision to confirm at the design gate. The `fuchsia-ci` job's placement (R11)
follows whatever the C++ out-of-tree job settles on.
