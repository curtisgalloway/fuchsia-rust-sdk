<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M9b — Pilot 1's upstream-Bazel in-tree crates evidence

Design: [design](../design.md), revision "2026-09-27, draft 1", amended 2026-09-27;
unchanged in M9b.
Notebook: [M9b chapter](../notebook/M9b.md)
Starting revision and pre-existing changes: `006a91a` (origin/main: I1, M1–M9a), branch
`ms/M9b`; working tree clean; plan 34 `## ` headings. `wip` commit `ae467ad` (crates,
overlays, patches, `regen.py`, tests, notebook); evidence and plan follow; the checkpoint
commit `overlay: M9b — Pilot 1's upstream-Bazel in-tree crates` follows the review.

**Relied on:** the orchestrator's verified state at `006a91a` (pytest 424, reuse
compliant, the three builds with explicit targets under `--lockfile_mode=error`, 425
targets each, `bazel test //...` 55 + 6 skipped, `regen.py --check` clean). Disk was
measured again at the start (Bazel 10.99 of 12 GiB, total 11.90 of 25, 17.77 GiB free);
everything else was rechecked on the final tree (below). Also relied on: the lock
(`33.20260927.4.1`, fuchsia.git `b5274053…`), `docs/closure/pilot1.json` (M6a) and its GN
evaluator (`scripts/closure.py`, `scripts/gn_eval.py`), M9a's overlay mapping.

## Milestone definition

### The M9b entry as planned (moved from the plan)

**Design coverage:** R6 (pilot 1 set), D8. **Dependencies:** M9a.
**Decided (orchestrator, M9a review):** M9's remainder is split in two, as M9a
recommended: M9b is the 29 crates with upstream `BUILD.bazel` and the 6 overlays their
closure needs (35 crates); M9c the other 6 overlays.
**In scope:** 29 crates with upstream `BUILD.bazel` (`regen.py` `upstream` mode, patches
where a label cannot be mapped): `sdk/lib/c/rust`, `buf-read-ext`,
`diagnostics/{hierarchy,inspect,inspect/contrib,inspect/derive,inspect/derive/macro,
inspect/format,log,log/encoding,log/types,selectors}`, `directed_graph`, `fdio/rust`,
`fdomain/client`, `from-enum`, `fuchsia-component`, `fuchsia-component/{client,directory}`,
`fuchsia-fs`, `fuchsia-runtime`, `injectable-time`, `trace/rust`, `vfs/rust/name`,
`cm_fidl_validator`, `cm_graph`, `cm_rust`, `cm_types`, `moniker`; and 6 overlays
translated from `BUILD.gn`: `detect-stall`, `fuchsia-component/{escrow,runtime,server}`,
`src/storage/lib/trace`, `src/storage/lib/vfs/rust` (GN `rustc_dylib`). First
exec-config builds of `num-derive` and `paste`. `fuchsia_sync_detect_lock_cycles =
False` stays (M6a/M8a).
**Out of scope:** M9c's 6 overlays; pilot 2 crates; unit tests (M16); host builds of
Fuchsia-only crates.

##### Implementation steps
1. Vendor bottom-up (the layering in the [M9 evidence](evidence/M9.md)), building each
   crate before its dependants.
2. For each overlay, translate `BUILD.gn` (`sources`, `deps`, `edition`, `features`,
   `name`, crate type, visibility) into `overlays/<path>/BUILD.bazel` and check it against
   GN by hand, with M9a's mapping (stated in its overlay headers).
3. Any trim (a conditional dependency the walker counted, a host-only branch) becomes a
   `patches/fuchsia/…` file with a comment giving the reason.

##### Acceptance criteria
- [ ] The 35 crates build for both targets.
- [ ] `regen.py --check` is clean; every change against upstream is in `overlays/` or
  `patches/`; the generated crate set still equals the closure's.
- [ ] The evidence lists each patch with its reason and each `overlays/` file.

##### Testing and review
- Review focus: overlays against `BUILD.gn` (a missed feature flag compiles but changes
  behavior; `vfs` is a dylib in GN); patch minimality; upstream `BUILD.bazel` labels that
  `regen.py` cannot map.

##### Session sizing
35 crates, about 99k of the 108k remaining lines; 6 overlays. Split point: layers 0–3,
then 4–11. Disk: Bazel was at 10.99 of 12 GiB after M9a; measure after each layer.

