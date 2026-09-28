<!-- Copyright 2026 Curtis Galloway -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

> **Copy.** Snapshot of `docs/drivers/rust-driver-oot-plan.md` from the private
> `curtisgalloway/fuchsia-ci` repo at `b061204`, kept here so sessions without that
> checkout can read it. Relative links (e.g. `out-of-tree-bus-drivers.md`) point into
> `fuchsia-ci`. The approved design is [`design.md`](design.md); where they differ, the
> design wins.

# Rust drivers out of tree: plan brief

**Purpose.** This is a self-contained brief for an agent (or engineer) who will
turn it into a detailed implementation plan. It states the goal, the
constraints, every upstream fact the plan depends on (with evidence paths), the
proposed architecture, the workstreams with acceptance criteria, and the open
questions. You should not need the conversation that produced it.

**Companion doc:** [`out-of-tree-bus-drivers.md`](out-of-tree-bus-drivers.md)
covers the C++ side and the wider "USB + core buses out of tree" question. This
brief covers only Rust.

**Evidence base (2026-09-27).**

| Source | Version | Notes |
|---|---|---|
| `fuchsia.git` `main` | `40c25c2c` | Sparse, blobless clone; `git grep` against `HEAD` covers the whole tree |
| Released IDK | `gs://fuchsia/development/33.20260927.4.1/sdk/linux-amd64/core.tar.gz` | Manifest extracted |
| Upstream Rust toolchain in CIPD | pin resolved anonymously | — |

Paths are relative to `fuchsia.git` unless marked otherwise. Anything marked
**[verify]** is believed but not confirmed.

---

## 1. Goal and definition of done

**Goal:** build Fuchsia DFv2 drivers written in Rust **outside `fuchsia.git`**,
against a released Fuchsia SDK, and run them on a device whose OS came from
that same release.

**Done (milestone 1):**
- `dw-spi` (`src/devices/spi/drivers/dw-spi`, ~2.0k LOC of Rust) builds in a
  standalone Bazel workspace with no `fuchsia.git` checkout at build time.
- It packages as a driver component.
- It loads and binds on a device or emulator running the matching release.

It is the chosen pilot because it is a real production Rust driver with a
modest dependency set.

**Done (milestone 2):**
- The workspace regenerates for a new SDK release with one command.
- A `fuchsia-ci` job does this automatically for each mirrored release.

**Explicitly not in scope:**
- Getting Rust into the official SDK. That is the long-term upstream fix (§8).
  This plan is the "add-on beside the SDK" route: faster, and it doubles as the
  prototype and evidence for that upstream proposal.

---

## 2. Constraints (fixed; do not re-litigate)

1. **Anonymous access only.** All upstream fetches must be anonymous HTTPS:
   git from `fuchsia.googlesource.com`, GCS, CIPD. This comes from repo
   policy in `AGENTS.md`.
2. **DFv2 only; no Banjo.** This comes from the project owner. Rust drivers
   upstream already are DFv2.
3. **Version lock is accepted.** The hardware FIDL these drivers use is
   `@available(added=HEAD)` / unstable. A HEAD-built driver runs only on an OS
   from the exact same SDK version (`docs/concepts/versioning/compatibility.md`
   lines 63–101). Every artifact in this plan is therefore pinned to one SDK
   version, and it gets regenerated per release rather than kept compatible
   across releases.
4. **This repo's code style applies** to any Python added here: Google style,
   `pyink` at 88 columns, `pylint`-clean, Apache 2.0 header, stdlib-only in
   `fuchsiaci/`. The add-on workspace itself should be a **separate repo**,
   not part of `fuchsia-ci`. Where it lives is an open question (§9).

---

## 3. Upstream facts the plan rests on

### 3.1 The released SDK has no Rust at all

- **Atom types.** The IDK has 519 atoms, of these types: `bind_library`,
  `cc_prebuilt_library`, `cc_source_library`, `companion_host_tool`,
  `dart_library`, `data`, `documentation`, `experimental_python_e2e_test`,
  `ffx_tool`, `fidl_library`, `host_tool`, `loadable_module`, `package`,
  `sysroot`, `version_history`. **No Rust type.** This was checked against
  `meta/manifest.json` of the released `core.tar.gz`.
- **Host tools.** The IDK ships `fidlgen_cpp` and `fidlgen_hlcpp`, but **not**
  `fidlgen_rust` or `fidlgen_rust_next`.
- **Orphaned schema.** `build/sdk/meta/rust_3p_library.json` defines a
  "third party Rust library" atom schema, but nothing references it. It is a
  leftover, not a plan.
- **Bazel SDK rules.** `rules_fuchsia` (`build/bazel_sdk/bazel_rules_fuchsia/`)
  has `fuchsia_wrap_rust_binary`
  (`fuchsia/private/fuchsia_rust.bzl`), which attaches package metadata to an
  already-built Rust *binary*. There is **no Rust driver rule**.

### 3.2 What the SDK does provide that Rust needs

