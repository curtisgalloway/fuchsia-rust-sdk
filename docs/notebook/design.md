<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# design — Design and planning

Goal: turn the brief (`docs/brief.md` at `909cc07`, from `fuchsia-ci` `b061204`)
into an approved design and an implementation plan for this repo.
Verdict record: [design](../design.md), then `../implementation-plan.md`.

## 2026-09-27T17:29-07:00 — opening
Starting revision: none (empty repo, no commits). Pre-existing changes: none.
Approach: resolve the brief's open questions with the owner, check pilot
candidates in the local `fuchsia.git` checkout (at `b5274053`),
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

## 2026-09-27T17:33-07:00 — direction: design approved
Owner approved design draft 1 as written, including D6 (commit vendored
source). Work continues in a cloud session.

## 2026-09-27T17:33-07:00 — checkpoint
State: design gate passed. Next: derive `docs/implementation-plan.md` from
[design](../design.md) (revision: commit after `a84035a` that records approval).

## 2026-09-27T17:46-07:00 — opening (resumed, cloud session)
Starting revision: `a556fa1`. Pre-existing changes: none. Branch
`claude/quirky-mayer-b1vuym`. Approach: derive the plan from the approved design
following the `project-plan` skill (loaded from `curtisgalloway/public-skills`).

## 2026-09-27T17:46-07:00 — surprise: fuchsia-cloud-dev already covers most of I3
`curtisgalloway/fuchsia-cloud-dev` boots `core.x64` (`33.20260919.6.1`) in a cloud
container without KVM, and its `qemu_edu` driver binds via a *composite* rule
(`pci` primary + optional `acpi` parent); a non-composite rule registers but never
binds. Plan uses it for the emulator harness (M3) and as the I3 lead.

## 2026-09-27T17:46-07:00 — decision: plan structure
Investigations I1–I4 get their own rows; I5 folds into M2 step 1. R2's
"runs on emulator" split into M3 (harness); R2's `zx` check moved to M5, where the
vendor mechanism first exists. Review method: reviewer subagent (review-swarm not
installed in cloud). R7's `DT_NEEDED` reference for pilot 1 flagged as a gap for the
owner, not silently changed.

## 2026-09-27T17:46-07:00 — checkpoint
State: plan draft 1 written ([plan](../implementation-plan.md)). Design unchanged.
Next: owner reads the plan; then start I1 (first command in the plan's Next session).

## 2026-09-28T09:18-07:00 — correction of the chapter's goal line (brief link)
The goal line linked `../brief.md`. The owner decided on 2026-09-28 (publication
decision 1B) to remove `docs/brief.md` from the tree before the repository is made
public: it copies a document from the owner's private `curtisgalloway/fuchsia-ci` repo,
which is not published. The file stays in git history (last present at `909cc07`).
The goal line was edited in place: the link became the plain text "`docs/brief.md` at
`909cc07`". No other word of this chapter changed; this is the one deliberate exception
to append-only in this chapter. The "brief" in the entries above still means that
document; see the design's header.
