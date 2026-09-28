<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# Notebook index

Updated: 2026-09-28T04:14-07:00

A row is stale when its chapter has an entry newer than "indexed through".

## Chapters

### [design — Design and planning](design.md)
Entries: 2026-09-27T17:29-07:00 through 2026-09-27T17:46-07:00
Outcome: open
- Design approved 2026-09-27 (incl. D6); plan draft 1 derived, awaiting owner read
- Pilots changed from dw-spi to simple/rust (emulator) then aml-saradc (VIM3)
- simple/rust binds only in a test realm (I3); fuchsia-cloud-dev's composite pci+acpi edu rule is the lead
- VIM3 already ships aml-saradc; replacement path needed (I4)
- rust_next generator is on pilot 1's critical path

### [I1 — SDK version → release revision](I1.md)
Entries: 2026-09-27T17:50-07:00 through 2026-09-27T18:06-07:00
Outcome: complete — `product_bundles.json` → build `source_manifest.json` gives the fuchsia.git rev; IDK CIPD `git_revision` = integration commit links the IDK
- 33.20260927.4.1 → b5274053…; 33.20260919.6.1 → 71dec18a…; every IDK .fidl blob present at each commit
- Dead ends: IDK meta/ has no revision; fuchsia.git has no release tags/branches
- CIPD `git_revision` (incl. fuchsia-cloud-dev pins) is the private integration commit
- fuchsia-bazel-rules CIPD lacks only 33.20260927.4.1; M1 pins IDK tarball + rules_fuchsia (decided)
- One integration commit ≠ one fuchsia.git rev (v20); keep builds-agree check; independent review after checkpoint

### [M1 — Repo scaffold and pinned release lock](M1.md)
Entries: 2026-09-27T18:08-07:00 through 2026-09-27T18:37-07:00
Outcome: complete — `resolve_pins.py` + `overlay.lock.json` for 33.20260927.4.1; two live runs byte-identical
- `resolve_pins.py`: one commit's files via depth-1 blobless fetch + `cat-file` (no sparse checkout)
- GCS has no SHA-256 for the IDK: stream 3 GB per run, check size + MD5 against GCS metadata
- `rules_fuchsia` CIPD instances are shared across releases (18 version tags on one)
- Review (before checkpoint): git inherited user config (C1); now isolated, tested with a hostile HOME
- `read(amt)` accepts truncated HTTP bodies; `digest` checks Content-Length

### [M2 — Bazel workspace and Fuchsia Rust toolchains](M2.md)
Entries: 2026-09-27T18:40-07:00 through 2026-09-27T19:24-07:00
Outcome: complete — both Fuchsia configs link hello_rust from a clean output base; review fixes applied

