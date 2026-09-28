<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# M9b — Pilot 1's upstream-Bazel in-tree crates evidence

Design: [design](../design.md), revision "2026-09-27, draft 1", amended 2026-09-27;
unchanged in M9b.
Notebook: [M9b chapter](../notebook/M9b.md)
Starting revision and pre-existing changes: `006a91a` (origin/main: I1, M1–M9a), branch
`ms/M9b`; working tree clean; plan 34 `## ` headings. `wip` commits `ae467ad` (crates,
overlays, patches, `regen.py`, tests, notebook) and `1feb17c` (evidence, plan, index);
the checkpoint commit `overlay: M9b — Pilot 1's upstream-Bazel in-tree crates` follows
the review and carries its fixes.

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
  `//tests/fidl:fuchsia_bindings` (M9a's route), and, after review finding 3,
  `log/rust:no_startup_handle` and `log/encoding/rust:rust` named in the two Fuchsia
  build check commands (they are visible only inside `//vendor/fuchsia`).
- **After the review** (orchestrator decisions): the GN parity check is a committed
  project tool, `scripts/gn_crosscheck.py` (finding 1); `regen.py` fails if an overlay
  replaces an upstream `BUILD.bazel` that defines Rust (`check_upstream_stub`, nit); the
  hosted profile's Bazel sub-budget is **15 GiB** (was 12; the total stays ≤ 25 GiB, C6).

## What was built

| File | What |
|---|---|
| `vendor/crates.txt` | 35 paths (28 `upstream`, 7 `overlay`), comment |
| `overlays/<path>/BUILD.bazel` ×7 | the overlays (table below) |
| `patches/fuchsia/<path>/0001-*.patch` ×17 | trims of upstream files (table below) |
| `vendor/fuchsia/<path>/` ×35 | generated by `regen.py`: upstream's files at `b5274053` + the rewritten/patched or overlay `BUILD.bazel`; 357 files, 99,168 `.rs` lines (each directory's count equals `pilot1.json`'s) |
| `third_party/crates/` | unchanged: the new BUILD files name no crates.io crate outside the closure's 121 |
| `scripts/regen.py` | the three mappings above; `check_upstream_stub` (review nit); docstring |
| `scripts/gn_crosscheck.py` | the GN parity check (below), a project check (plan table) |
| `tests/test_gn_crosscheck.py` | 7 tests: GN dep resolution of every kind (in-tree, group, FIDL flavor, alias, host-only proc macro, C library, listed removal), an unresolvable dep fails, rustc argv and aquery parsing, the crate-type allowlist, both Fuchsia configs + host for proc macros, target selection |
| `scripts/overlay_profile.py`, `tests/test_overlay_profile.py`, `tests/test_disk_report.py`, `README.md` | hosted Bazel sub-budget 12 → 15 GiB (orchestrator decision); two over-budget fixtures moved above 15 |
| `rules/BUILD.bazel` | `config_setting` `is_host_os` (visible to `//vendor/fuchsia`) |
| `tests/test_regen.py` | trace-engine and `is_host_os` mappings; an unlisted label anywhere is provisional; message of a leftover provisional label; end to end, an unlisted plain dep fails after the patches; an overlay may replace only a stub upstream file |
| `tests/test_pilot1_crates.py` | 9 tests: the M9b set and modes; every closure crate but M9c's and the driver listed; upstream mode only where the closure saw a `BUILD.bazel`; overlays verbatim, Fuchsia-only, GN's names/crate names/edition/features; `vfs` dylib → rlib documented; upstream files define the closure's targets with GN's crate names and features (`select()` evaluated for Fuchsia); no `test_deps` left; the 17 patches are on upstream crates |
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
load). rules_rust has no `dylib` crate type (`rust_shared_library` is a cdylib). The
code is the same, but not its process-wide state (corrected after review finding 2):
`src/temp_clone.rs` keeps statics (`CLONES`, and `STATE`, which starts a 2-thread pool
on first use), so every binary that links `vfs` statically has its own copies, where
GN's drivers in one driver host share those of the one `libvfs_rust.so` (one pool per
driver instead of one per process). Benign for pilot 1. Consequences for M10: an
in-tree reference driver that uses `vfs` lists `libvfs_rust.so` in `DT_NEEDED`; pilot 1
will not (a library fewer, not more); and the per-driver copies of that state.

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

### GN parity: every crate against its `BUILD.gn` (`scripts/gn_crosscheck.py`)