- **Native libraries** the Rust driver stack links against are all in the IDK
  as prebuilts: `pkg/driver_runtime_shared_lib` (`libdriver_runtime.so`),
  `pkg/fdio`, `pkg/async-default`, plus `sysroot` (`sdk/manifests/fuchsia_idk.manifest`).
- **FIDL sources.** 33 of the 34 FIDL libraries in the pilot's closure ship in
  the IDK (§A.3). The one exception, `fuchsia.sys2`, comes in through
  `src/sys/lib/cm_rust`.
- **`fidlc` is in the IDK**, and it produces the JSON IR that the Rust
  generators consume.
- **Clang and sysroot** are already wired into the Bazel SDK as
  `@fuchsia_clang` and `@fuchsia_sdk//pkg/sysroot`.

### 3.3 The Rust driver ABI is small and C-shaped

- **One exported symbol.** A driver `.so` exports exactly one symbol,
  `__fuchsia_driver_registration__`. The version script is
  `build/bazel_sdk/bazel_rules_fuchsia/fuchsia/private/driver.ld`
  (`global: __fuchsia_driver_registration__; local: *;`).
- **Rust side.** In Rust, the `driver_register!` macro emits that static
  (`sdk/lib/driver/component/rust/src/macros.rs:57-63`). `dw-spi` uses it at
  `src/devices/spi/drivers/dw-spi/src/lib.rs:55`.
- **GN build.** A Rust driver is a `rustc_cdylib` via the `fuchsia_rust_driver`
  template (`build/drivers/fuchsia_driver.gni:200`). That template also emits
  a `-test-staticlib` for unit tests.
- **C++ reference rule.** `fuchsia_cc_driver.bzl` wraps `cc_shared_library`,
  adds the version script, links `@fuchsia_sdk//pkg/driver_runtime_shared_lib`,
  and passes `install_root = "driver/"`. `fuchsia_cc.bzl:107-130` optionally
  runs a restricted-symbols check against
  `fuchsia/private/driver_restricted_symbols.txt` (1,171 libc symbols drivers
  must not import).

### 3.4 Upstream's in-tree Bazel build already builds Rust

This is the most important finding. Most of the build logic this plan needs
already exists upstream, but only for the platform-internal Bazel build.

- **rules_rust.** `rules_rust` 0.69.0 is a dependency, with one local patch
  (`build/bazel/toplevel.MODULE.bazel:73-83`,
  `build/bazel/vendor_patches/rules_rust-0.69.0/`).
- **Toolchain definitions.** Rust toolchains for `x86_64-unknown-fuchsia` and
  `aarch64-unknown-fuchsia` live in `build/bazel/toolchains/rust/rust.BUILD.bazel`.
  They take `rust_std` from `lib/rustlib/<triple>/lib/*` of the prebuilt
  toolchain and use `@fuchsia_clang` for LLVM tools.
- **Library macros.** `build/bazel/rules/rust/` has `rustc_library`,
  `rustc_binary`, `rustc_proc_macro`, `rustc_test` and `rustc_embed_files`.
  These are thin wrappers over `rules_rust` plus Fuchsia flags
  (`common.bzl`: `--cap-lints`).
- **API-level cfg flags.** `build/bazel/versioning/rustc_api_level.bzl:20-45`
  turns an API level into
  `--cfg=fuchsia_api_level_at_least="N"` / `fuchsia_api_level_less_than="N"`
  for every known level. The pilot closure uses these cfgs ~160 times, so the
  add-on must replicate them.
- **FIDL Rust bindings.** `build/bazel/rules/fidl/fidl_rust_library.bzl`
  generates Rust FIDL bindings in the `fidl`, `common` and `fdomain` flavors
  by running `@//tools/fidl/fidlgen_rust`, a Go tool with its own
  `BUILD.bazel` (`go_binary_host_tool`).
  - **Gap:** there is **no `rust_next` flavor** in Bazel.
    `fidlgen_rust_next` is a Rust host binary with only a `BUILD.gn`
    (`tools/fidl/fidlgen_rust_next/`). `dw-spi` depends mostly on `_rust_next`
    bindings.
- **Third-party crates.** `build/bazel/update-rustc-third-party/` is a
  crate_universe-style generator (crate annotations, alias cleanup) driven by
  `third_party/rust_crates/Cargo.toml` and `Cargo.lock`. The lockfile has 666
  packages.
  - Some crates are locally patched via `[patch.crates-io]`:
    `byteorder`, `memchr`, `libc` and `tokio` in this closure. They come from
    `third_party/rust_crates/{ask2patch,intree,…}`.
- **Coverage of the closure.** Of the pilot's 67 in-tree crates, **42 already
  have a real `BUILD.bazel` using `rustc_library`** (§A.1). **25 do not**,
  and those are exactly the driver-specific ones: all of
  `sdk/lib/driver/*/rust`, `sdk/lib/async/rust*`, and a few
  `fuchsia-component` sub-crates.
- **dw-spi's own `BUILD.bazel`** is only a `fuchsia_prebuilt_package` wrapper
  around the GN-built archive. There is no Bazel Rust driver rule upstream.

