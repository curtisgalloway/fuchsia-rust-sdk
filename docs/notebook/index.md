<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# Notebook index

Updated: 2026-09-27T22:02-07:00

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
Entries: 2026-09-27T21:45-07:00 through 2026-09-27T22:02-07:00
Outcome: open (review pending) — `regen.py vendor`/`--check`; `zx-types`, `zx-sys`, `zx-status(-ext)` build; `zx` → M6
- Upstream's crates.io crates are in fuchsia.git with crate_universe BUILD files; reused them + static.crates.io by Cargo.lock SHA-256
- `zx` needs patched crates (`forks/libc`, `ask2patch/memchr` via `bstr`): M6's scope, so deferred
- Git: depth-1 blobless fetch, then one by-ID fetch of the needed blobs (~16 s per run)
- No per-crate LICENSE upstream: root LICENSE/PATENTS copied to `vendor/fuchsia/`
- `.bazelignore` needed so `overlays/<path>/BUILD.bazel` is not a package in place

## Threads
- **Disk budget (C6):** [M2](M2.md) measured 20 GB of Bazel caches (9 GB free);
  [M2a](M2a.md) trims the IDK and prunes the cached tarball (7.7 GiB); [M3](M3.md) adds the
  emulator bucket (0.5 GiB; total 8.8 GiB, clean-slate peak about 9.6 GiB).
  [M4](M4.md) adds 0.06 GiB (total 8.82 GiB).
  [M5](M5.md) adds 0.17 GiB (`@rust_crates` and builds; total 8.99 GiB).
- **Targeting HEAD (C3, R3):** [M2](M2.md) sets `--override_fuchsia_api_level=HEAD` in the
  Fuchsia configs; [M2a](M2a.md) trims non-HEAD `obj/` but keeps `version_history.json`;
  [M4](M4.md) derives the Rust cfgs from that file and asserts the HEAD branch at build time.
- **Vendored lints (`vendored = True`):** [M4](M4.md) adds the attribute (`--cap-lints=allow`)
  and the review decides every vendored target gets it; [M5](M5.md) makes regen.py add it
  to each `rustc_*` call and tests it in Bazel (`tests/vendor`).