M9a's script compared overlay text with regex-parsed GN and was not committed. Before the
review a scratch script compared the build itself (37 of 37 M9b targets agreed); after
review finding 1 it is a committed project check, `scripts/gn_crosscheck.py`. For each
closure target of the given `vendor/crates.txt` paths (or `--all`), under both Fuchsia
configs (and the host for proc macros), it compares what Bazel compiles with the
`BUILD.gn` target at the lock's revision, evaluated by `closure.py`'s GN evaluator in the
same context and read through `regen.py`'s git source:

- crate name, crate type, edition, `feature` cfgs, `--extern` names (one `aquery` of the
  `Rustc` actions per config), crate root and sources (`CrateInfo`, one `cquery`);
- GN's expected externs from `deps`, `public_deps`, `proc_macro_deps`: in-tree targets by
  their `BUILD.gn` crate names, crates.io aliases by upstream's alias targets, FIDL
  bindings by flavor, groups expanded, host-only proc macros found in the host context;
- C deps from a table (`NATIVE_DEPS`): the library must be in the target's `CcInfo`
  (transitively, the strongest statement the providers allow); `REMOVED_DEPS` lists
  `//sdk/lib/syslog:client_includes` with its patch;
- `crate_type` must equal GN's except in `CRATE_TYPE_DEVIATIONS` (`vfs`: dylib → rlib);
- any GN dep it cannot resolve fails the run (exit 2), as does any difference (exit 1).

Not compared (the docstring says so): GN configs and rustflags and Bazel's `rustc_flags`,
non-feature cfgs, visibility, version, test targets and `test_deps`, how dependents link.

```
$ uv run scripts/gn_crosscheck.py --all        # 14 s; git: one depth-1 blobless fetch
sdk/lib/async/rust/dispatcher:dispatcher [fuchsia_x64]: OK crate=libasync_dispatcher type=rlib externs=5 srcs=4 features=[] c_libs=['libasync-default.so', 'libasync.a']
src/storage/lib/trace:trace [fuchsia_x64]: OK crate=storage_trace type=rlib externs=1 srcs=1 features=['tracing'] c_libs=[]
src/storage/lib/vfs/rust:vfs [fuchsia_x64]: OK crate=vfs type=rlib (allowed: rules_rust has no dylib crate type (M9b)) externs=18 srcs=47 features=[] c_libs=['libtrace-engine.so']
src/lib/diagnostics/log/rust:no_startup_handle [fuchsia_arm64]: OK crate=driver_diagnostics_log type=rlib externs=14 srcs=8 features=['no_startup_handle'] c_libs=[]
src/lib/trace/rust:trace [fuchsia_arm64]: OK crate=fuchsia_trace type=rlib externs=5 srcs=1 features=[] c_libs=['libtrace-engine.so']
src/sys/lib/cm_rust:cm_rust_derive [host]: OK crate=cm_rust_derive type=proc-macro externs=4 srcs=1 features=[] c_libs=[]
gn_crosscheck.py: 62 crate directories, 64 targets: all agree with BUILD.gn
```

- `--all`: **62 directories, 64 targets, 124 (target, config) pairs agree**: M9b's 35
  (37 targets), M9a's 11, and M5–M8b's 16 (`zx*`, `fidl`, `rust_constants`,
  `fidl_next*`, `fuchsia-loom`, `fuchsia-async(-macro)`, `fuchsia-sync`).
- M9a + M9b paths only: 46 directories, **48 targets** agree (93 pairs: 45 × 2 Fuchsia
  configs + 3 proc macros on host).
- Negative: `storage_trace` with `crate_features = []` (scratch edit, restored and
  regenerated) → `features: bazel () gn ('tracing',)` under both configs, exit 1. Before
  the host retry for proc macros, the first `--all` run stopped with exit 2 on
  `fuchsia-inspect-derive-macro` (defined only `if (is_host)` in GN): the fail-closed
  path in practice.