### 3.5 The compiler: upstream's pinned toolchain is fetchable anonymously

- **Where it is pinned.** `manifests/toolchain` (lines 77–88) pins two CIPD
  packages at
  `git_revisions:c26ce708de5d14682647895d2f3caf38f70b5aa6,3493720eca95cf844a8d7e58fdd12e0e5644e7d0`:
  - `fuchsia/third_party/rust/host/${platform}`: the host rustc/cargo.
  - `fuchsia/third_party/rust/target/fuchsia`: the Fuchsia target std libraries.
- **Anonymous access confirmed.** Both resolved anonymously on 2026-09-27 via
  `POST https://chrome-infra-packages.appspot.com/prpc/cipd.Repository/ResolveVersion`.
  - Host linux-amd64 instance: `3a8ffdbe…`.
  - Target instance: `4fe0f40e…`.
  - Both were registered 2026-09-15 by `rust-prod-builder`.
- **Recommendation: use this pinned toolchain, not rustup stable.** It is the
  exact compiler the platform was built with, so `std`, codegen flags and lint
  behavior match.
- **Fallback: rustup stable.** It would probably work:
  - The closure uses only one nightly feature, `#![feature(c_size_t)]` in
    `sdk/lib/c/rust`, which is replaceable by `usize`.
  - Crates are edition 2024, so rustc ≥ 1.85 is required.
  - Official `*-unknown-fuchsia` std is tier 2 in rustup.
- **Per-release pin.** The toolchain pin for any given release comes from
  `manifests/toolchain` at that release's `fuchsia.git` commit.

### 3.6 Mapping an SDK version to a source commit

- **Why it matters.** Every generated or vendored piece must come from the
  `fuchsia.git` commit that produced the SDK: crates, FIDL bindings, the
  toolchain pin, `Cargo.lock`.
- **This repo already has the mapping.** It records `source_manifest.json`
  per mirrored build (see `ci-architecture.md` and `fuchsiaci/`).
- **[verify]** That the IDK release `33.20260927.4.1` maps to a specific
  `fuchsia.git` revision through the same mechanism, for SDK builds as opposed
  to product builds. The handoff doc
  `fuchsia-release-artifacts-ci-handoff.md` has the Buildbucket/GCS probe
  recipes.

---

## 4. The dependency closure (what has to be built)

Computed by walking GN `deps` from three roots:
`//sdk/lib/driver/component/rust`, `//sdk/lib/driver/runtime/rust` and
`//src/devices/spi/drivers/dw-spi`. The walk excludes `test_deps` and stops at
non-Rust targets. The script is in §B.

| Kind | Count | Notes |
|---|---|---|
| In-tree Rust crates | 67 | ~163k lines of `.rs`, including inline `#[cfg(test)]` code; 42 have Bazel builds, 25 don't (§A.1) |
| crates.io crates | 44 (direct) | Versions pinned from `Cargo.lock` (§A.2); 4 are locally patched; the full transitive set is larger |
| FIDL libraries needing Rust bindings | 34 | 33 in IDK; `fuchsia.sys2` is not (§A.3) |
| Native libraries | 3 + sysroot | All in IDK |

**Known imprecision (the planner should budget a trimming pass):**

- **Upper bound.** The walker ignores GN conditionals (`if (is_host)`,
  `if (is_fuchsia)`, feature toggles), so the closure is an upper bound.
  Heavyweights that are probably conditional or trimmable include:
  - `cm_fidl_validator` (12k lines)
  - `process_builder`, `elf_parse`
  - `fdomain/client`
  - `diagnostics/selectors`

  Several arrive via `fuchsia-component`, `inspect` or `cm_rust`.
- **Missed dependency.** The walker drops `rustc_dylib` targets, so
  `src/storage/lib/vfs/rust` (the `vfs` crate, reached from
  `fuchsia-component/server`) is missing from the counts and **must be
  added**.

---

## 5. Proposed architecture

A standalone Bazel workspace, the **overlay**, that combines four things:

```
overlay-workspace/
├── MODULE.bazel            # rules_fuchsia (pinned to SDK version) + rules_rust 0.69.0 (+ upstream patch)
├── toolchain/              # repo rule: fetch CIPD rust host+target at the release pin; define
│                           #   rust_toolchain()s for {x86_64,aarch64}-unknown-fuchsia (port of
│                           #   build/bazel/toolchains/rust/rust.BUILD.bazel)
├── rules/
│   ├── rustc_library.bzl   # port of build/bazel/rules/rust/* (+ api-level cfg select)
│   ├── fidl_rust.bzl       # fidl/common flavors (port of fidl_rust_library.bzl) + NEW rust_next flavor
│   └── fuchsia_rust_driver.bzl  # NEW: rust_shared_library + driver.ld + libdriver_runtime.so → fuchsia_driver_component
├── third_party/crates/     # crate_universe output from the release's Cargo.lock (+ the 4 patched crates)
├── vendor/fuchsia/<rev>/   # generated: the 67 in-tree crates copied at the SDK's fuchsia.git rev,
│                           #   each with a BUILD.bazel (42 copied from upstream, 25 generated/hand-written)
├── tools/                  # fidlgen_rust (Go) and fidlgen_rust_next (Rust), built from source at <rev>
├── drivers/dw_spi/         # the pilot
└── regen.py                # one command: SDK version → rev → refresh toolchain pin, crates, vendor/, bindings
```

