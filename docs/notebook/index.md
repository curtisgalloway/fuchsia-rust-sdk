<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# Notebook index

Updated: 2026-09-27T20:47-07:00

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
Entries: 2026-09-27T20:27-07:00 through 2026-09-27T20:47-07:00
Outcome: open — implemented and verified (boot 51 s TCG, hello_rust logs, total 8.8 of 25 GiB); review pending
- QEMU is in the lock's IDK (`tools/x64/qemu_internal`) = fuchsia.git's jiri.lock pin: no `qemu` lock field
- Product bundle has no content pin upstream (blobs merkle-named, images by path); harness checks versions, records SHA-256s
- ffx sockets live in `<isolate>/data/emu/instances/<name>/`; build-info product reads "minimal" for core.x64
- Rust packaging needs `@fuchsia_sdk//pkg/fdio:dist` explicitly; `bazel info --config=…` can't resolve `@rules_fuchsia`
- Plain-HTTP probes via a CONNECT-only proxy get the proxy's status; `ffx repository server list` shows stale entries

## Threads
- **Disk budget (C6):** [M2](M2.md) measured 20 GB of Bazel caches (9 GB free);
  [M2a](M2a.md) trims the IDK and prunes the cached tarball (7.7 GiB); [M3](M3.md) adds the
  emulator bucket (0.5 GiB; total 8.8 GiB, clean-slate peak about 9.6 GiB).
