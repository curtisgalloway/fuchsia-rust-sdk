<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# design — Design and planning

Goal: turn the brief (`~/src/fuchsia-ci/docs/drivers/rust-driver-oot-plan.md`)
into an approved design and an implementation plan for this repo.
Verdict record: [design](../design.md), then `../implementation-plan.md`.

## 2026-09-27T17:29-07:00 — opening
Starting revision: none (empty repo, no commits). Pre-existing changes: none.
Approach: resolve the brief's open questions with the owner, check pilot
candidates in the local `fuchsia.git` tree (`~/src/fuchsia` at `b5274053`),
write the design, stop at the design gate.

## 2026-09-27T17:30-07:00 — direction: open questions answered
Owner chose: pilot `examples/drivers/simple/rust` on the emulator, then
`aml-saradc` on the VIM3 (dw-spi dropped: no DesignWare SPI in the lab);
upstream CIPD toolchain; production builds only for milestone 1; both x64 and
arm64. The overlay lives in this repo (`fuchsia-rust-sdk`).

## 2026-09-27T17:31-07:00 — surprise: simple/rust binds only in a test realm
Its DML-generated bind rule is `gizmo.example.TEST_NODE_ID ==
"simple_rust_driver"`; no stock emulator node has it, and `gizmo.example` is not
an SDK bind library. Pilot 1 needs a retargeted `.bind` (design I3; QEMU `edu`
device is the lead candidate).

## 2026-09-27T17:31-07:00 — surprise: VIM3 already ships aml-saradc
`boards/vim3/BUILD.gn:50` and `vim3-dml/meta/adc.shard.dml` include it, so the
overlay copy competes for the node. Design I4 covers the replacement method.

## 2026-09-27T17:31-07:00 — surprise: rust_next is needed even by the smallest driver
`sdk/lib/driver/component/rust/BUILD.gn` depends on four `_rust_next` binding
targets, so `fidlgen_rust_next` (no upstream Bazel build) is on the critical
path for pilot 1, not only for dw-spi as the brief implied.

## 2026-09-27T17:32-07:00 — decision: commit vendored source (proposed)
Design D6 proposes committing generated `vendor/` and `third_party/crates/`
over a build-time sparse fetch, to satisfy "no fuchsia.git at build time" and
make release bumps reviewable diffs. Flagged for the owner at the design gate.

## 2026-09-27T17:32-07:00 — checkpoint
State: design draft 1 written; waiting on design-gate approval (including D6).
Next: on approval, derive `docs/implementation-plan.md`.