##### Evidence and findings
Status: pending · Evidence: [M9b](evidence/M9b.md) · Notebook: [M9b](notebook/M9b.md)

### Deviations from the entry (decided in M9b; see the notebook)

- **`fuchsia-component` is an overlay, not an upstream crate.** Its upstream
  `BUILD.bazel` is an empty `filegroup` ("Unused stub target to satisfy Bazel genquery",
  fxbug.dev/500609897); GN's is the crate `fuchsia_component` (deps `client`,
  `directory`, `escrow`, `runtime`, `server`), which `fdf_component` (M9c) uses. M9b is
  **28 upstream + 7 overlays = 35 crates** (the entry said 29 + 6). The six planned
  overlays are the ones this crate needs.
- **`regen.py` gained three mappings** (the rewriter rejected these labels before any
  patch could apply): `//build/bazel/platforms:is_host_os` → `//rules:is_host_os` (a new
  `config_setting` on `HOST_OS_CONSTRAINTS`), `//zircon/system/ulib/trace-engine` →
  `@fuchsia_sdk//pkg/trace-engine`, and M8a's provisional rule for unlisted in-tree
  labels generalized from `//conditions:default` branches to any position (still
  fail-closed: `regen.py` fails after the patches, naming file:line, unless a patch
  removed the label). Tests in `tests/test_regen.py`.
- **`vfs` is built as an rlib** (GN: `rustc_dylib`), decision below.
- **Explicit build coverage**: `//tests/vendor:pilot1_crates`, named through
  `//tests/fidl:fuchsia_bindings` (M9a's route, so the check commands are unchanged).

## What was built

| File | What |
|---|---|
| `vendor/crates.txt` | 35 paths (28 `upstream`, 7 `overlay`), comment |
| `overlays/<path>/BUILD.bazel` ×7 | the overlays (table below) |
| `patches/fuchsia/<path>/0001-*.patch` ×17 | trims of upstream files (table below) |
| `vendor/fuchsia/<path>/` ×35 | generated by `regen.py`: upstream's files at `b5274053` + the rewritten/patched or overlay `BUILD.bazel`; 357 files, 99,168 `.rs` lines (each directory's count equals `pilot1.json`'s) |
| `third_party/crates/` | unchanged: the new BUILD files name no crates.io crate outside the closure's 121 |
| `scripts/regen.py` | the three mappings above; docstring |
| `rules/BUILD.bazel` | `config_setting` `is_host_os` (visible to `//vendor/fuchsia`) |
| `tests/test_regen.py` | trace-engine and `is_host_os` mappings; an unlisted label anywhere is provisional; message of a leftover provisional label |
| `tests/test_pilot1_crates.py` | 9 tests: the M9b set and modes; every closure crate but M9c's and the driver listed; upstream mode only where the closure saw a `BUILD.bazel` (and `fuchsia-component`'s stub); overlays verbatim, Fuchsia-only, GN's names/crate names/edition/features; `vfs` dylib → rlib documented; upstream files define the closure's targets with GN's crate names and features; no `test_deps` left; the 17 patches are on upstream crates |
| `tests/test_fidl.py` | the Fuchsia-only patch test finds every patch that adds `target_compatible_with` (now 8), and reads contexts without proc-macro targets |
| `tests/vendor/BUILD.bazel`, `src/pilot1_crates.rs` | 12 cap-lints tests (the public M9b crates); `:pilot1_crates` (`pub use` of `fuchsia_component`, `fuchsia_inspect_contrib`, `diagnostics_log_types`), which reaches 33 of the 35 (cquery) |
| `tests/fidl/BUILD.bazel` | `:fuchsia_bindings` also names `//tests/vendor:pilot1_crates` |

### The overlays