**Key design choices, and why:**

- **Bazel, not Cargo.** The C++ out-of-tree path is Bazel (`rules_fuchsia`),
  and upstream's Rust Bazel rules exist to port. Packaging and assembly
  (`fuchsia_driver_component`, `fuchsia_package`,
  `fuchsia_board_input_bundle`) are Bazel-only. A Cargo build would still
  need a Bazel packaging step at the end.
- **Vendor source, don't fork.** `vendor/` is regenerated from upstream at a
  commit, never hand-edited. Local fixes (for example the `c_size_t` swap, or
  trimming a conditional dependency) live as patch files applied by
  `regen.py`, so each release bump is mechanical.
- **Build the FIDL generators from source**, since they are not SDK host
  tools. `fidlgen_rust` is Go, with upstream `BUILD.bazel` (it needs
  `rules_go`). `fidlgen_rust_next` is Rust, with only a `BUILD.gn`, so it
  needs a hand-written Bazel build.
  - **Alternative [verify]:** download prebuilt host-tool binaries from the
    release's build artifacts in GCS, if they are published there. That would
    avoid building them.
- **Generate FIDL bindings from IDK FIDL sources**, using the IDK's `fidlc`.
  Do not copy bindings pre-generated by upstream CI; they aren't published.

---

## 6. Workstreams

Each has an acceptance check. The order is the recommended dependency order.
Estimates assume one engineer who knows Bazel and Rust; they are estimates,
not measurements.

### W0. Pin resolution (1 day)

**Input:** an SDK version, e.g. `33.20260927.4.1`.

**Output:** a lockfile (`overlay.lock.json`) containing:
- the `fuchsia.git` revision
- the CIPD toolchain instance IDs (host + target)
- the `rules_fuchsia` CIPD version
- the `Cargo.lock` hash

**Acceptance:** the script is deterministic, and every field is traceable to
an upstream artifact.

### W1. Toolchain (2–3 days)

**Work:**
- A repository rule fetches both CIPD packages anonymously.
- Define `rust_toolchain`s for x64 and arm64 Fuchsia by porting
  `build/bazel/toolchains/rust/rust.BUILD.bazel`.
- Link via `@fuchsia_clang` with the IDK sysroot.

**Acceptance:** `sdk/rust/zx-types`, `zx-sys` and `zx` build as `rust_library`
for both Fuchsia targets. A trivial `fuchsia_wrap_rust_binary` hello-world
links against `libfdio.so`.

This is the smallest proof that the approach works. **Start here.**

### W2. Library rules and API-level cfgs (2 days)

**Work:** port `rustc_library` / `rustc_proc_macro` / `rustc_test` and
`rustc_api_level.bzl`.
- The API-level list comes from the IDK's `version_history.json`.
- Target `HEAD`, per constraint 3.

**Acceptance:** a crate using `#[cfg(fuchsia_api_level_at_least = "HEAD")]`
compiles with the expected branch taken.

### W3. Third-party crates (3–5 days)

**Work:**
- Run crate_universe (or port `build/bazel/update-rustc-third-party`) over the
  release's `third_party/rust_crates/Cargo.toml` and `Cargo.lock`.
- Restrict to the transitive closure of the 44 direct crates.
- Vendor the 4 patched crates (`byteorder`, `memchr`, `libc`, `tokio`) from
  `third_party/rust_crates/ask2patch|…` at the same commit.

**Acceptance:** every crate in §A.2 builds for both Fuchsia targets.

**Risk:** proc-macro crates (`syn`, `quote`, `proc-macro2`, `darling`,
`strum_macros`, `async-trait`, `num-derive`, `pin-project`) must build for the
**host** exec platform. Configure the host toolchain from the same CIPD host
package.

### W4. FIDL generators and binding rules (4–6 days)

**Work:**
- Build `fidlgen_rust` (Go; needs `rules_go` plus `tools/fidl/lib/fidlgen`).
- Build `fidlgen_rust_next`. It is Rust, with templates via askama
  (`askama.toml`), so check `tools/fidl/fidlgen_rust_next/BUILD.gn` for its
  crate dependencies.
- Port `fidl_rust_library.bzl` and add a `rust_next` flavor. Mirror the GN
  template to find the crate naming and flags; grep `//build/fidl` for
  `rust_next` **[verify: GN template location]**.

**Acceptance:** Rust and `rust_next` bindings for all 33 IDK FIDL libraries in
§A.3 compile. Resolve `fuchsia.sys2`, either by trimming `cm_rust` out of the
closure or by pulling that FIDL source from `fuchsia.git` at the same commit.

