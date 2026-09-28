<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M9c — Pilot 1's last overlays; `fdf_component`

Goal: vendor pilot 1's last 6 in-tree crates as overlays translated from `BUILD.gn`
(`elf_parse`, `process_builder`, `namespace`, `inspect/runtime/rust`,
`fuchsia-component/config`, `fdf_component`), building each for x64 and arm64, so every
in-tree crate of `pilot1.json` but the pilot driver is vendored
([plan M9c](../implementation-plan.md)).
Verdict record: [M9c evidence](../evidence/M9c.md)

## 2026-09-28T12:37+00:00 — opening
Starting revision: `1ef1833` (origin/main: I1, M1–M9b), branch `ms/M9c`.
Pre-existing changes: none; plan 34 `## ` headings (saved to the run's scratch).
Relied on (orchestrator-verified at `1ef1833`; rechecked at the end): pytest 444, reuse
compliant, `regen.py --check` clean, `gn_crosscheck.py --all` 62 directories / 64
targets agree, three builds + explicit targets under `--lockfile_mode=error` (479
targets each), `bazel test //...` 55 + 18 skipped. Measured now: disk Bazel 11.36 of
15 GiB, total 12.28 of 25 GiB, 17.40 GiB free; `MODULE.bazel.lock` SHA-256 recorded.
`pilot1.json` minus `vendor/crates.txt`: exactly the 6 planned crates plus the driver.
Approach: read each `BUILD.gn` at `b5274053` (`git cat-file`), translate bottom-up
(elf_parse → process_builder → namespace; inspect/runtime, config; then fdf_component)
copying an M9b overlay's rendered fields, run `gn_crosscheck.py` on each before `--all`.
Clock note: this container's clock is UTC, so stamps here are `+00:00`.

## 2026-09-28T12:40+00:00 — attempt: read the six `BUILD.gn` files at `b5274053`
Blobless depth-1 fetch into the run's scratch (as `regen.py`'s `GitSource`), then
`cat-file` of each `BUILD.gn` and every file of the six directories. None has a
`BUILD.bazel` upstream (as `pilot1.json` says). Blobs: `elf_parse` 6dc28b62f01b,
`process_builder` 6b2705cc4fe3, `namespace` 711701a0cfeb, `inspect/runtime/rust`
f19d989d45bf, `fuchsia-component/config` 04c1b59dbbe6, `driver/component/rust`
a88932efdb99. Conditions: `namespace` adds zx, process_builder, vfs under `is_fuchsia`;
`inspect_runtime` adds thiserror at PLATFORM/HEAD (taken: the overlay builds at HEAD).
GN's `version` is `not_needed` in `rustc_library.gni`; the three without one get none.

## 2026-09-28T12:40+00:00 — decision: `inspect/runtime/rust`'s `:rust` group is an alias without `client_includes`
GN: crate `inspect_runtime` is target `:lib` (visibility `:*`); dependents use group
`:rust` = `:lib` + `//sdk/lib/inspect:client_includes`, an `expect_includes` of
`inspect/client.shard.cml` (a manifest check, like M9b's syslog one). Overlay: `lib`
(visibility `:__pkg__`) and `alias(name = "rust", actual = ":lib")`, public (the
`fidl_next_bind` pattern); `client_includes` is not translated (reason in the header).
The pilot's `simple_rust_driver.cml` already includes `inspect/client.shard.cml`, so
M10's manifest check covers it. `gn_crosscheck.py` must list it in `REMOVED_DEPS`, or
`fdf_component`'s group expansion fails closed. `unchecked_includes` not translated.

## 2026-09-28T12:40+00:00 — decision: `elf_parse`'s GN `inputs` → `compile_data`
The three `test-utils/*.bin` are `include_bytes!` in `#[cfg(test)]` only, but GN lists
them as the library's `inputs`; `compile_data` is the direct translation (rules_rust
attribute inherited by `rustc_library`) and keeps M16's test build from needing a change.

## 2026-09-28T12:44+00:00 — failed command: first arm64 build; `inspect/rust` shorthand label
`scripts/bazel build --lockfile_mode=error --config=fuchsia_arm64 --keep_going` on the six
packages (`:all`): exit 1, 3 of 7 top-level targets; loading errors "no such target
'//vendor/fuchsia/src/lib/diagnostics/inspect/rust:rust'" from `config`, `inspect/runtime`
and `fdf_component`. GN's `//src/lib/diagnostics/inspect/rust` is a group/alias there; the
crate is upstream Bazel's `:fuchsia-inspect` (as `inspect/contrib` and `inspect/derive`
name it). Fix: name `:fuchsia-inspect`; check every other shorthand against the vendored
packages' target names before rebuilding.

