<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M8b — FIDL Rust binding rule, `rust_next` flavor evidence

Design: [design](../design.md), revision "2026-09-27, draft 1", amended 2026-09-27
(D7/R5 exception for non-IDK FIDL libraries, `b32e648`); unchanged in M8b.
Notebook: [M8b chapter](../notebook/M8b.md).
Starting revision and pre-existing changes: `5b9f58f` (origin/main: I1, M1–M8a), branch
`ms/M8b`; working tree clean; plan 32 `## ` headings. `wip` commits: `e3e7b5f` (rule,
regen.py, runtime crates, bindings, tests), `f581e17` (evidence, plan, notebook),
`d6ad181` (process log); the checkpoint commit `overlay: M8b — FIDL Rust binding rule, rust_next flavor` follows the
review.

**Relied on:** the orchestrator's verified state at `5b9f58f` (pytest 406, reuse
compliant, the three builds with explicit targets and `bazel test //...` 52 + 3 skipped
under `--lockfile_mode=error`, `regen.py --check` clean, Bazel caches 10.8 of 12 GiB);
all rechecked on the final tree (below). The lock (`33.20260927.4.1`, fuchsia.git
`b5274053…`), M7's `//tools/fidlgen_rust_next` and configs, M8a's `rules/fidl.bzl` IR
targets and `docs/closure/pilot1.json`.

## Milestone definition

The plan's M8b entry (moved here at completion; unchanged except for status):

**Design coverage:** R5, D7, F6. **Dependencies:** M8a.
**Decided (orchestrator, after the M8a review):** the driver transport moves to M9. M8b
covers the 17 libraries without `contains_drivers`; `fuchsia.driver.framework` and
`fuchsia.power.broker` get their `rust_next` crates in M9.
**In scope:** the `rust_next` and `rust_next_common` flavors from
`build/rust/fidl_rust_next.gni` and `build/fidl/fidl.gni` (crate `fidl_next_<lib>` /
`fidl_next_common_<lib>`, targets `<lib>_rust_next`, `<lib>_rust_next_common`, edition
2024, `--config configs/{fuchsia,common}.json`, `--common-lib fidl_next_common_<lib>` for
the regular crate, deps `fidl_next` + `static_assertions` + the dep libraries'
`_rust_next[_common]` + zx → `zx-types`, feature `fuchsia` on Fuchsia; the
`contains_drivers` path written but only exercised in M9); the 6 runtime crates
(`fidl_next`, `fidl_next_bind`, `fidl_next_codec`, `fidl_next_protocol`, `fidl_next_util`,
`fuchsia-loom`); `rust_next` bindings for the 17 libraries.
**Out of scope:** the driver transport and the two driver libraries' `rust_next` crates
(M9); `fdomain` flavors; `fidl_rust_next_convert` crates; pilot 2 libraries (M12).

Implementation steps: (1) port the flavor into the macro, with a check that its arguments
match `tests/fidlgen/fidlgen.bzl`'s `FLAVORS`; (2) vendor the 6 crates through `regen.py`
and build the 17 libraries; (3) extend `tests/fidl` (crate names, `:fuchsia_bindings`).

Acceptance criteria:

- [x] `rust_next` and `rust_next_common` crates of the 17 libraries without
  `contains_drivers` compile for both targets (17 / 17).
- [x] Crate names match what vendored crates `use` (`fidl_next_fuchsia_io`,
  `fidl_next_common_fuchsia_io`); the evidence records the `rust_next` naming rule.
- [x] `regen.py --check` is clean; the generated crate set still equals the closure's.

Review focus (plan): flags and features parity with `fidl_rust_next.gni` (the `fuchsia`
feature, `--common-lib`, `--config`), IR dependency order.

## What was built