### W5. Vendor the 67 in-tree crates (5–7 days)

**Work:**
- `regen.py` copies each crate directory at the pinned revision.
- For the 42 with upstream `BUILD.bazel`: copy it, rewriting labels (`//…` to
  `//vendor/fuchsia/…`, and `//third_party/rust_crates:x` to the
  crate_universe label).
- For the 25 without: generate `BUILD.bazel` from `BUILD.gn` (the `sources`,
  `deps`, `edition`, `features` and `name` fields are regular enough to
  translate), then hand-fix.
- Apply the trim patches (§4), and add the `vfs` crate.

**Acceptance:** `fdf_component`, `fdf` (runtime), `mmio`, `pdev`,
`fdf_power`, `fdf_metadata` and `fdf_resource` all build for both targets.

### W6. `fuchsia_rust_driver` rule (3–4 days)

**Work:** build a `rust_shared_library` (crate type `cdylib`) with:
- link flags `-Wl,--version-script=driver.ld`, reusing the file from
  `rules_fuchsia`
- `@fuchsia_sdk//pkg/driver_runtime_shared_lib` linked in
- the output fed to a provider compatible with what
  `fuchsia_driver_component` expects (see how `fuchsia_cc` produces
  `FuchsiaPackageResourcesInfo` and `FuchsiaUnstrippedBinaryInfo` with
  `install_root = "driver/"` in `fuchsia/private/fuchsia_cc.bzl`)
- the restricted-symbols check (`//fuchsia/tools:check_restricted_symbols`)
- a `-test-staticlib` equivalent, if unit tests are in scope

**Acceptance:**
- The output `.so` exports only `__fuchsia_driver_registration__` (check with
  `llvm-readelf --dyn-syms`).
- It passes the restricted-symbols check.
- It has `DT_NEEDED` only on `libdriver_runtime.so`, libc/`libzircon`, and
  whatever the in-tree GN build of the same driver needs. Compare against the
  upstream-built `dw-spi` package extracted from a release product bundle,
  which this repo already mirrors.

**Risk:** Rust `std` may pull in libc symbols on the restricted list. Compare
with what the in-tree build does for Rust drivers (it may use a
driver-specific config, e.g. `//build/config/rust:bootfs` as seen in dw-spi's
`BUILD.gn`).

### W7. Pilot: dw-spi end to end (4–5 days)

**Work:**
- Port `dw-spi`'s `BUILD.gn`. Its DML file (`meta/dw-spi.dml`) is compiled by
  `dmlc`, which is not in the SDK, so replace it with hand-written `.bind` and
  `.cml`. The goldens may be checked in upstream; the C++ agent found that
  pattern for other drivers.
- Build the package, then either:
  - put it in a board input bundle (`fuchsia_board_input_bundle`,
    `base_driver_packages`), or
  - on an `eng` product, use `ffx driver register` (ephemeral drivers are
    enabled only for `eng` at Standard feature-set level:
    `src/lib/assembly/platform_configuration/src/subsystems/driver_framework.rs:67-90`).

**Target hardware:**
- `dw-spi` needs DesignWare SPI hardware.
- The lab's VIM3 (Amlogic) uses `aml-spi`, not dw-spi **[verify: which lab
  board, if any, has a DesignWare SPI block; otherwise acceptance is "loads
  and fails to bind cleanly" plus unit tests]**.
- Alternative pilot with lab hardware: a Rust driver that binds on something
  present in the lab. Picking it is a planner decision; see §9.

**Acceptance:** `ffx driver list` shows the driver loaded, and (with
hardware) bound.

### W8. Regeneration and CI (3–5 days)

**Work:**
- `regen.py <sdk-version>` redoes W0, W3, W4 (bindings) and W5 end to end,
  then runs the build.
- A `fuchsia-ci` job calls it for each newly mirrored release and records
  pass/fail in the DB.
- This lives with the C++ out-of-tree rebuild job proposed in
  `out-of-tree-bus-drivers.md` §7.

**Acceptance:** two consecutive releases regenerate and build with zero
manual edits. Any needed patch is carried by `regen.py`, not typed by hand.

**Total:** roughly **6–8 engineer-weeks** to milestone 2, of which **3–5
weeks** get to milestone 1. The earlier chat estimate was "3–5 weeks to first
driver"; the bigger number includes regeneration and CI, and W5's 25 missing
`BUILD.bazel` files.

---

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Closure far larger than needed (conditionals, heavy component libs) | High | W5 trim pass; carry trims as patches; measure closure with a proper GN query (`gn desc --tree` needs a full checkout, or use `git grep`-based walker with conditional handling) |
| `rules_rust` patch or Bazel-version coupling with `rules_fuchsia` | Medium | Pin Bazel to the version `sdk-samples/drivers` uses (`.bazelversion`); apply upstream's rules_rust patch |
| `fidlgen_rust_next` build pulls a big host-side crate tree | Medium | Try the prebuilt-tool route first ([verify] availability in release GCS) |
| Rust `std` imports restricted libc symbols | Medium | W6 check early; mirror in-tree config |
| Upstream renames or moves crates between releases | Medium | `regen.py` keyed on GN labels, fails loudly; CI catches it within one release |
| CIPD toolchain pin changes format or goes non-anonymous | Low | Fallback: rustup stable (§3.5) |
| License obligations for vendored code | Low | All BSD-3 (Fuchsia) plus crates.io licenses; carry upstream `LICENSE` and `METADATA` files in `vendor/` |

