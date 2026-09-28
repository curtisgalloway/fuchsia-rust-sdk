<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M8b — FIDL Rust binding rule, `rust_next` flavor

Goal: the `rust_next` and `rust_next_common` flavors in the binding rule, the 6
`rust_next` runtime crates, and `rust_next` bindings for pilot 1's 17 libraries without
`contains_drivers` ([plan M8b](../implementation-plan.md)).
Verdict record: [M8b evidence](../evidence/M8b.md)

## 2026-09-28T02:56-07:00 — opening
Starting revision: `5b9f58f` (origin/main: I1, M1–M8a), branch `ms/M8b`.
Pre-existing changes: none; plan 32 `## ` headings. Relied on (orchestrator-verified,
rechecked at the end): pytest 406, reuse compliant, three builds + explicit targets under
`--lockfile_mode=error`, `bazel test //...` 52 + 3 skipped, `regen.py --check` clean,
disk Bazel 10.8 of 12 GiB.
Approach: read `build/rust/fidl_rust_next.gni` and `build/fidl/fidl.gni` at `b5274053`
with `git cat-file`; add the flavors to `rules/fidl_rust.bzl` (driver path written,
off); vendor the 6 crates via `vendor/crates.txt` + `regen.py`; extend `tests/fidl`.
Watch disk after the first full build (Bazel group budget 12 GiB).

## 2026-09-28T03:02-07:00 — attempt: reading the upstream templates at `b5274053`
From the M7 scratch clone (`git cat-file` on named paths): `build/rust/fidl_rust_next.gni`
(crate `${prefix}_next${common}_<lib_>`, edition 2024, version 0.1.0, no clippy, lints
allow_unused_crate_dependencies + deny_unused_results, deps `fidl_next:fidl_next_internal`
+ `static_assertions` + FIDL deps' `_rust_next[_common]_internal` (zx → `zx-types`),
feature `fuchsia` when is_fuchsia, `driver` + `sdk/lib/driver/runtime/rust/fidl` with
contains_drivers; `--config configs/{fuchsia,common}.json`, `--common-lib` for the regular
crate); `build/fidl/fidl.gni` (public groups `<lib>_rust_next[_common]` whose visibility is
the invoker's intersected with `fidl_rust_next_allowlist`; contains_drivers only when
!is_host). Upstream Bazel: `fidl_library.bzl` still `pass`es (fxbug.dev/454452299), but
`build/rust/fidl_rust_next.bzl` holds the allowlist in Bazel form, and the 5 `fidl_next*`
BUILD.bazel files load it for their public aliases (`fidl_next` → `:fidl_next_internal`).

## 2026-09-28T03:02-07:00 — surprise: `fidl_next_protocol`'s test_deps name `//third_party/rust_crates:futures`
That label does not exist in upstream Bazel (only Cargo files are exported there), and
regen.py's rewriter rejects any `//third_party/rust_crates:<x>` label. A patch cannot fix
it, since patches apply after the rewrite. Also: all 6 crates are `fuchsia`-context only in
pilot1.json; `fidl_next_bind` needs `fuchsia-async` unconditionally (Fuchsia-only by M8a's
patch), so host bindings become transitively incompatible without new host patches.

## 2026-09-28T03:02-07:00 — decision: rule shape, visibility, drivers, test_deps
- New `rules/fidl_rust_next.bzl` (loadable by vendored BUILD files): the allowlist and the
  flavor. regen.py maps `load("//build/rust:fidl_rust_next.bzl", "fidl_rust_next_allowlist")`
  there (like `@fuchsia_build_info`) and checks the overlay's copy of the upstream list
  against `build/rust/fidl_rust_next.bzl` at the revision, so a release that changes it fails
  regen.py (and `--check`). Overlay additions: `//rules:__subpackages__` (the symbolic macro's
  hard-coded deps are checked from its definition package) and `//tests/fidl:__pkg__`.
- Targets `<lib>_rust_next[_common]` are the `rust_library`s (GN's `_internal` + group
  pair collapsed); visibility = GN's intersection of the library's visibility with the
  allowlist.
- `contains_drivers` libraries: the driver branch is written behind a flag (off until
  M9) and their `rust_next` targets are not declared yet (they need `fdf_fidl`).
- Every library with `enable_rust_next` (default True, as GN and upstream Bazel) gets the
  flavor, zx included: 17 closure libraries + 4 others + zx (GN parity). Acceptance counts 17.
- test_deps: an unmappable label inside `test_deps` becomes provisional (the M8a
  mechanism): a patch must remove it or regen.py fails. `fidl_next_protocol` gets a patch
  dropping its test_deps, as `fuchsia-async`'s did (unit tests: M16). Not chosen: mapping
  `//third_party/rust_crates:<x>` to the vendor alias (makes a label upstream does not
  define resolve).

## 2026-09-28T03:07-07:00 — attempt: regen and first x64 build
`regen.py vendor` first failed as intended, naming `fidl_next_protocol/BUILD.bazel:53` (the
test dep); with `patches/fuchsia/src/lib/fidl/rust_next/fidl_next_protocol/0001-drop-test-deps.patch`
it passes, the allowlist check included; `third_party/crates/` unchanged. x64: the 6
runtime crates, then `//vendor/fuchsia/sdk/fidl/... //vendor/fuchsia/zircon/...` build
first time: 250 targets (162 before; +88 = 22 libraries x 2 generators + 2 crates).

## 2026-09-28T03:08-07:00 — decision: host handling, as M8a
arm64 builds the same 261 targets. On host, `fidl_next_codec`, `fidl_next_protocol` and
`fuchsia-loom` compile (their host deps are all in the closure: munge, zerocopy,
thiserror, pin-project, futures, rust_constants), while `fidl_next_bind`, `fidl_next_util`,
`fidl_next` and so every host `rust_next` crate are incompatible through `fuchsia-async`
(Fuchsia-only by M8a's patch), so `//...` skips them; the host generators still run (IR at
PLATFORM). No new host patch: nothing out of the closure is reached. Same outcome as M8a
(host FIDL generated, not compiled); recorded for the host-runtime backlog item.

## 2026-09-28T03:08-07:00 — attempt: tests
`tests/fidl:crate_names_next` (`pub use` of both crates of the 17 libraries) builds for
x64 and arm64 and joins `:fuchsia_bindings`. A parity diff test first placed in
`tests/fidl` failed on visibility (tests/fidlgen's genrules are package-private); moved to
`tests/fidlgen` (`fuchsia_mem_rust_next[_common]_rule_parity_test`), where the rule's host
output for fuchsia.mem equals M7's FLAVORS genrules byte for byte: both pass.

## 2026-09-28T03:13-07:00 — attempt: project checks and disk
Negative check: with `--common-lib` removed from the rule, `fuchsia_mem_rust_next_rule_parity_test`
fails; restored, it passes. aquery (x64, fuchsia.io): generator args in GN's order;
rustc `--cfg feature="fuchsia"`, `--allow=unused_crate_dependencies`, `--deny=unused_results`,
edition 2024; the generated code itself gates on `target_os`, not the feature. pytest 420;
reuse compliant (1189); `regen.py --check` clean; three builds with explicit targets, 400
targets each (298 before); `bazel test //...` 54 + 3 skipped; `--config=fuchsia_x64
//tests/vendor/...` 7 + 1 skipped before adding `fuchsia-loom`'s cap-lints test. Disk:
Bazel 10.95 of 12 GiB (+0.14), total 11.85 of 25; 17.85 GiB free.