Each header records the `BUILD.gn` blob it translates and M9a's GN → Bazel mapping
(`overlays/sdk/lib/driver/runtime/rust/BUILD.bazel`), with one addition found in the
first build: GN takes proc macros in `deps`, rules_rust needs them in `proc_macro_deps`
(`vfs`'s `paste`). GN's "no visibility" is spelled `["//visibility:public"]` (a symbolic
macro's target is private otherwise). All are Fuchsia-only (the closure reaches them in
the fuchsia context only; their deps `fidl`/`fuchsia-async` are Fuchsia-only here).
Licensing as M9a: each carries its `BUILD.gn`'s Fuchsia copyright and Curtis Galloway's,
BSD-2-Clause.

| Overlay (`overlays/…/BUILD.bazel`) | Target → crate | `BUILD.gn` blob | Deps | GN-specific notes |
|---|---|---|---|---|
| `src/lib/detect-stall` | `detect-stall` → `detect_stall` | `a429c89a8f10` | 6 | visibility: GN's 8 entries mapped |
| `src/lib/fuchsia-component` | `fuchsia-component` → `fuchsia_component` | `b93857e1c868` | 5 | replaces upstream's stub `filegroup`; no unit tests in GN |
| `src/lib/fuchsia-component/escrow` | `escrow` → `fuchsia_component_escrow` | `19145c7c3a27` | 10 | |
| `src/lib/fuchsia-component/runtime` | `runtime` → `fuchsia_component_runtime` | `3fc658b228db` | 6 | |
| `src/lib/fuchsia-component/server` | `server` → `fuchsia_component_server` | `cc3e7bbc17fd` | 15 | `fidl_next` via its allowlisted alias |
| `src/storage/lib/trace` | `trace` → `storage_trace` | `fba9525293d1` | 1 | same-file template `rust_storage_trace` evaluated for Fuchsia (`enable_tracing = is_fuchsia`): feature `tracing`, dep `trace/rust`, `src/lib.rs` only; the testonly variants and the C++ targets are not translated |
| `src/storage/lib/vfs/rust` | `vfs` → `vfs` | `8b84c6e00779` | 19 (18 Rust + `pkg/trace-engine`, GN `public_deps`) | GN `rustc_dylib` built as an rlib; `vfs_rust_uses_log = is_host` is false, so no `log`/`use_log`; `bootfs` config (`-Copt-level=s`) not translated; `vfs_static` and the host `vfs` not translated |

**Decision: `vfs` as an rlib.** GN builds it for Fuchsia as a Rust dylib
(`libvfs_rust.so`, which `build/drivers/driver_shared_library_allowlist` lets a driver
load). rules_rust has no `dylib` crate type (`rust_shared_library` is a cdylib), and a
static link changes where the code lives, not what it does. Consequence for M10: an
in-tree reference driver that uses `vfs` lists `libvfs_rust.so` in `DT_NEEDED`; pilot 1
will not (a library fewer, not more).

### The patches

Each is applied by `regen.py` to the rewritten `BUILD.bazel`; its header gives the reason
(and, for dropped test deps, which crates or in-tree labels would otherwise be fetched or
fail; checked by script against the rewritten `test_deps`). Added lines are Apache-2.0,
context lines Fuchsia's BSD-2-Clause, as M8a's.

| Patch | Change | Reason |
|---|---|---|
| `src/lib/diagnostics/hierarchy/rust/0001-fuchsia-only.patch` | `test_deps` emptied; host (`is_host_os`) deps branch emptied; Fuchsia-only | host: `schemars` (outside the closure); tests: `assert_matches`, `serde_json`, `test-case`, `//src/lib/fuchsia`, `ffx/lib/writer` |
| `src/lib/diagnostics/inspect/format/rust/0001-drop-test-deps.patch` | `test_deps` emptied | `//src/lib/fuchsia` |
| `src/lib/diagnostics/inspect/rust/0001-drop-test-deps.patch` | `test_deps` emptied | `assert_matches`, `diagnostics-assertions`, `//src/lib/fuchsia` |
| `src/lib/diagnostics/log/encoding/rust/0001-drop-test-deps.patch` | `test_deps` emptied | `//src/lib/fuchsia` |
| `src/lib/diagnostics/log/rust/0001-drop-syslog-client-includes.patch` | `//sdk/lib/syslog:client_includes` removed | upstream's own comment: an empty stub in Bazel; in GN an `expect_includes` (the component manifest must include `syslog/client.shard.cml`); not vendored; the manifest check is M10's |
| `src/lib/diagnostics/log/types/0001-fuchsia-only.patch` | host (`//conditions:default`) deps emptied; Fuchsia-only | host: `schemars`, `serde` (feature `serde`) |
| `src/lib/diagnostics/selectors/0001-drop-test-deps.patch` | `test_deps` emptied | `assert_matches`, `tempfile`, `test-case`, `//src/lib/fuchsia` |
| `src/lib/fdio/rust/0001-drop-test-deps.patch` | `test_deps` emptied | `assert_matches`, `tempfile` |
| `src/lib/fdomain/client/0001-flex-fidl-only.patch` | `:client` and `:flex_fdomain` removed; `:flex_fidl`'s host branch emptied; Fuchsia-only | the closure uses only `:flex_fidl`; `:client` needs `fuchsia.fdomain` and `fidl_message` (outside the closure), `:flex_fdomain` needs `:client`; host: `fuchsia-emulated-handle` |
| `src/lib/fuchsia-component/client/0001-drop-test-deps.patch` | `test_deps` emptied | `assert_matches`, `fuchsia-component/tests` FIDL |
| `src/lib/fuchsia-component/directory/0001-drop-test-deps.patch` | `test_deps` emptied | `assert_matches` |
| `src/lib/fuchsia-fs/0001-drop-fdomain-and-tests.patch` | `_COMMON_TEST_DEPS` emptied; `:fuchsia-fs_fdomain`, the testonly `fidl_library` `fidl.test.schema` and its load removed | FIDL's fdomain flavor is not built (`//rules:fidl_rust.bzl`) and `:flex_fdomain` is removed; tests: `assert_matches`, `proptest`, `tempfile`, `//src/lib/fuchsia` |
| `src/storage/lib/vfs/rust/name/0001-drop-test-deps.patch` | `test_deps` emptied | `assert_matches` |
| `src/sys/lib/cm_fidl_validator/0001-drop-test-deps.patch` | `test_deps` emptied | `proptest`, `regex`, `test-case` |
| `src/sys/lib/cm_rust/0001-fuchsia-only.patch` | `test_deps` emptied; host deps branch emptied; `cm_rust` Fuchsia-only (its derive macro untouched) | host: `bitflags-serde-legacy` (not vendored), `serde`; tests: `difference`, `serde_json` |
| `src/sys/lib/cm_types/0001-drop-test-deps.patch` | `test_deps` emptied | `assert_matches`, `serde_json` |
| `src/sys/lib/moniker/0001-fuchsia-only.patch` | host deps branch emptied; Fuchsia-only | host: `schemars`, `serde` |

Minimality: the patches change only `test_deps`, host branches (plus the Fuchsia-only
mark that the emptied branch makes necessary, as M8a's), and whole targets outside the
closure. No source file and no Fuchsia-side dependency, feature or flag is changed. Eleven
upstream files needed no patch (`sdk/lib/c/rust`, `buf-read-ext`, `inspect/contrib`,
`inspect/derive`, `inspect/derive/macro`, `directed_graph`, `from-enum`,
`fuchsia-runtime`, `injectable-time`, `trace/rust`, `cm_graph`); `regen.py` drops the two
`rustc_test` targets (`inspect/contrib`, `log/rust`) as before.

## Verification

Commands run from the worktree root; Bazel only in this worktree. Logs in the run's
scratch directory (not committed).

### Cross-check of every crate against `BUILD.gn` (scripted)

M9a's script compared overlay text with regex-parsed GN and was not committed; this one
is new and checks the build itself, for the 28 upstream files as for the overlays. For
each closure target of the 35 directories it compares the Bazel compile (`aquery` of the
`Rustc` action: `--crate-name`, `--edition`, `feature` cfgs, `--extern` names, crate root;
`cquery labels(srcs, …)`) with the `BUILD.gn` target evaluated by `closure.py`'s GN
evaluator in the same context (fuchsia; host for proc macros). GN's expected externs come
from its `deps`, `public_deps` and `proc_macro_deps`: in-tree crates by the closure's
crate names, crates.io aliases by upstream's alias targets, FIDL deps by flavor
(`fidl_<lib>`, `fidl_<lib>_common`, `flex_<lib>`, …), groups expanded. Non-Rust deps are
listed as notes. (`sdk/lib/c/rust`: Bazel names GN's `zx-libc` target `rust`.)

```
sdk/lib/c/rust:rust [fuchsia, rlib]: OK crate=zx_libc externs=1 srcs=3 features=[]
src/lib/buf-read-ext:buf-read-ext [fuchsia, rlib]: OK crate=buf_read_ext externs=0 srcs=1 features=[]
src/lib/detect-stall:detect-stall [fuchsia, rlib]: OK crate=detect_stall externs=6 srcs=2 features=[]
src/lib/diagnostics/hierarchy/rust:diagnostics-hierarchy [fuchsia, rlib]: OK crate=diagnostics_hierarchy externs=10 srcs=5 features=[]
src/lib/diagnostics/inspect/contrib/rust:fuchsia-inspect-contrib [fuchsia, rlib]: OK crate=fuchsia_inspect_contrib externs=12 srcs=16 features=[]
src/lib/diagnostics/inspect/derive:fuchsia-inspect-derive [fuchsia, rlib]: OK crate=fuchsia_inspect_derive externs=6 srcs=2 features=[]
src/lib/diagnostics/inspect/derive/macro:fuchsia-inspect-derive-macro [host, proc-macro]: OK crate=fuchsia_inspect_derive_macro externs=3 srcs=1 features=[]
src/lib/diagnostics/inspect/format/rust:lib [fuchsia, rlib]: OK crate=inspect_format externs=9 srcs=12 features=[]
src/lib/diagnostics/inspect/rust:fuchsia-inspect [fuchsia, rlib]: OK crate=fuchsia_inspect externs=18 srcs=39 features=[]
src/lib/diagnostics/log/encoding/rust:rust [fuchsia, rlib]: OK crate=diagnostics_log_encoding externs=7 srcs=4 features=[]
src/lib/diagnostics/log/rust:no_startup_handle [fuchsia, rlib]: OK crate=driver_diagnostics_log externs=14 srcs=8 features=['no_startup_handle']
    note: non-Rust dep //sdk/lib/syslog:client_includes (expect_includes)
src/lib/diagnostics/log/types:types [fuchsia, rlib]: OK crate=diagnostics_log_types externs=3 srcs=2 features=[]
src/lib/diagnostics/selectors:selectors [fuchsia, rlib]: OK crate=selectors externs=10 srcs=6 features=[]
src/lib/directed_graph:directed_graph [fuchsia, rlib]: OK crate=directed_graph externs=0 srcs=1 features=[]
src/lib/fdio/rust:fdio [fuchsia, rlib]: OK crate=fdio externs=6 srcs=3 features=[]
    note: non-Rust dep //sdk/lib/fdio (zx_library)
src/lib/fdomain/client:flex_fidl [fuchsia, rlib]: OK crate=flex_client externs=3 srcs=1 features=[]
src/lib/from-enum:from-enum [fuchsia, rlib]: OK crate=from_enum externs=1 srcs=1 features=[]
src/lib/from-enum:from-enum-derive [host, proc-macro]: OK crate=from_enum_derive externs=4 srcs=1 features=[]
src/lib/fuchsia-component:fuchsia-component [fuchsia, rlib]: OK crate=fuchsia_component externs=5 srcs=1 features=[]
src/lib/fuchsia-component/client:client [fuchsia, rlib]: OK crate=fuchsia_component_client externs=12 srcs=2 features=[]
src/lib/fuchsia-component/directory:directory [fuchsia, rlib]: OK crate=fuchsia_component_directory externs=4 srcs=1 features=[]
src/lib/fuchsia-component/escrow:escrow [fuchsia, rlib]: OK crate=fuchsia_component_escrow externs=10 srcs=1 features=[]
src/lib/fuchsia-component/runtime:runtime [fuchsia, rlib]: OK crate=fuchsia_component_runtime externs=6 srcs=1 features=[]
src/lib/fuchsia-component/server:server [fuchsia, rlib]: OK crate=fuchsia_component_server externs=15 srcs=3 features=[]
src/lib/fuchsia-fs:fuchsia-fs [fuchsia, rlib]: OK crate=fuchsia_fs externs=14 srcs=9 features=[]
src/lib/fuchsia-runtime:fuchsia-runtime [fuchsia, rlib]: OK crate=fuchsia_runtime externs=5 srcs=1 features=[]
src/lib/injectable-time:injectable-time [fuchsia, rlib]: OK crate=injectable_time externs=3 srcs=2 features=[]
src/lib/trace/rust:trace [fuchsia, rlib]: OK crate=fuchsia_trace externs=5 srcs=1 features=[]
    note: non-Rust dep //zircon/system/ulib/trace-engine (zx_library)
src/storage/lib/trace:trace [fuchsia, rlib]: OK crate=storage_trace externs=1 srcs=1 features=['tracing']
src/storage/lib/vfs/rust:vfs [fuchsia, rlib]: OK crate=vfs externs=18 srcs=47 features=[]
    note: non-Rust dep //zircon/system/ulib/trace-engine (zx_library)
src/storage/lib/vfs/rust/name:name [fuchsia, rlib]: OK crate=name externs=5 srcs=2 features=[]
src/sys/lib/cm_fidl_validator:cm_fidl_validator [fuchsia, rlib]: OK crate=cm_fidl_validator externs=6 srcs=3 features=[]
src/sys/lib/cm_graph:cm_graph [fuchsia, rlib]: OK crate=cm_graph externs=3 srcs=1 features=[]
src/sys/lib/cm_rust:cm_rust [fuchsia, rlib]: OK crate=cm_rust externs=15 srcs=5 features=[]
src/sys/lib/cm_rust:cm_rust_derive [host, proc-macro]: OK crate=cm_rust_derive externs=4 srcs=1 features=[]
src/sys/lib/cm_types:cm_types [fuchsia, rlib]: OK crate=cm_types externs=9 srcs=1 features=[]
src/sys/lib/moniker:moniker [fuchsia, rlib]: OK crate=moniker externs=4 srcs=5 features=[]
```

37 of 37 targets agree (35 directories; `from-enum` and `cm_rust` also hold a derive
macro). The C deps are present on the Bazel side (`cquery deps(…, 1)`):
`vfs` and `trace/rust` → `@fuchsia_sdk//pkg/trace-engine`, `fdio` →
`@fuchsia_sdk//pkg/fdio`; `//sdk/lib/syslog:client_includes` is the patched-out
`expect_includes`. The checker was validated both ways: it passes M9a's 11 overlays (11
OK), and with `storage_trace`'s `crate_features` emptied (scratch edit, restored and
regenerated) it reports `features: bazel [] gn ['tracing']` and exits 1.

A second script checks the overlay fields the compile does not show, against the
evaluated GN: visibility (GN's mapped), version, `with_unit_tests`, target name,
`vendored`, Fuchsia-only: 7 of 7 OK (`vfs`'s GN `configs` = `bootfs`, recorded above).

### Criterion 1: the 35 crates build for both targets

Bottom-up by the M9 layering, measuring disk between the halves (the split point):

```
# layers 0-3 (20 packages, 22 targets), //vendor/fuchsia/<path>:all
$ scripts/bazel build --lockfile_mode=error --config=fuchsia_arm64 --keep_going <layers 0-3>
INFO: Found 22 targets...
INFO: 21 processes: 392 action cache hit, 1 internal, 20 linux-sandbox.
INFO: Build completed successfully, 21 total actions
(x64 likewise; the first x64 attempt named a package without :all, see the notebook)
disk: Bazel 11.09 of 12 GiB
# layers 4-11 (15 packages, 19 targets)
$ scripts/bazel build --lockfile_mode=error --config=fuchsia_x64 --keep_going <layers 4-11>
ERROR: ... vfs: ... listed ...paste... in its deps, but it is a proc-macro.
ERROR: ... escrow: Visibility error: target '...fuchsia-component/runtime:runtime' is not visible
INFO: Build succeeded for only 15 of 19 top-level targets
# after the two overlay fixes
INFO: Found 19 targets...
INFO: Build completed successfully, 5 total actions      (x64; arm64 the same)
```

No upstream source needed a change; every compile error was in my overlays (fixed as
above). The three proc macros (`fuchsia-inspect-derive-macro`, `from-enum-derive`,
`cm_rust_derive`) build for exec; `num-derive` and `paste` compiled for exec for the
first time (`bazel-out/k8-opt-exec/…/libnum_derive-*.so`, `libpaste-*.so`), as M9a
predicted. On host, the Fuchsia-only crates are skipped by `//...` (their `fidl`/
`fuchsia-async` deps are Fuchsia-only); the portable ones build (`buf-read-ext`,
`directed_graph`, `from-enum` and the three derive macros; cquery of the 41 targets).

### Criterion 2: `regen.py --check`, overlays/patches only, crate set = closure

```
$ uv run scripts/regen.py --check
regen.py --check: vendor/fuchsia, third_party/crates match fuchsia.git b5274053cc0f1ba03cd0902a3da575ac9c31c152
```

Every change against upstream is an `overlays/` file or a `patches/fuchsia/` file (tables
above); `vendor/fuchsia/` is generated. `third_party/crates/` is byte-identical to
`006a91a` (`git diff --stat` empty), so `test_crates_closure.py`'s "exactly
crates_io.transitive (121)" still holds.

### Criterion 3: the evidence lists each patch with its reason and each overlay

The two tables above.

### Project checks (final tree)

| Check | Result |
|---|---|
| `uv run pytest` | 435 passed (424 + 2 in `test_regen.py` + 9 in `test_pilot1_crates.py`; 1 changed in `test_fidl.py`) |
| `uv run reuse lint` | compliant (1651 / 1651) |
| `scripts/bazel build --lockfile_mode=error --config=fuchsia_x64 //... //third_party/crates:aliases //tests/fidl:fuchsia_bindings` | success, 479 targets (425 + 41 in the 35 packages + 12 cap-lints tests + `:pilot1_crates`) |
| same, `--config=fuchsia_arm64` | success, 479 targets |
| `scripts/bazel build --lockfile_mode=error //... //third_party/crates:aliases //third_party/crates:host_all` | success, 479 targets |
| `scripts/bazel test --lockfile_mode=error //...` | 55 passed, 18 skipped (Fuchsia-only cap-lints tests; 12 new) |
| `scripts/bazel test --lockfile_mode=error --config=fuchsia_x64 //tests/vendor/...` | 23 passed, 1 skipped (`fuchsia-async-macro`: proc macros are host-only) |
| `uv run scripts/regen.py --check` | clean |
| `uv run scripts/check_sdk_files.py` | 0 missing (x64 18,949, arm64 19,123, host 15,782 files) |
| `MODULE.bazel.lock` | unchanged (SHA-256 checked before and after the builds) |
| plan `## ` headings | same 34 as the base |

### C1: downloads

Nothing new at build time: `@fuchsia_sdk//pkg/trace-engine` is in the IDK already
fetched, and no crate was added. `regen.py` fetched the 35 directories' blobs anonymously
from fuchsia.git (one by-ID fetch, as before).

### Disk (C6)

`uv run scripts/disk_report.py`: Bazel 10.99 → 11.09 of 12 GiB after layers 0–3 (both
Fuchsia configs) → **11.36 of 12 GiB** after all 35 and the three build checks and tests;
total **12.27 of 25 GiB** (ok); 17.40 GiB free. M9b added 0.37 GiB; 0.64 GiB of the Bazel
group's budget is left for M9c (9,017 lines, `fdf_component` 2,898) and M10.

## Findings for later milestones (also in the plan backlog)

- **M10:** `vfs` is an rlib here, a dylib in GN: an in-tree driver's `DT_NEEDED` may list
  `libvfs_rust.so`, pilot 1's will not. `//sdk/lib/syslog:client_includes` (GN
  `expect_includes`: dependents' manifests include `syslog/client.shard.cml`) is patched
  out: the driver package's `.cml` must include the shard itself. Upstream Bazel and GN
  can name a crate's target differently (`sdk/lib/c/rust`: `rust` vs `zx-libc`).
- **M9c:** `diagnostics_log` (`log/rust:no_startup_handle`) and
  `diagnostics_log_encoding` are pinned only by `//...` until `fdf_component` depends on
  them; `fuchsia-component` (now built) is what `fdf_component` needs.
- **M14:** `closure.py`'s `upstream_bazel` means "a `BUILD.bazel` exists"; one is an
  empty stub (`fuchsia-component`). The crate-root rule counts `test_deps` (10 of the 17
  patches only empty `test_deps`; a later release may move their context lines).
- **M16:** the patches that empty `test_deps` (13 files) must be revisited with the unit
  tests, as M8a's and M8b's.

## Limitations and open items

- Unit tests of the 35 crates are not built (M16); host builds of the Fuchsia-only crates
  do not exist, as the closure.
- GN configs other than lints are not translated (e.g. `vfs`'s `bootfs` opt-level), as
  in M9a.

## Review

Pending (orchestrator).