| File | What | Upstream source |
|---|---|---|
| `rules/fidl_rust_next.bzl` (new) | `fidl_rust_next_library` (both crates), `_fidlgen_rust_next`, GN's visibility intersection, `fidl_rust_next_allowlist` | `build/rust/fidl_rust_next.gni` (blob `ba4f5f71`), `build/fidl/fidl.gni` (`988ab2a7`), `build/rust/fidl_rust_next.bzl` (`b0bc7a1b`) at `b5274053` |
| `rules/fidl.bzl` | `enable_rust_next` calls the flavor (was `pass`) | upstream's `fidl_library.bzl` still `pass`es (fxbug.dev/454452299) |
| `scripts/regen.py` | maps `load("//build/rust:fidl_rust_next.bzl", "fidl_rust_next_allowlist")` to `//rules:fidl_rust_next.bzl` and checks the overlay's copy of the list against the revision's; an unmappable label inside a Rust rule's `test_deps` is provisional (a patch must remove it) | — |
| `vendor/crates.txt` | `sdk/lib/fuchsia-loom`, `src/lib/fidl/rust_next/fidl_next{,_bind,_codec,_protocol,_util}` (`upstream`) | — |
| `patches/fuchsia/src/lib/fidl/rust_next/fidl_next_protocol/0001-drop-test-deps.patch` | `test_deps = []` (they name `//third_party/rust_crates:futures`, which upstream Bazel does not define) | — |
| `vendor/fuchsia/…` | generated: 6 crates, 98 files (14,754 `.rs` lines) | fuchsia.git at `b5274053` |
| `tests/fidl/src/crate_names_next.rs`, `tests/fidl/BUILD.bazel` | `:crate_names_next` (`pub use` of the 34 crates), in `:fuchsia_bindings` | — |
| `tests/fidlgen/BUILD.bazel` | `fuchsia_mem_rust_next[_common]_rule_parity_test`: the rule's generator output = M7's `FLAVORS` genrules | — |
| `tests/vendor/BUILD.bazel` | `cap_lints_allow_fuchsia_loom_test` | — |
| `tests/test_fidl.py`, `tests/test_regen.py` | closure consistency (+3); regen mapping, allowlist check, overlay entries outside `//vendor/fuchsia`, `test_deps` path (+12) | — |

### How the flavor is declared

For each `fidl_library` with `enable_rust_next` (default True, as in GN and upstream's
Bazel macro) and without `contains_drivers`, in `//vendor/fuchsia/sdk/fidl/<lib>`:

| Target | What |
|---|---|
| `<lib>_rust_next_common_fidlgen` | `fidlgen_rust_next --json <IR> --output-filename … --rustfmt … --rustfmt-config rustfmt.toml --config configs/common.json` |
| `<lib>_rust_next_common`, crate `fidl_next_common_<lib_>` | edition 2024, version 0.1.0, no clippy, lints `//rules/lints:fidl_rust` (GN: rustc_library defaults + `allow_unused_crate_dependencies` + `deny_unused_results`); deps `fidl_next`, `static_assertions`, each FIDL dep's `_rust_next_common` (zx → `zx-types`); feature `fuchsia` on Fuchsia |
| `<lib>_rust_next_fidlgen` | as above with `--common-lib fidl_next_common_<lib_> --config configs/fuchsia.json` |
| `<lib>_rust_next`, crate `fidl_next_<lib_>` | the same settings; deps add `:<lib>_rust_next_common` and use the deps' `_rust_next` |

The IR is M8a's `<lib>` target (dependencies first in `fidlc`'s `--files` groups; Fuchsia
at HEAD, host at PLATFORM), shared with the `rust` flavor, so the IR order reviewed in
M8a applies unchanged.

**Naming rule (criterion 2).** `fidl_rust_next.gni`: crate
`${prefix}_next${common}_<lib_>`, prefix `fidl` (`fdomain` for FDomain, not built), `common`
= `_common` for the common crate, `<lib_>` the library name with `.` → `_`; the regular
crate is generated with `--common-lib fidl_next_common_<lib_>` and re-exports it. GN
targets `<lib>_rust_next`, `<lib>_rust_next_common` (groups over `…_internal`); in the
overlay those names are the `rust_library` targets themselves (Deviations).