---

## 8. The long-term upstream fix (context for the planner)

Proper SDK support would need:
- an IDK atom type for Rust source libraries (the orphaned
  `rust_3p_library.json` schema is a starting point);
- `fidlgen_rust` and `fidlgen_rust_next` published as host tools;
- the driver crates published as partner/unstable atoms;
- a Rust driver rule in `rules_fuchsia`, with `rules_rust` bundled.

**The blockers are policy, not code:**
- Rust has no stable ABI, so atoms must be source, tied to a named compiler
  version.
- The 44+ crates.io dependencies would collide with SDK users' own versions.

That needs an RFC and SDK-owner buy-in. The overlay produces exactly the
evidence such an RFC needs: the minimal closure, a working rule, and the
per-release regeneration cost. The planner should keep the overlay's structure
close to what an upstream atom layout would look like, so it can be proposed
directly.

---

## 9. Open questions for the planner or the owner

1. **Pilot choice.** `dw-spi` is the best-understood Rust driver, but the lab
   may have no DesignWare SPI. Is "builds, loads, unit tests pass" enough for
   milestone 1, or must the pilot bind on lab hardware? If the latter, list
   Rust drivers upstream (`git grep -l fuchsia_rust_driver -- '*.gn'`) and
   match them against lab boards (VIM3, NUC11, OptiPlex).
2. **Where the overlay repo lives,** and under what name.
3. **Toolchain.** Is upstream's pinned CIPD toolchain (recommended) acceptable
   long term, or is rustup stable preferred for independence?
4. **Scope of tests.** Are unit tests in scope (the `-test-staticlib`
   pattern, plus Rust `fdf` test harnesses), or only production builds for
   milestone 1?
5. **Architectures.** Does milestone 1 need both x64 and arm64, or only the
   pilot board's?

---

## Appendix A: closure data (at `40c25c2c`)

### A.1 In-tree crates

"Lines" counts `.rs` under the crate, including inline tests. "Bazel" means
upstream already has a real `BUILD.bazel` for that crate.

| Crate path | Lines | Bazel |
|---|---:|---|
| `sdk/lib/async/rust` | 1,179 | **no** |
| `sdk/lib/async/rust/dispatcher` | 672 | **no** |
| `sdk/lib/async/rust/fidl` | 417 | **no** |
| `sdk/lib/async/rust/sys` | 648 | **no** |
| `sdk/lib/c/rust` | 251 | yes |
| `sdk/lib/driver/component/rust` | 2,898 | **no** |
| `sdk/lib/driver/metadata/rust` | 484 | **no** |
| `sdk/lib/driver/mmio/rust` | 3,324 | **no** |
| `sdk/lib/driver/platform-device/rust` | 422 | **no** |
| `sdk/lib/driver/power/rust` | 286 | **no** |
| `sdk/lib/driver/resource/rust` | 150 | **no** |
| `sdk/lib/driver/runtime/rust` | 20 | **no** |
| `sdk/lib/driver/runtime/rust/channel` | 2,506 | **no** |
| `sdk/lib/driver/runtime/rust/core` | 1,154 | **no** |
| `sdk/lib/driver/runtime/rust/env` | 1,038 | **no** |
| `sdk/lib/driver/runtime/rust/fdf_sys` | 863 | **no** |
| `sdk/lib/driver/runtime/rust/fidl` | 965 | **no** |
| `sdk/lib/fuchsia-loom` | 206 | yes |
| `sdk/rust/zx` | 15,612 | yes |
| `sdk/rust/zx-status` | 404 | yes |
| `sdk/rust/zx-status-ext` | 84 | yes |
| `sdk/rust/zx-sys` | 1,118 | yes |
| `sdk/rust/zx-types` | 3,346 | yes |
| `src/lib/buf-read-ext` | 79 | yes |
| `src/lib/detect-stall` | 447 | **no** |
| `src/lib/diagnostics/hierarchy/rust` | 4,105 | yes |
| `src/lib/diagnostics/inspect/contrib/rust` | 3,324 | yes |
| `src/lib/diagnostics/inspect/format/rust` | 3,074 | yes |
| `src/lib/diagnostics/inspect/runtime/rust` | 1,034 | **no** |
| `src/lib/diagnostics/inspect/rust` | 13,020 | yes |
| `src/lib/diagnostics/log/rust` | 3,588 | yes |
| `src/lib/diagnostics/selectors` | 3,095 | yes |
| `src/lib/directed_graph` | 870 | yes |
| `src/lib/elf_parse` | 1,203 | **no** |
| `src/lib/fdio/rust` | 3,868 | yes |
| `src/lib/fdomain/client` | 5,345 | yes |
| `src/lib/fidl/rust/fidl` | 8,234 | yes |
| `src/lib/fidl/rust_constants` | 35 | yes |
| `src/lib/fidl/rust_next/fidl_next` | 43 | yes |
| `src/lib/fidl/rust_next/fidl_next_bind` | 2,818 | yes |
| `src/lib/fidl/rust_next/fidl_next_codec` | 7,192 | yes |
| `src/lib/fidl/rust_next/fidl_next_protocol` | 3,841 | yes |
| `src/lib/fidl/rust_next/fidl_next_util` | 177 | yes |
| `src/lib/from-enum` | 115 | yes |
| `src/lib/fuchsia-async` | 15,603 | yes |
| `src/lib/fuchsia-async-macro` | 300 | yes |
| `src/lib/fuchsia-component` | 17 | yes |
| `src/lib/fuchsia-component/client` | 881 | yes |
| `src/lib/fuchsia-component/config` | 68 | **no** |
| `src/lib/fuchsia-component/directory` | 192 | yes |
| `src/lib/fuchsia-component/escrow` | 206 | **no** |
| `src/lib/fuchsia-component/runtime` | 1,775 | **no** |
| `src/lib/fuchsia-component/server` | 1,622 | **no** |
| `src/lib/fuchsia-emulated-handle` | 3,519 | yes |
| `src/lib/fuchsia-fs` | 5,495 | yes |
| `src/lib/fuchsia-runtime` | 538 | yes |
| `src/lib/fuchsia-sync` | 1,430 | yes |
| `src/lib/injectable-time` | 240 | yes |
| `src/lib/process_builder` | 2,873 | **no** |
| `src/storage/lib/vfs/rust/name` | 794 | yes |
| `src/sys/lib/bitflags-serde-legacy` | 179 | yes |
| `src/sys/lib/cm_fidl_validator` | 12,186 | yes |
| `src/sys/lib/cm_graph` | 499 | yes |
| `src/sys/lib/cm_rust` | 5,239 | yes |
| `src/sys/lib/cm_types` | 2,246 | yes |
| `src/sys/lib/moniker` | 1,231 | yes |
| `src/sys/lib/namespace` | 797 | **no** |