The C deps it confirms: `libasync.a`, `libasync-default.so`, `libdriver_runtime.so`
(M9a), `libfdio.so` (`fdio`, `fuchsia-async`), `libtrace-engine.so` (`trace/rust`,
`vfs`), `libsync.a`. A second (scratch) script checked the overlay fields the compile does
not show against the evaluated GN: visibility (GN's mapped), version,
`with_unit_tests`, target name, `vendored`, Fuchsia-only: 7 of 7 OK (`vfs`'s GN
`configs` = `bootfs`, recorded above).

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

"The crate set equals the closure's" holds for directories and crates (every vendored
directory is a closure crate, every crates.io crate a closure crate), not for every Bazel
target (review finding 4): upstream files also define targets the closure does not use,
and `//...` builds them: `log/rust:rust` (`diagnostics_log`, beside the closure's
`no_startup_handle`), `log/types:types-serde`, and the aliases `inspect/contrib/rust:rust`
and `inspect/derive:derive`. They use only closure crates.

### Criterion 3: the evidence lists each patch with its reason and each overlay

The two tables above.

### Project checks (final tree)

| Check | Result |
|---|---|
| `uv run pytest` | 444 passed (424 + 4 in `test_regen.py` + 9 in `test_pilot1_crates.py` + 7 in `test_gn_crosscheck.py`; `test_fidl.py`, `test_overlay_profile.py`, `test_disk_report.py` changed) |
| `uv run reuse lint` | compliant (1654 / 1654) |
| `uv run scripts/gn_crosscheck.py --all` | 62 directories, 64 targets: all agree with `BUILD.gn` |
| `scripts/bazel build --lockfile_mode=error --config=fuchsia_x64 //... //third_party/crates:aliases //tests/fidl:fuchsia_bindings //vendor/fuchsia/src/lib/diagnostics/log/rust:no_startup_handle //vendor/fuchsia/src/lib/diagnostics/log/encoding/rust:rust` | success, 479 targets (425 + 41 in the 35 packages + 12 cap-lints tests + `:pilot1_crates`; the two log targets are among the 41) |
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
Fuchsia configs) → 11.36 of 12 GiB after all 35 and the three build checks and tests;
total 12.27 of 25 GiB; 17.40 GiB free. M9b added 0.37 GiB, which left 0.64 GiB of the
Bazel group's 12 for M9c (9,017 lines, `fdf_component` 2,898) and M10.

**Budget decision (orchestrator, 2026-09-28, at the M9b review):** with the total at
12.3 of 25 GiB but the Bazel group 0.64 GiB short of its cap, the hosted profile's Bazel
sub-budget rises from 12 to **15 GiB**; the owner's total (≤ 25 GiB, C6) is unchanged.
`scripts/overlay_profile.py`, its test, the README and the plan (Conventions, M2a) say
so. Final tree: Bazel **11.36 of 15 GiB**, total **12.28 of 25 GiB** (ok), 17.42 GiB
free.

## Findings for later milestones (also in the plan backlog)

