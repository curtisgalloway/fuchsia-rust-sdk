<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M9b — Pilot 1's upstream-Bazel in-tree crates

Goal: vendor pilot 1's 29 in-tree crates that have an upstream `BUILD.bazel` and the 6
overlays their closure needs (35 crates), building each for x64 and arm64
([plan M9b](../implementation-plan.md)).
Verdict record: [M9b evidence](../evidence/M9b.md)

## 2026-09-28T04:18-07:00 — opening
Starting revision: `006a91a` (origin/main: I1, M1–M9a), branch `ms/M9b`.
Pre-existing changes: none; plan 34 `## ` headings (saved to the run's scratch).
Relied on (orchestrator-verified; rechecked at the end): pytest 424, reuse compliant,
three builds + explicit targets under `--lockfile_mode=error` (425 targets each),
`bazel test //...` 55 + 6 skipped, `regen.py --check` clean. Disk measured now: Bazel
10.99 of 12 GiB, total 11.90 of 25 GiB, 17.77 GiB free.
Approach: bottom-up by the M9 layering; upstream crates through `regen.py`'s rewriter
(patch only what it cannot map); overlays translated from `BUILD.gn` at `b5274053` and
cross-checked field by field by a script (M9a's was not committed, so recreated).
Measure disk after layers 0–3 and at the end; stop at the split point if over budget.

## 2026-09-28T04:29-07:00 — surprise: `fuchsia-component`'s upstream `BUILD.bazel` is a stub
Read all 29 upstream `BUILD.bazel` files (`git cat-file` at `b5274053`).
`src/lib/fuchsia-component/BUILD.bazel` is an empty `filegroup` ("Unused stub target to
satisfy Bazel genquery", fxbug.dev/500609897); GN's is the real crate
`fuchsia_component` (deps client, directory, escrow, runtime, server), which
`fdf_component` (M9c) uses. It must be an overlay: M9b is 28 upstream + 7 overlays (still
35 crates). The 6 planned overlays exist because this crate needs them.

## 2026-09-28T04:29-07:00 — decision: three `regen.py` mappings instead of failing
The upstream files use labels the rewriter rejects before any patch can apply:
`//build/bazel/platforms:is_host_os` (select key; 5 files), `//zircon/system/ulib/trace-engine`
(`trace/rust`), and unlisted in-tree packages outside a `//conditions:default` branch
(`fdomain/client`'s `client` target: `fidl_message`, `fuchsia.fdomain`; `log/rust`'s
`//sdk/lib/syslog:client_includes`; `cm_rust`'s `bitflags-serde-legacy` in an
`is_host_os` branch). Added: `is_host_os` → `//rules:is_host_os` (a `config_setting` on
`HOST_OS_CONSTRAINTS`); trace-engine → `@fuchsia_sdk//pkg/trace-engine` (IDK has it);
M8a's provisional rule generalized from default branches to any position (still fails
after the patches unless a patch removes the label). Alternative rejected: listing
`fidl_message`/`fuchsia.fdomain` would grow the vendored set beyond the closure.
Tests: 128 in `test_regen.py` pass (3 new/changed).

## 2026-09-28T04:35-07:00 — attempt: 7 overlays, 17 patches, `regen.py vendor`
Overlays written by hand from the `BUILD.gn` files (read at 04:22–04:24): `detect-stall`,
`fuchsia-component` (+ `escrow`, `runtime`, `server`), `storage/lib/trace` (the
`rust_storage_trace` template evaluated for Fuchsia: feature `tracing`, dep `trace/rust`),
`vfs` (Fuchsia branch; `rustc_dylib` → `rustc_library`, decision below). Patches written
by a scratch script (structural edits on `regen.py`'s rewrite; the run's scratch directory is
not committed): 12 drop `test_deps` only, 4 also empty a host branch and mark the target
Fuchsia-only (`hierarchy`, `log/types`, `cm_rust`, `moniker`), `fdomain/client` keeps
only `flex_fidl`, `fuchsia-fs` drops `fuchsia-fs_fdomain` and the test FIDL library,
`log/rust` drops `//sdk/lib/syslog:client_includes`. Each header's crate lists were
checked by script against the rewritten `test_deps`. `regen.py vendor` (49 s): success;
`third_party/crates/` unchanged (the crate set still equals the closure's); every new
directory's `.rs` line count equals `pilot1.json`'s.

## 2026-09-28T04:35-07:00 — decision: `vfs` as an rlib
GN builds `vfs` for Fuchsia as a `rustc_dylib` (`libvfs_rust.so`, on the driver
shared-library allowlist). rules_rust has no `dylib` crate type (`rust_shared_library`
is a cdylib), and a static link changes where the code lives, not what it does; the
overlay's `vfs` is a `rustc_library`. Consequence for M10: the in-tree reference driver
may list `libvfs_rust.so` in `DT_NEEDED` and pilot 1 will not. GN's `bootfs` config
(`-Copt-level=s`) is not translated either (optimization only).

## 2026-09-28T04:35-07:00 — correction of the attempt entry above (7 overlays, 17 patches)
Its first version named the scratch directory by its absolute path; replaced with "the
run's scratch directory" (no home or scratch paths in committed text). Nothing else changed.

## 2026-09-28T04:37-07:00 — failed command: bare package labels on the first layer build
The layers 0–3 build named each package by its bare label; `inspect/derive/macro`'s
target is `fuchsia-inspect-derive-macro`, not `macro`, so the pattern failed to parse
(`--keep_going` built the other 21). Rerun with `<package>:all` for every package.

## 2026-09-28T04:37-07:00 — attempt: layers 0–3 build for x64 and arm64; disk
20 packages (22 targets: `log/types` also has `types-serde`, `from-enum` its derive
macro, built for exec; `inspect/derive/macro` is host-only and skipped by `:all` on
Fuchsia). x64 and arm64: success at the first attempt, no upstream source change needed
(arm64: 20 rustc actions). Disk: Bazel 11.09 of 12 GiB (+0.10), total 12.00 of 25.
Continuing with layers 4–11 (the split point is not needed so far).

## 2026-09-28T04:45-07:00 — failed command: layers 4–11, two analysis errors in my overlays
First build of the other 15 packages (x64, arm64): 15 of 19 targets built; two failed
analysis. (1) `vfs`: rules_rust rejects `paste` in `deps` ("it is a proc-macro. It
should instead be in … proc_macro_deps"); GN takes proc macros in `deps`. (2) `escrow` →
`runtime`: "not visible". GN's "no visibility" means public, but a symbolic macro's
target is private unless `visibility` is passed; M9a's overlays spell
`["//visibility:public"]` and mine did not. Fixed both (header mapping line added for
proc macros); public set explicitly on `escrow`, `runtime`, `server`,
`fuchsia-component`, `vfs`. Rerun: x64 and arm64 success (4 rustc actions each).

## 2026-09-28T04:45-07:00 — attempt: scripted cross-check of all 35 crates against GN
New scratch check (M9a's compared overlay text only): for each closure target, the
Bazel compile as `aquery` shows it (crate name, edition, `feature` cfgs, `--extern`
names, crate root) and `cquery labels(srcs)` against the `BUILD.gn` target evaluated
by `closure.py`'s GN evaluator in the same context (externs from GN deps: closure crate
names, crates.io alias targets, FIDL flavor crate names, groups expanded). Result: 37 of
37 targets OK (35 directories; `from-enum` and `cm_rust` also have a derive macro), for
the 28 upstream files as for the 7 overlays. Non-Rust GN deps noted: `sdk/lib/fdio`,
`trace-engine` (C, IDK), `//sdk/lib/syslog:client_includes` (patched out). The checker
also passes M9a's 11 overlays, and fails when `storage_trace`'s `tracing` feature is
removed (scratch edit, restored and regenerated). A second script checks the overlays'
visibility, version, `with_unit_tests`, names: 7 of 7 OK.

## 2026-09-28T04:45-07:00 — attempt: exec builds and disk after all 35
`num-derive` and `paste` compiled for exec (`k8-opt-exec`: `libnum_derive-*.so`,
`libpaste-*.so`) as proc macros of `fuchsia-runtime`, `inspect/format`, `hierarchy`,
`vfs` …; first exec builds, as M9a predicted. Disk: Bazel 11.36 of 12 GiB, total 12.27
of 25, 17.42 GiB free.

## 2026-09-28T04:50-07:00 — attempt: tests
`tests/test_pilot1_crates.py` (9 tests: the 28 + 7 modes, every closure crate but M9c's
and the driver listed, upstream mode only where `upstream_bazel`, overlays verbatim and
Fuchsia-only with GN's names/crate names/edition/features, `vfs` dylib→rlib documented,
upstream files define the closure targets with GN's crate names and features, no
`test_deps` left, 17 patches all on upstream crates). `test_fidl.py`'s Fuchsia-only
patch test failed on the new patches (it expected M8a's three by file name); now it finds
every patch adding `target_compatible_with` (8) and ignores proc-macro targets when
reading contexts (`cm_rust`'s derive macro is host code). `//tests/vendor`: 12 more
cap-lints tests (the public M9b crates) and `:pilot1_crates` (`pub use` of
`fuchsia_component`, `fuchsia_inspect_contrib`, `diagnostics_log_types`), named by
`//tests/fidl:fuchsia_bindings`; cquery: it reaches 33 of the 35 (not `log/rust`,
`log/encoding`, visible only inside `//vendor/fuchsia`; M9c's `fdf_component` uses
them). pytest 435 passed; reuse compliant (1651); `regen.py --check` clean.

## 2026-09-28T04:51-07:00 — attempt: project checks on the tree
Three builds with explicit targets under `--lockfile_mode=error`: 479 targets each
(425 + 41 in the 35 packages + 12 cap-lints tests + `:pilot1_crates`), success.
`bazel test //...`: 55 passed, 18 skipped (Fuchsia-only cap-lints tests, 12 new);
`--config=fuchsia_x64 //tests/vendor/...`: 23 passed, 1 skipped. `check_sdk_files`: 0
missing on all three. `MODULE.bazel.lock` unchanged. Disk: Bazel 11.36 of 12 GiB, total
12.27 of 25. Next: `wip` commit, then evidence and plan.

## 2026-09-28T04:54-07:00 — correction of the 04:35 attempt entry (patch counts)
It says "12 drop `test_deps` only"; recounted from the files while writing the evidence:
10 only empty `test_deps` (`inspect/format`, `inspect/rust`, `log/encoding`,
`selectors`, `fdio`, `fuchsia-component/client`, `directory`, `vfs/rust/name`,
`cm_fidl_validator`, `cm_types`); 13 empty `test_deps` in all (with `hierarchy`,
`cm_rust`, `fuchsia-fs`). The total of 17 stands (10 + 4 Fuchsia-only + `fdomain/client`
+ `fuchsia-fs` + `log/rust`).

## 2026-09-28T04:55-07:00 — checkpoint (stop before the checkpoint commit)
State: implemented, in review. 35 crates (28 upstream + 7 overlays, 17 patches) build for
x64 and arm64; the GN cross-check agrees for all 37 targets; project checks green (pytest
435, reuse, three builds at 479 targets, `bazel test` 55 + 18 skipped, `regen.py --check`,
`check_sdk_files`, lock unchanged); disk Bazel 11.36 of 12 GiB. Evidence written except
Review; plan: M9b entry condensed ("in review"), backlog (4 items, disk numbers), Next
session; `## ` headings equal the base. Next: the orchestrator's review, then fixes,
Review section, checkpoint commit.