**Plus, missed by the walker:** `src/storage/lib/vfs/rust` (the `vfs` crate,
a `rustc_dylib` in GN).

### A.2 Direct crates.io dependencies (versions from `third_party/rust_crates/Cargo.lock`)

`anyhow` 1.0.104 · `async-trait` 0.1.92 · `base64` 0.21.7/0.22.1 ·
`bitfield` 0.19.5 · `bitflags` 1.3.2/2.13.0 · `bstr` 1.13.1 ·
`byteorder` 1.5.0 (**patched**) · `chrono` 0.4.45 · `crossbeam` 0.8.4 ·
`darling` 0.20.11/0.23.0 · `derivative` 2.2.0 · `either` 1.18.0 ·
`flyweights` 0.1.5 · `fragile` 2.0.1 · `futures` 0.3.34 ·
`futures-lite` 2.6.1 · `itertools` 0.13.0/0.14.0 · `libc` 0.2.189
(**patched**) · `log` 0.4.29 · `maplit` 1.0.2 · `memchr` 2.8.3
(**patched**) · `munge` 0.4.7 · `num-derive` 0.5.1 · `num-traits` 0.2.19 ·
`paste` 1.0.15 · `pin-project` 1.1.11 · `pin-project-lite` 0.2.17 ·
`proc-macro2` 1.0.107 · `quote` 1.0.47 · `rustc-hash` 2.1.3 ·
`schemars` 1.2.2 · `serde` 1.0.229 · `slab` 0.4.12 · `smallvec` 1.15.2 ·
`socket2` 0.6.4 · `static_assertions` 1.1.0 · `strum` 0.28.0 ·
`strum_macros` 0.28.0 · `syn` 1.0.109/2.0.119/3.0.3 ·
`thiserror` 1.0.69/2.0.20 · `tokio` 1.53.1 (**patched**) · `url` 2.5.8 ·
`winnow` 0.7.13/1.0.4 · `zerocopy` 0.8.48

Where two versions are listed, the lockfile carries both. Which version each
in-tree crate uses is set by the `third_party/rust_crates` GN aliases.

### A.3 FIDL libraries in the closure