## 2026-09-28T12:45+00:00 — attempt: arm64 build of the six after the label fix
`regen.py vendor`, then the same arm64 build: exit 0, "Found 7 targets" (six crates + the
`inspect/runtime/rust:rust` alias), 3 compiles (the first run had compiled
`elf_parse`, `process_builder`, `namespace`). No upstream source needed a change;
`third_party/crates/` unchanged by `regen.py`. Next: x64, then `gn_crosscheck.py`.

## 2026-09-28T12:46+00:00 — attempt: x64 build; `gn_crosscheck.py` on the six fails closed as expected
x64 build of the six packages: exit 0, 7 targets, 6 compiles. `gn_crosscheck.py <six paths>`:
exit 2, "cannot resolve dep //sdk/lib/inspect:client_includes (expect_includes)" via
`fdf_component`'s dep on the `inspect/runtime/rust` group (the 12:40 decision predicted
it). Added it to `REMOVED_DEPS` with the reason (the overlay does not translate it).

## 2026-09-28T12:49+00:00 — attempt: `gn_crosscheck.py` on the six agrees; a negative edit fails
With `client_includes` in `REMOVED_DEPS`: 6 directories, 6 targets, 12 (target, config)
pairs OK (`fdf_component`: 34 externs, 13 sources). Negative (scratch edit of the
`namespace` overlay dropping its `is_fuchsia` `vfs` dep, regenerated): exit 1,
"externs: gn only ['vfs']" under both configs; restored, regenerated, agrees again.

## 2026-09-28T12:50+00:00 — attempt: `gn_crosscheck.py --all` agrees; fdf_component reaches the whole closure
`--all`: 68 crate directories, 70 targets, all agree (136 OK lines: 2 Fuchsia configs ×
67 + host proc macros). cquery (x64): `deps(fdf_component)` contains all 70 in-tree
closure targets (`log/rust:no_startup_handle`, `log/encoding/rust:rust` and the five
other M9c crates among them).

## 2026-09-28T12:50+00:00 — decision: the Fuchsia build checks name fdf_component instead of the two log targets
The orchestrator asked for `fdf_component` named explicitly in the x64/arm64 commands; since it
reaches both log targets (M9b named them only because nothing public did; its evidence said
M9c may drop them), the two labels are replaced by
`//vendor/fuchsia/sdk/lib/driver/component/rust:rust`: one label, same coverage plus M9c's.
Also `pub use fdf_component` in `//tests/vendor:pilot1_crates` (a crate outside
`//vendor/fuchsia` using it, as M10's driver will) and cap-lints tests for the new public crates.

## 2026-09-28T12:52+00:00 — attempt: tests updated; `//tests/vendor/...` passes on x64
`tests/test_pilot1_crates.py` (M9c set, 68 of 69 listed, M9c overlays verbatim/Fuchsia-only/
GN names, the inspect_runtime alias, no M9c patch) and `tests/test_gn_crosscheck.py` (each
`REMOVED_DEPS` reason names an existing overlay/patch dir): 20 pass. `tests/vendor`: six
cap-lints tests (fdf_component, inspect_runtime via the alias, elf_parse, process_builder,
namespace, fuchsia_component_config) and `pub use fdf_component` in `:pilot1_crates`;
`bazel test --config=fuchsia_x64 //tests/vendor/...`: 29 passed, 1 skipped (was 23 + 1).

## 2026-09-28T12:54+00:00 — attempt: project checks on the implementation tree
Three builds under `--lockfile_mode=error` with explicit targets (Fuchsia:
`//third_party/crates:aliases //tests/fidl:fuchsia_bindings
//vendor/fuchsia/sdk/lib/driver/component/rust:rust`): x64, arm64, host each 492 targets,
exit 0. `bazel test //...`: 55 passed, 24 skipped (18 + the 6 new Fuchsia-only cap-lints
tests). `//tests/vendor/...` on arm64: 29 + 1 skipped. pytest 448; reuse 1714/1714;
`regen.py --check` clean; `check_sdk_files` 0 missing (x64 18,976, arm64 19,150, host
15,782); `MODULE.bazel.lock` hash unchanged; disk Bazel 11.47 of 15 GiB, total 12.39 of
25 GiB, 17.29 GiB free (M9c: +0.11 GiB).