- **M10:** `vfs` is an rlib here, a dylib in GN: an in-tree driver's `DT_NEEDED` may list
  `libvfs_rust.so`, pilot 1's will not, and `vfs`'s process-wide state (`temp_clone.rs`
  statics, a 2-thread pool) is per driver rather than per driver host. `//sdk/lib/syslog:client_includes` (GN
  `expect_includes`: dependents' manifests include `syslog/client.shard.cml`) is patched
  out: the driver package's `.cml` must include the shard itself. Upstream Bazel and GN
  can name a crate's target differently (`sdk/lib/c/rust`: `rust` vs `zx-libc`).
- **M9c:** `diagnostics_log` (`log/rust:no_startup_handle`) and
  `diagnostics_log_encoding` are named explicitly by the Fuchsia build checks; once
  `fdf_component` reaches them, M9c may drop those labels. `fuchsia-component` (now
  built) is what `fdf_component` needs. Run `scripts/gn_crosscheck.py` on each overlay.
- **M14:** `closure.py`'s `upstream_bazel` means "a `BUILD.bazel` exists"; one is an
  empty stub (`fuchsia-component`; `regen.py` now checks it stays one). The crate-root rule counts `test_deps` (10 of the 17
  patches only empty `test_deps`; a later release may move their context lines).
- **M16:** the patches that empty `test_deps` (13 files) must be revisited with the unit
  tests, as M8a's and M8b's.

## Limitations and open items

- Unit tests of the 35 crates are not built (M16); host builds of the Fuchsia-only crates
  do not exist, as the closure.
- GN configs other than lints are not translated (e.g. `vfs`'s `bootfs` opt-level), as
  in M9a.

## Review

**Method:** a reviewer subagent with fresh context, launched by the orchestrator (the
plan's review method), before the checkpoint commit. It reviewed `ms/M9b` at `ae467ad`
and `1feb17c` against the design, the M9b entry, this evidence and the diff from
`006a91a`, without modifying anything. It re-ran the three builds (479 targets each),
cquery counts, pytest, reuse, `regen.py --check` and `bazel test //...`; removed four
patches one at a time in a scratch copy (each run exits 2 naming file:line); re-ran the
scratch cross-check (37 OK); read 8 patches (only `test_deps`, host branches, targets
outside the closure and Fuchsia-only marks; no Fuchsia dep, feature, flag or source
touched); confirmed `fdomain/client` keeping only `flex_fidl`, the `log/rust` syslog
drop (upstream stubs it; the shard is in `simple_rust_driver.cml`), all 7 overlays
against `BUILD.gn`, the `fuchsia-component` stub, and the `is_host_os`/`trace-engine`
mappings. **Verdict:** land after fixes. The findings, with the orchestrator's decisions
and their resolutions:

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | major | The GN parity cross-check was a scratch script (scratch paths, notes instead of failures) | Decided: commit it. `scripts/gn_crosscheck.py` + 7 tests: repo-relative, GN through `regen.py`'s git source and `closure.py`'s evaluator, `crate_type` against an allowlist (`vfs`), fails on unresolvable deps (exit 2) and C libraries missing from `CcInfo`, both Fuchsia configs (+ host for proc macros), states what it does not compare. `--all`: 62 directories, 64 targets agree; M9a + M9b: 46 directories, 48 targets agree; negative edit exits 1. A project check in the plan and M9c's method ("Read first for M9c", M9c step 1) |
| 2 | minor | "A static link changes where the code lives, not what it does" is wrong for `vfs`: `temp_clone.rs` has process-wide statics (`CLONES`; `STATE` spawning a 2-thread pool), one copy per statically linked driver instead of one shared `libvfs_rust.so` | Corrected in the overlay header, this evidence and the plan (M9b limitations, backlog item for M10); notebook correction appended |
| 3 | minor | `log/rust` and `log/encoding` covered only by `//...` (silent-skip risk) | `//vendor/fuchsia/src/lib/diagnostics/log/rust:no_startup_handle` and `…/log/encoding/rust:rust` added to the x64 and arm64 build check commands (plan table); both builds pass with them |
| 4 | minor (record) | Non-closure targets are built too (`log/rust:rust`, `log/types:types-serde`, aliases `inspect/contrib/rust:rust`, `inspect/derive:derive`) | Recorded under criterion 2: "crate set equals the closure" holds for directories and crates, not every target |
| 5 | minor (record) | Notebook entries batched (04:29, 04:35, 04:45; the layers 4–11 failure written after its fix); the 04:35 correction replaced earlier text | Process-log `instruction gap` entry appended; no stamp edited |
| n1 | nit | reuse count to be the final one | 1654 / 1654 on the final tree |
| n2 | nit | `test_upstream_crates_define_the_closures_targets` treated `select()` features as `[]` | `tests/test_pilot1_crates.py` evaluates `select()` for Fuchsia (and top-level variables, list concatenation) |
| n3 | nit | `test_upstream_mode_only_where_upstream_has_bazel` checked the overlay's text, not upstream's stub | `regen.py`'s `check_upstream_stub` now fails any run where an overlay replaces an upstream `BUILD.bazel` that defines Rust (tested in `test_regen.py`), so upstream's stub is checked on every `regen.py` run; the pytest keeps the closure side |
| n4 | nit | No end-to-end test that a provisional label outside a default branch fails after the patches | `test_an_unlisted_plain_dep_left_after_the_patches_fails` |
| D | decision | Disk | The hosted Bazel sub-budget rises from 12 to 15 GiB (orchestrator, 2026-09-28): M9b left 0.64 GiB for M9c + M10 while the total was at 12.3 of 25; the total (C6) is unchanged. `overlay_profile.py`, tests, README, plan updated |

**After the fixes** (final tree): pytest 444; reuse compliant (1654); `regen.py --check`
clean; `gn_crosscheck.py --all` 62/64 agree; the three builds with explicit targets
(Fuchsia ones with the two log targets) under `--lockfile_mode=error`, 479 targets each;
`bazel test //...` 55 passed + 18 skipped; `check_sdk_files` 0 missing on all three;
`MODULE.bazel.lock` unchanged; disk Bazel 11.36 of 15 GiB, total 12.28 of 25 GiB; plan
`## ` headings equal the base's 34. No second review: the orchestrator decided the fixes;
the new tool and `regen.py` check are covered by their tests and by the runs above.