**In the IDK (33):**
`fuchsia.component`, `fuchsia.component.decl`, `fuchsia.component.runner`,
`fuchsia.component.runtime`, `fuchsia.component.sandbox`, `fuchsia.data`,
`fuchsia.device.fs`, `fuchsia.diagnostics`, `fuchsia.diagnostics.types`,
`fuchsia.driver.framework`, `fuchsia.driver.metadata`,
`fuchsia.hardware.clock`, `fuchsia.hardware.gpio`, `fuchsia.hardware.i2c`,
`fuchsia.hardware.mailbox`, `fuchsia.hardware.pci`,
`fuchsia.hardware.platform.device`, `fuchsia.hardware.power`,
`fuchsia.hardware.powerdomain`, `fuchsia.hardware.reset`,
`fuchsia.hardware.sharedmemory`, `fuchsia.hardware.spi`,
`fuchsia.hardware.spi.businfo`, `fuchsia.hardware.spiimpl`,
`fuchsia.inspect`, `fuchsia.io`, `fuchsia.ldsvc`, `fuchsia.logger`,
`fuchsia.mem`, `fuchsia.power.broker`, `fuchsia.power.system`,
`fuchsia.process`, `fuchsia.process.lifecycle`.

**Not in the IDK (1):** `fuchsia.sys2`, via `src/sys/lib/cm_rust`.

---

## Appendix B: reproducing the evidence

```bash
# 1. Sparse, blobless clone (~300 MB with the paths below; widen as needed)
git clone --depth 1 --filter=blob:none --sparse https://fuchsia.googlesource.com/fuchsia fx
git -C fx sparse-checkout set --no-cone /sdk/ /src/devices/ /build/ /tools/fidl/ \
    /third_party/rust_crates/Cargo.toml /third_party/rust_crates/Cargo.lock /manifests/
# Note: gitiles web views of fuchsia.git return 503 through the agent proxy; git itself works.

# 2. Does a crate have an upstream Bazel build?
git -C fx cat-file -e HEAD:src/lib/fuchsia-async/BUILD.bazel && echo yes

# 3. Resolve the Rust toolchain pin anonymously
curl -sS -X POST -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"package":"fuchsia/third_party/rust/target/fuchsia","version":"git_revisions:c26ce708de5d14682647895d2f3caf38f70b5aa6,3493720eca95cf844a8d7e58fdd12e0e5644e7d0"}' \
  https://chrome-infra-packages.appspot.com/prpc/cipd.Repository/ResolveVersion

# 4. Released IDK manifest (3 GB archive; stream and extract meta/manifest.json only)
curl -sS https://storage.googleapis.com/fuchsia/development/33.20260927.4.1/sdk/linux-amd64/core.tar.gz \
  | tar -xzf - meta/manifest.json
```

**Closure walker** (run from the directory containing `fx/`; it
auto-widens the sparse checkout as it goes):

```python
# Usage: python3 closure.py //sdk/lib/driver/component/rust //src/devices/spi/drivers/dw-spi
# Walks GN deps (not test_deps) through Rust targets; prints JSON of in-tree
# crate dirs, third_party/rust_crates names, and FIDL libraries. Ignores GN
# conditionals (so over-approximates) and rustc_dylib targets (so misses vfs).
import json, os, re, subprocess, sys

ROOT = "fx"
RUST_KINDS = (r"(rustc_library|rustc_macro|fuchsia_rust_driver|rustc_staticlib|"
              r"fuchsia_cc_driver|fuchsia_driver_component|driver_bind_rules|"
              r"bind_library|group)$")
seen, added, intree, third, fidl = set(), set(), set(), set(), set()
stack = sys.argv[1:]

def ensure(path):
    if path not in added:
        added.add(path)
        if not os.path.exists(os.path.join(ROOT, path, "BUILD.gn")):
            subprocess.run(["git", "-C", ROOT, "sparse-checkout", "add", f"/{path}/"],
                           capture_output=True, check=False)

while stack:
    label = stack.pop()
    if label in seen:
        continue
    seen.add(label)
    path, _, name = label.lstrip("/").partition(":")
    name = name or os.path.basename(path)
    if path.startswith("third_party/rust_crates"):
        third.add(name); continue
    if path.startswith("sdk/fidl") or (name.endswith(("_rust", "_rust_next")) and "fidl" in path):
        fidl.add(path.split("/")[-1]); continue
    ensure(path)
    gn = os.path.join(ROOT, path, "BUILD.gn")
    if not os.path.exists(gn):
        continue
    text = open(gn, encoding="utf-8").read()
    m = re.search(r'(\w+)\(\s*"%s"\s*\)\s*\{' % re.escape(name), text)
    if not m and name == os.path.basename(path):
        m = re.search(r'(rustc_library|rustc_macro)\(\s*"[^"]*"\s*\)\s*\{', text)
    if not m or not re.match(RUST_KINDS, m.group(1)):
        continue
    i, depth = m.end(), 1
    while depth and i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0); i += 1
    block = re.sub(r"test_deps\s*=\s*\[[^\]]*\]", "", text[m.end():i])
    intree.add(path)
    for dm in re.finditer(r"(?<!test_)(?:deps|public_deps|non_rust_deps)\s*\+?=\s*\[([^\]]*)\]", block):
        for dep in re.findall(r'"([^"]+)"', dm.group(1)):
            dep = f"//{path}{dep}" if dep.startswith(":") else dep
            if dep.startswith("//"):
                stack.append(dep)

print(json.dumps({"intree": sorted(intree), "third": sorted(third), "fidl": sorted(fidl)}, indent=1))
```