**Visibility.** `fidl.gni` gives the public targets
`filter_labels_include(visibility, allowlist) + filter_labels_include(allowlist, visibility)`
with the phased-rollout allowlist `fidl_rust_next_allowlist`; `_allowlisted_visibility`
computes the same for Bazel visibility labels. All 17 libraries are public, so their
crates are visible to the allowlist: upstream's 22 entries mapped to `//vendor/fuchsia/…`
(checked against the revision by `regen.py`, below) plus the overlay's `//rules:__pkg__`
(the symbolic macro's own `fidl_next` dependency is checked against its defining package)
and `//tests/fidl:__pkg__`; `tests/test_regen.py` keeps those overlay entries outside
`//vendor/fuchsia`, since only the upstream part is checked against the revision. The
drift check reads the Bazel copy of the list (`build/rust/fidl_rust_next.bzl`); GN's copy
in `fidl_rust_next.gni` is LINT.IfChange-linked to it upstream and identical at this
revision. It runs only while a vendored BUILD file loads the list (the five `fidl_next*`
crates). The 5 upstream `fidl_next*` BUILD files load the same list for their
public aliases.

**Driver path (M9).** Written behind `_DRIVER_TRANSPORT = False` in
`rules/fidl_rust_next.bzl`: on Fuchsia, feature `driver` and
`//vendor/fuchsia/sdk/lib/driver/runtime/rust/fidl`, as GN (which forwards
`contains_drivers` only when `!is_host`). While off, a `contains_drivers` library gets no
`rust_next` targets (they would need `fdf_fidl`); M9 turns it on together with
`rules/fidl_rust.bzl`'s flag.

## Verification

Commands run from the worktree root; Bazel only in this worktree.

### Criterion 1: 17 / 17 for both targets

```
$ scripts/bazel build --lockfile_mode=error --config=fuchsia_x64 //vendor/fuchsia/src/lib/fidl/rust_next/... //vendor/fuchsia/sdk/lib/fuchsia-loom
INFO: Build completed successfully, 7 total actions
$ scripts/bazel build --lockfile_mode=error --config=fuchsia_x64 //vendor/fuchsia/sdk/fidl/... //vendor/fuchsia/zircon/...
INFO: Found 250 targets...          # 162 before M8b; +88 = 22 libraries x (2 generators + 2 crates)
INFO: Build completed successfully, 89 total actions
$ scripts/bazel build --lockfile_mode=error --config=fuchsia_arm64 //vendor/fuchsia/sdk/fidl/... //vendor/fuchsia/zircon/... //vendor/fuchsia/src/lib/fidl/rust_next/... //vendor/fuchsia/sdk/lib/fuchsia-loom
INFO: Found 261 targets...
INFO: Build completed successfully, 95 total actions
$ scripts/bazel cquery --config=fuchsia_{x64,arm64} 'kind("rust_library", //vendor/fuchsia/sdk/fidl/... + //vendor/fuchsia/zircon/...)' | grep -c rust_next
44                                  # both configs, the same 44 targets
```

The 44 are 22 libraries x 2: the 17 closure libraries, the 4 other vendored libraries
with `enable_rust_next` (`fuchsia.component.runtime` sets it explicitly;
`fuchsia.inspect`, `fuchsia.process.lifecycle` and `fuchsia.sys2` keep the default, True),
and zx (GN's
`zircon/vdso/zx` also has the flavor by default; nothing uses it, since FIDL deps on zx
become `zx-types`). `fuchsia.driver.framework` and `fuchsia.power.broker` have none (M9).
The 17 are pinned by `//tests/fidl:crate_names_next`, a Fuchsia-only `rustc_library` in
`:fuchsia_bindings` that the x64/arm64 build checks name explicitly, so a crate that
became incompatible would fail the build instead of being skipped (M6b's finding).

Flags and features (aquery, `--config=fuchsia_x64`, `fuchsia.io`; paths shortened):

```
FidlGenRustNext: --json fuchsia.io.fidl.json --output-filename fuchsia.io_rust_next_common.rs --rustfmt rustfmt --rustfmt-config rustfmt.toml --config common.json
FidlGenRustNext: --json fuchsia.io.fidl.json --output-filename fuchsia.io_rust_next.rs --rustfmt rustfmt --rustfmt-config rustfmt.toml --common-lib fidl_next_common_fuchsia_io --config fuchsia.json
Rustc fidl_next_fuchsia_io:        --edition=2024 --extern=fidl_next --extern=static_assertions --extern=fidl_next_fuchsia_unknown --extern=zx_types --extern=fidl_next_common_fuchsia_io --cfg feature="fuchsia" --allow=unused_crate_dependencies --deny=unused_results
Rustc fidl_next_common_fuchsia_io: --edition=2024 --extern=fidl_next --extern=static_assertions --extern=fidl_next_common_fuchsia_unknown --extern=zx_types --cfg feature="fuchsia" --allow=unused_crate_dependencies --deny=unused_results
```

The generated code does not test the `fuchsia` feature at this release (it gates on
`target_os = "fuchsia"`: 390 + 312 lines over the x64 outputs; no `feature =` gate), so it
is set for parity only; `fidl_next_bind` has its own `fuchsia` feature from its upstream
BUILD file.

**Generator parity (plan step 1).** `//tests/fidlgen:fuchsia_mem_rust_next_rule_parity_test`
and `…_rust_next_common_rule_parity_test` diff the rule's host output for `fuchsia.mem`
with M7's `FLAVORS` genrules (whose arguments the golden tests check against upstream's
goldens): identical, both pass. Negative check: with `--common-lib` removed from the rule,
`fuchsia_mem_rust_next_rule_parity_test` FAILED; restored, PASSED.

### Criterion 2: crate names

`tests/fidl/src/crate_names_next.rs` names each crate literally (`pub use
fidl_next_fuchsia_io;`, `pub use fidl_next_common_fuchsia_io;` … 34 lines) and builds for
x64 and arm64. `tests/test_fidl.py` keeps `_RUST_NEXT_LIBRARIES` equal to `pilot1.json`'s
`rust_next` libraries without `contains_drivers` (17) and the `.rs` file equal to the two
names per library.

### Criterion 3: `regen.py --check`, crate set

```
$ uv run scripts/regen.py --check
regen.py --check: vendor/fuchsia, third_party/crates match fuchsia.git b5274053cc0f1ba03cd0902a3da575ac9c31c152
```

`third_party/crates/` is unchanged by M8b (the 6 crates' crates.io deps — `munge`,
`zerocopy`, `pin-project`, `thiserror`, `futures`, `bitflags`, `static_assertions` — were
already in the closure's 121; `tests/test_crates_closure.py` passes).
`tests/test_fidl.py::test_rust_next_flavor_runtime_crates_are_vendored` walks
`pilot1.json` from every `_rust_next[_common]` target (driver runtime excluded) and gets
exactly the 6 new crates plus M8a's (`rust_constants`, `fuchsia-async(-macro)`,
`fuchsia-sync`, `zx*`), all listed `upstream`.

Fail-closed paths, first run without the patch:

```
regen.py: src/lib/fidl/rust_next/fidl_next_protocol/BUILD.bazel:53: test_deps names //third_party/rust_crates:futures, which regen.py cannot map; remove it with a patch under patches/fuchsia/src/lib/fidl/rust_next/fidl_next_protocol/ (unit tests are milestone M16)
```

and, in `tests/test_regen.py`, an overlay allowlist copy with a missing, changed or
reordered entry, or an upstream entry that is not a package spec, fails the run naming
`rules/fidl_rust_next.bzl` and the difference.

### Host

As M8a (host FIDL generated at PLATFORM, not compiled): `fidl_next_codec`,
`fidl_next_protocol` and `fuchsia-loom` compile on host (their host deps are all in the
closure), while `fidl_next_bind` depends on `fuchsia-async` (Fuchsia-only by M8a's patch),
so `fidl_next_bind`, `fidl_next_util`, `fidl_next` and every host `rust_next` crate are
incompatible and skipped by `//...`; building them by name says "is incompatible and
cannot be built". The host generators run (the parity tests use them). No host patch was
needed: nothing outside the closure is reached.

### Project checks (final tree)

| Check | Result |
|---|---|
| `uv run pytest` | 421 passed (406 before; +12 regen, +3 `test_fidl.py`) |
| `uv run reuse lint` | compliant (1190 / 1190 files) |
| `scripts/bazel build --lockfile_mode=error --config=fuchsia_x64 //... //third_party/crates:aliases //tests/fidl:fuchsia_bindings` | success, 401 targets (298 before) |
| same, `--config=fuchsia_arm64` | success, 401 targets |
| `scripts/bazel build --lockfile_mode=error //... //third_party/crates:aliases //third_party/crates:host_all` | success, 401 targets |
| `scripts/bazel test --lockfile_mode=error //...` | 58 tests: 55 passed, 3 skipped (the Fuchsia-only cap-lints tests for `zx`, `fuchsia-async`, `fuchsia-sync`); new: the 2 parity tests, `cap_lints_allow_fuchsia_loom_test` |
| `scripts/bazel test --lockfile_mode=error --config=fuchsia_x64 //tests/vendor/...` | 8 passed, 1 skipped (`cap_lints_allow_fuchsia_async_macro_test`: proc macros are Linux-only) |
| `uv run scripts/regen.py --check` | clean |
| `uv run scripts/check_sdk_files.py` | 0 missing (x64 18,323, arm64 18,497, host 15,669 files; 14/14/0 skipped as before) |
| `MODULE.bazel.lock` | unchanged |

### C1: downloads

Nothing new at build time: no crate was added, `fidlgen_rust_next` and its configs are
M7's. `regen.py` fetched the 6 directories' blobs and `build/rust/fidl_rust_next.bzl`
anonymously from fuchsia.git, as before.

### Disk (C6)

`uv run scripts/disk_report.py` after all builds: Bazel 10.95 of 12 GiB (10.81 after
M8a; +0.14), total 11.85 of 25 GiB, ok; 17.85 GiB free (17.83 after the review fixes, same
Bazel and total).

## Deviations from the plan text

- **`rules/fidl_rust_next.bzl`**, a sibling file (allowed by the entry), holds the flavor
  and the allowlist: vendored `fidl_next*` BUILD files load the list, so the file is
  loadable from `//vendor/fuchsia` (`visibility("public")`, as `fidl.bzl`).
- **GN's `_internal` + group pair collapsed:** `<lib>_rust_next[_common]` are the
  `rust_library` targets, with the allowlisted visibility.
- **Every `enable_rust_next` library gets the flavor** (22, zx included), as GN; the
  acceptance count is the closure's 17.
- **The allowlist**, not in the entry: GN restricts the bindings' visibility to it, and
  the upstream `fidl_next*` BUILD files load it, so `regen.py` needed a mapping for the
  load. Overlay additions: `//rules:__pkg__`, `//tests/fidl:__pkg__`.
- **`regen.py`: unmappable `test_deps` labels are provisional.** A patch cannot fix a
  label the rewriter rejects (patches apply to the rewritten file), so the rewriter keeps
  such a label inside `test_deps` and fails after the patches if it is still there.
  Not chosen: mapping `//third_party/rust_crates:<x>` to the vendor alias (it would make a
  label upstream's Bazel build does not define resolve, in any attribute).
- **Patch** `fidl_next_protocol/0001-drop-test-deps.patch`, not in the plan: as
  `fuchsia-async`'s `test_deps` (M8a); M16 revisits both.

## Findings for later milestones (also in the plan backlog)

- M9: turn on `_DRIVER_TRANSPORT` in both `rules/fidl_rust.bzl` and
  `rules/fidl_rust_next.bzl`; the second then declares the two driver libraries'
  `rust_next` crates with feature `driver` and `sdk/lib/driver/runtime/rust/fidl`.
- M10: the overlay's own driver packages are not in `fidl_rust_next_allowlist`; add them
  to `_OVERLAY_ALLOWLIST` if they use `rust_next` crates directly.
- M14/M15: `regen.py` now fails when upstream's allowlist changes; the rule itself is a
  hand port of `fidl_rust_next.gni` (blob IDs in its header) with the same drift risk as
  closure.py's template table.
- M16: `fidl_next_protocol`'s test deps (patch) and the provisional `test_deps` rule.

## Limitations and open items

- The two `contains_drivers` libraries have no `rust_next` crates until M9.
- Host `rust_next` bindings generated, not compiled (as M8a's `rust` flavor).
- FDomain and conversion crates not built (no pilot 1 user).

## Review

**Method:** a reviewer subagent with fresh context, launched by the orchestrator (the
plan's review method), before the checkpoint commit. It reviewed `ms/M8b` at `d6ad181`
(`wip` commits `e3e7b5f`, `f581e17`, `d6ad181`) against the design, the M8b entry, this
evidence and the diff from `5b9f58f`, without modifying anything (`MODULE.bazel.lock`
unchanged, Bazel 10.95 of 12 GiB). It re-verified the three criteria (both configs build;
44 `rust_next` crates = 22 libraries in each config, identical lists; the 5 extras correct
per GN's `enable_rust_next` default; literal crate names; aquery flags, edition and lints;
`regen.py --check` clean), parity with `fidl_rust_next.gni` at `b5274053`, that the
`_internal` + group collapse changes no crate name or visibility anything relies on, the
fail-closed `test_deps` check (patch removed: fails naming file:line), the allowlist drift
check (entry removed: fails), that `_DRIVER_TRANSPORT = False` declares nothing for the
driver libraries, and that no FIDL crate is skipped in the Fuchsia `//...` builds.
**Verdict:** land after fixes (process and documentation). Findings, with the
orchestrator's decisions:

| # | Severity | Finding | Decision / resolution |
|---|---|---|---|
| 1 | minor (record) | Notebook entries batched: three share 03:02, two share 03:08 (repeats the open process-log item) | Recorded: new process-log `instruction gap` entry; stamps not edited |
| 2 | minor (fix) | `_OVERLAY_ALLOWLIST` is unchecked: an upstream-looking entry (e.g. `//vendor/fuchsia/src/graphics:__subpackages__`) passes `--check` | Fixed: `test_the_overlays_own_allowlist_entries_are_outside_vendor_fuchsia` (pytest); negative check with that entry added: fails |
| n1 | nit | `//rules:__subpackages__` wider than needed | Narrowed to `//rules:__pkg__` (both macros are in package `//rules`); the three builds pass |
| n2 | nit | `fuchsia.component.runtime` sets `enable_rust_next = True` explicitly, not by default | Evidence corrected |
| n3 | nit | reuse count | Final number (1190) |
| n4 | nit | The drift check reads the Bazel copy of the list and runs only while a vendored BUILD file loads it; say so | Noted in `regen.py`'s comment and in this evidence (GN's copy is LINT.IfChange-linked and identical at this revision) |
| n5 | nit | Next session names only some `wip` commits | Names all three and the checkpoint |

**After the fixes:** pytest 421; reuse compliant (1190); `regen.py --check` clean; the
three builds with explicit targets under `--lockfile_mode=error` (401 targets each);
`bazel test //...` 55 passed + 3 skipped; disk Bazel 10.95 of 12 GiB, total 11.85 of 25;
`MODULE.bazel.lock` unchanged; plan `## ` headings equal the base's. No second review:
the fixes are one test, one narrowed visibility entry and documentation.