### [M2a — Fit the hosted disk budget](M2a.md)
Entries: 2026-09-27T19:30-07:00 through 2026-09-27T20:25-07:00
Outcome: complete — hosted profile: trimmed IDK 3.6 GB, Bazel caches 7.7 GiB of 12, total 8.2 of 25; review fixes applied
- HEAD prebuilts come from `arch/<cpu>/`; `obj/` holds only other levels. Keep `*meta.json` and dropped CPUs' sysroots (generator reads/globs them)
- Bazel caches every download by SHA-256, even without a checksum: cache policy = prune after fetch (`scripts/bazel`)
- A missing SDK file shows as an analysis error (`no such target`), not a missing path; `check_sdk_files.py` fails on unexpected ones
- Dead end: Python `tarfile` `r|gz` (>10 min); `r:gz` takes 48 s. Only `idk_trim.py` + `idk_extract.py` feed `@fuchsia_idk` (profile edits don't refetch)

### [M3 — Portable emulator harness at the lock's release](M3.md)
Entries: 2026-09-27T20:27-07:00 through 2026-09-27T21:11-07:00
Outcome: complete — `scripts/emu` boots the lock's core.x64 (TCG ~51 s), hello_rust logs, bundle pinned by digest; total 8.8 of 25 GiB
- QEMU is in the lock's IDK (`tools/x64/qemu_internal`) = fuchsia.git's jiri.lock pin: no `qemu` lock field
- Bundle: no upstream content pin; owner said pin it → `product_bundle` = SHA-256 over sorted "path\tsha256" lines (835 files)
- ffx: sockets in `<isolate>/data/emu/instances/<name>/`; a killed QEMU leaves a "staged" instance (only "running" counts)
- Build-info product "minimal" on core.x64 is normal (reviewer); Rust packaging needs `@fuchsia_sdk//pkg/fdio:dist`
- Dead end: probing plain-HTTP apt mirrors through a CONNECT-only proxy; apt hosts left out of the preflight

### [M4 — `rustc_*` rules with API-level cfgs](M4.md)
Entries: 2026-09-27T21:17-07:00 through 2026-09-27T21:38-07:00
Outcome: complete — cfgs at the toolchain level as upstream; wrappers add cap-lints
- Upstream generator is `build/bazel/versioning/rustc_api_level.bzl`; golden made by running it unmodified; GN emitter agrees
- IDK `version_history.json` is key-sorted (`10…32, 4…9`); upstream's script rejects it; port sorts numerically
- Dead end: select() on rules_fuchsia's API level fails host analysis when unset; host gets PLATFORM directly
- New repository rule in its own file so the 3 GB IDK is not refetched
- M3 checkpoint had deleted the plan's M4–M10/I2 entries; restored

### [M5 — Vendor stage of `regen.py`; `zx` crates build](M5.md)
Entries: 2026-09-27T21:45-07:00 through 2026-09-27T22:20-07:00
Outcome: complete — `regen.py vendor`/`--check`; `zx-types`, `zx-sys`, `zx-status(-ext)` build; `zx` → M6
- Upstream's crates.io crates are in fuchsia.git with crate_universe BUILD files; reused them + static.crates.io by Cargo.lock SHA-256 (option A: M6 continues)
- `zx` needs patched crates (`forks/libc`, `ask2patch/memchr` via `bstr`): deferred to M6
- Review: Fuchsia's LICENSE is BSD-2-Clause, mislabelled BSD-3 since M2; corrected repo-wide
- Review: regex rewriter missed `@rules_rust` loads; now ast-based, fails closed at file:line
- Git: depth-1 blobless fetch, then one by-ID fetch of the needed blobs (~16 s per run)

### [M6 — Pilot 1 closure measured (M6a; M6b uses M6b.md)](M6.md)
Entries: 2026-09-27T22:23-07:00 through 2026-09-27T23:34-07:00
Outcome: complete (M6a) — `closure.py` + `gn_eval.py`; `pilot1.json`: 69 in-tree, 44 direct / 121 crates.io (4 patched), 23 FIDL; M6b (crates build) planned
- Brief's regex walker misses bazel2gn variable deps, relative labels, proc_macro_deps: GN is now evaluated
- Review blocker: scope literals, forward_variables_from, foreach, same-file templates were dropped silently (lost vfs's deps); now evaluated, anything else is a recorded gap
- Review: FIDL template deps (`_common` siblings, `fidl_driver` for contains_drivers) modelled by a table from the release's .gni files
- Decided: `fuchsia_sync_detect_lock_cycles = false`; split rests on 121 transitive crates + the new patched-crate mechanism; `zx` → M6b
- Dead end: `git grep` / `ls-tree -l` in a blobless clone fetch every blob (twice)

### [M6b — Pilot 1's crates.io crates build](M6b.md)
Entries: 2026-09-27T23:37-07:00 through 2026-09-28T00:29-07:00
Outcome: complete — 121 crates generated (4 patched, committed under third_party/crates/src), zx builds, network-off builds pass; review fixes applied
- Patched crates: crate_universe BUILD files like vendor's; symlinked per file into @rust_crates (rctx.symlink + watch)
- Proc macros as top-level Fuchsia targets link as Fuchsia .so (-lfdio): build list keeps them host-only
- Not every crate compiles for Fuchsia: crate_universe features are per platform (synstructure/syn visit)
- 15 build scripts spawn only $RUSTC; pass with sandbox network off; no overrides
- Review: criterion 1 read as "built in the configuration it is used in; all for host" (orchestrator decision); crate groups named explicitly in the build checks

### [I2 — Prebuilt FIDL generators](I2.md)
Entries: 2026-09-28T00:32-07:00 through 2026-09-28T00:48-07:00
Outcome: complete — `fidlgen_rust_next` found in the public debug store, pinned (M7 fetches it); `fidlgen_rust` not published (M7 builds it)
- Build dirs' `tools/` has 8 tools, no generator; `build-ids.json` names `fidlgen_rust_next` → `buildid/<id>/executable` (anonymous)
- Stored gzip-encoded: pin the decoded SHA-256 (Bazel `http_file` gets decoded bytes)
- Build ID not recomputable; tie = release manifests + ID note + `.comment` toolchain revs = lock pins
- Dead ends: CIPD (no `fidl` package, incl. hidden), IDK `tools/` (cpp/hlcpp only)
- `fidlgen_rust` is Go, stdlib-only, upstream `BUILD.bazel`; built via Bazel upstream

### [M7 — FIDL generators as Bazel host tools](M7.md)
Entries: 2026-09-28T00:51-07:00 through 2026-09-28T01:53-07:00
Outcome: complete — both generators run under Bazel and match upstream goldens; review: land
- Lock gains `go` (fuchsia.git's `fuchsia/go` CIPD pin, go1.21.8) and `fidlgen_rust_next` (build-ids.json → debug store, ELF note checked)
- regen.py maps rules_go loads, drops Go test calls (fail-closed); upstream BUILD files otherwise unchanged
- Goldens: 17/20 until upstream's per-library flags (`--api-coverage`, `--include-drivers`) were passed
- rules_go asks go.dev for SDK hashes unless MODULE.bazel.lock has `facts` (kept); `bazel mod` pollutes the lockfile

### [M8 — FIDL Rust binding rule (M8a: `rust` flavor; M8b uses M8b.md)](M8.md)
Entries: 2026-09-28T02:06-07:00 through 2026-09-28T02:53-07:00
Outcome: M8a complete — 23 libraries' `rust` crates build for x64/arm64; split M8a/M8b (21 runtime crates); review: land after doc fixes
- FIDL libraries via regen.py: upstream `sdk/fidl/*/BUILD.bazel` rewritten, `idk` mode takes `.fidl` from the IDK; `fuchsia.sys2` from fuchsia.git
- Host FIDL at PLATFORM (`runtime_supported_api_levels`), Fuchsia at HEAD; tested (E0659 glob-ambiguity check on `NodeInfoDeprecated`)
- `fidl`/`fuchsia-async`/`fuchsia-sync` Fuchsia-only by patch (host needs `forks/tokio`); regen.py checks provisional host-branch labels after patches
- In-tree proc macro built as a Fuchsia `.so` under `//...`: `rustc_proc_macro` now host-only by default
- Driver transport deferred (as upstream's Bazel rule); orchestrator: M9 takes it (10 overlay crates)

### [M8b — FIDL Rust binding rule, `rust_next` flavor](M8b.md)
Entries: 2026-09-28T02:56-07:00 through 2026-09-28T03:31-07:00
Outcome: complete — 17 / 17 for both targets (22 libraries built); review fixes applied
- `rules/fidl_rust_next.bzl` from `fidl_rust_next.gni`/`fidl.gni`; generator parity with M7's FLAVORS by diff test
- GN's `fidl_rust_next_allowlist` visibility; regen maps upstream's load and checks the list against the revision
- `fidl_next_protocol` test_deps name a label upstream Bazel lacks: unmappable test_deps are provisional + patch
- Host: codec/protocol/loom compile; the rest incompatible via `fuchsia-async` (as M8a); driver libraries wait for M9

### [M9 — Pilot 1 in-tree crates (M9a: driver runtime; M9b, M9c use their own)](M9.md)
Entries: 2026-09-28T03:33-07:00 through 2026-09-28T04:14-07:00
Outcome: complete (M9a) — 11 driver runtime overlays; FIDL driver transport on; `rust_next` 19/19; review fixes applied
- Split before starting (52 crates left, 23 without Bazel); the rest split again at review: M9b (35), M9c (6, `fdf_component`)
- Overlays translated from BUILD.gn and machine-compared; C deps → IDK `pkg/async`, `async-default`, `driver_runtime_shared_lib` (cc_imports with shared libs)
- GN gives `driver` + `fidl_driver`/`fdf` to both `rust` and `rust_common`; `//tests/fidl:driver_transport` fails without either flavor's feature
- Corrected: macro-declared crates are visible to edges written in `//rules` (not a `select()` effect); only top-level targets need `//rules:__pkg__`

## Threads
- **Disk budget (C6):** [M2](M2.md) measured 20 GB of Bazel caches (9 GB free);
  [M2a](M2a.md) trims the IDK and prunes the cached tarball (7.7 GiB); [M3](M3.md) adds the
  emulator bucket (0.5 GiB; total 8.8 GiB, clean-slate peak about 9.6 GiB).
  [M4](M4.md) adds 0.06 GiB (total 8.82 GiB).
  [M5](M5.md) adds 0.17 GiB (`@rust_crates` and builds; total 8.99 GiB).
  [M6](M6.md) adds nothing (no Bazel input changed; total 8.99 GiB).
  [M6b](M6b.md) adds 1.3 GiB (121 crates built for x64, arm64, host and exec; total 10.30 GiB).
  [M7](M7.md) adds about 1 GiB (the release's Go SDK, rules_go, the Go builds; total 11.29 GiB).
  [M8](M8.md) adds 0.4 GiB (bindings for three configs; total 11.71 GiB, Bazel 10.81 of 12).
  [M8b](M8b.md) adds 0.14 GiB (`rust_next` bindings, 6 crates; total 11.85 GiB, Bazel 10.95 of 12).
  [M9](M9.md) (M9a) adds 0.04 GiB (11 driver runtime crates; total 11.90 GiB, Bazel 10.99 of 12).
- **Targeting HEAD (C3, R3):** [M2](M2.md) sets `--override_fuchsia_api_level=HEAD` in the
  Fuchsia configs; [M2a](M2a.md) trims non-HEAD `obj/` but keeps `version_history.json`;
  [M4](M4.md) derives the Rust cfgs from that file and asserts the HEAD branch at build time.
- **Vendored lints (`vendored = True`):** [M4](M4.md) adds the attribute (`--cap-lints=allow`)
  and the review decides every vendored target gets it; [M5](M5.md) makes regen.py add it
  to each `rustc_*` call and tests it in Bazel (`tests/vendor`).
- **Fuchsia license name:** [M2](M2.md) added Fuchsia's LICENSE as BSD-3-Clause and
  M3/M4 followed; the [M5](M5.md) review found it is the 2-clause text and M5 relabelled
  the repo (design C4 to amend).
- **Closure size (D8):** the brief measured 67/44/34 for dw-spi with a regex walker;
  [M6](M6.md) evaluates GN and measures pilot 1 at 69/44/23 (121 crates.io
  transitively; the first run's 66/45/24 missed forwarded deps and FIDL template deps),
  which split M6 into M6a/M6b.
  [M6b](M6b.md) generates exactly those 121 crates from 44 roots and builds them.
- **FIDL generators:** [I2](I2.md) finds `fidlgen_rust_next` only in the public debug store
  and `fidlgen_rust` unpublished; [M7](M7.md) pins the first per release in the lock and
  builds the second from vendored Go with the release's Go SDK; both match upstream goldens.
  [M8](M8.md) runs them from `rules/fidl_rust.bzl` on IR from the IDK's `fidlc`.
  [M8b](M8b.md) runs `fidlgen_rust_next` from `rules/fidl_rust_next.bzl`, diff-tested
  against M7's genrules.
- **Host vs Fuchsia API level:** [M4](M4.md) puts host cfgs at PLATFORM (rules_fuchsia's
  flag fails unset); [M8](M8.md) generates host FIDL at PLATFORM too, tested.
- **FIDL driver transport:** [M8](M8.md) finds it needs 10 in-tree crates without Bazel
  and defers it (as upstream's Bazel rule); [M8b](M8b.md) writes the `rust_next` driver
  path behind a flag; [M9](M9.md) (M9a) vendors the runtime as overlays, removes both
  flags and pins the transport with `//tests/fidl:driver_transport`.
