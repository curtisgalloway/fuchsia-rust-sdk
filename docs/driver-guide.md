<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# Writing a Rust driver with the overlay

This guide makes a new DFv2 driver by copying pilot 1 (`drivers/simple_rust`), then builds
it for both Fuchsia targets, loads it on the emulator and checks that it binds. Every step
was followed literally in G1 (a copy named `g1_guide_check`). The facts behind it are in
the [M10](evidence/M10.md), [I3](evidence/I3.md) and [M11](evidence/M11.md) evidence.

The examples call the new driver `my_driver`. Use a lowercase name with underscores: it
becomes the Bazel package, the `.so`, the package name and the component name.

## 1. Copy the pilot

From the repository root:

```bash
cp -r drivers/simple_rust drivers/my_driver
cd drivers/my_driver
mv meta/simple_rust.bind meta/my_driver.bind
mv meta/simple_rust_bind_test.json meta/my_driver_bind_test.json
mv meta/simple_rust_driver.cml meta/my_driver.cml
```

## 2. Rename inside the files

Every occurrence of the old names changes; nothing else needs to.

```bash
sed -i -e 's/simple_rust_bind_test\.json/my_driver_bind_test.json/' \
       -e 's/simple_rust\.bind/my_driver.bind/' \
       -e 's/simple_rust_driver\.cml/my_driver.cml/' \
       -e 's/simple_rust_driver/my_driver/g' BUILD.bazel
sed -i 's/simple_rust_driver\.so/my_driver.so/' meta/my_driver.cml
sed -i 's/^composite simple_rust;/composite my_driver;/' meta/my_driver.bind
sed -i 's/const NAME: &str = "simple_rust_driver";/const NAME: \&str = "my_driver";/' src/lib.rs
grep -rn simple_rust .     # expect only comments (BUILD.bazel's header, the .bind's)
```

What each name is:

| Where | Name | Must match |
|---|---|---|
| `BUILD.bazel` `fuchsia_rust_driver(output_name = …)` | `my_driver` → `driver/my_driver.so` | the `.cml`'s `program.binary`, `elf_test`'s `driver` |
| `BUILD.bazel` `fuchsia_package(package_name = …)` | `my_driver` | the package URL `fuchsia-pkg://devhost/my_driver#meta/my_driver.cm` |
| `BUILD.bazel` `fuchsia_driver_component(manifest = …)` | `meta/my_driver.cml` → `meta/my_driver.cm` | `manifest_test`'s `component` |
| `BUILD.bazel` `fuchsia_driver_bind_bytecode(output = …)` | `rust.bindbc` (unchanged) | the `.cml`'s `program.bind` (`meta/bind/rust.bindbc`) |
| `.bind` `composite …;` | `my_driver` | the composite name the driver index reports |
| `src/lib.rs` `Driver::NAME` | `my_driver` | the tag its log lines carry (`scripts/emu log my_driver`) |

Keep the Bazel target names (`driver`, `bind`, `bind_test`, `component`, `pkg`, `elf_test`,
`manifest_test`); the commands below use them. Rename the Rust struct if you like.

## 3. The BUILD targets

`drivers/my_driver/BUILD.bazel` now declares:

- **`driver`** — `fuchsia_rust_driver` (`//rules:fuchsia_rust_driver.bzl`): a `cdylib`
  linked with `rules_fuchsia`'s `driver.ld` so only `__fuchsia_driver_registration__` is
  exported, soname `<output_name>.so`, against the IDK's driver runtime; the
  restricted-symbols check runs as a build action. `deps` name vendored crates
  (`//vendor/fuchsia/...`), crates.io crates (`@rust_crates//vendor:<crate>`) and bind
  library crates (`//drivers/bind:<library>_rust`). Unused crate deps are allowed, as GN
  allows them for Rust drivers.
- **`bind`** — `fuchsia_driver_bind_bytecode` from `rules_fuchsia`: compiles the `.bind`
  with the IDK's `bindc`. Its `deps` are the bind libraries the rule's `using` lines name,
  from the IDK: `@fuchsia_sdk//bind/<library>`.
- **`bind_test`** — `fuchsia_driver_bind_test` (`//rules:bind_test.bzl`, not
  `rules_fuchsia`'s bind test, which fails under Bzlmod): `bindc test --lint` with the
  JSON spec.
- **`component`**, **`pkg`** — `fuchsia_driver_component` and `fuchsia_package`. `pkg` is
  tagged `manual`, so `//...` skips it: name it explicitly.
- **`elf_test`**, **`manifest_test`** — the R7 checks on the packaged driver (exports,
  soname, `DT_NEEDED` within `allowed_needed`, every packaged library's needs resolved,
  CPU) and the manifest's `syslog`/`inspect` shards. Fuchsia configs only.

A bind library the driver uses in its source (for a child node's properties, as the
pilot's `fuchsia.test`) needs a Rust crate: add a `fuchsia_bind_rust_library` to
`drivers/bind/BUILD.bazel` as `fuchsia.test_rust` is declared there.

## 4. Write the bind rule and its test

On the emulator (section 6 starts it), find the node to bind and read its properties:

```bash
scripts/emu ffx driver list-devices -v            # every node: moniker, driver, properties
scripts/emu ffx driver list-devices -v PCI0.bus.00_06_0
scripts/emu ffx driver composite list             # the composite node specs
scripts/emu ffx driver composite show 00_06_0     # a spec's parents and their bind properties
```

A PCI device on `core.x64` is published as a **composite node spec** with two parents,
the PCI device (`pci`) and its ACPI node (`acpi`); its unbound PCI node shows `Driver :
None` and a spec named after it. A driver for it must be a composite rule: a plain rule
on the PCI node registers but never binds. The copied rule binds QEMU's `edu` device
(VID 0x1234, DID 0x11e8), which `scripts/emu start` adds:

```
composite my_driver;
using fuchsia.acpi;
using fuchsia.pci;
primary parent "pci" { fuchsia.BIND_PCI_VID == 0x1234; fuchsia.BIND_PCI_DID == 0x11e8; }
optional parent "acpi" { fuchsia.BIND_PROTOCOL == fuchsia.acpi.BIND_PROTOCOL.DEVICE; }
```

For another device, change the values to that device's properties from `composite show`.
The test spec (`meta/my_driver_bind_test.json`) has one entry per parent; each test gives
a `device` (the properties as `composite show` prints them: string values in escaped
quotes, `"\"fuchsia.hardware.pci.Service\""`; enum values by name,
`"fuchsia.acpi.BIND_PROTOCOL.DEVICE"`; numbers in hex) and `"expected": "match"` or
`"abort"`. Keep at least one `abort` case per parent (another device's properties), so the
test shows the rule rejects what it should.

## 5. Build and test for both targets

```bash
scripts/bazel build --config=fuchsia_x64   //drivers/my_driver:pkg
scripts/bazel build --config=fuchsia_arm64 //drivers/my_driver:pkg
scripts/bazel test  --config=fuchsia_x64   //drivers/my_driver/...
scripts/bazel test  --config=fuchsia_arm64 //drivers/my_driver/...
```

Expect `bind_test`, `elf_test` and `manifest_test` to pass for each. A host `scripts/bazel
test` skips all three (they are Fuchsia-only). The package is
`bazel-bin/drivers/my_driver/my_driver.far`.

If you add a dependency, `elf_test` may report a new `DT_NEEDED` library: add it to
`allowed_needed` only after checking an in-tree driver in the release's product bundle
needs it too (M10's method).

## 6. Load it on the emulator

The emulator is `core.x64` only, so only the x64 build can be loaded here.

```bash
scripts/emu setup                          # first time: IDK, core.x64 bundle, package repository
scripts/emu start                          # about 1 minute under TCG
scripts/emu check                          # the target runs the lock's sdk_version
scripts/emu driver //drivers/my_driver:pkg # build (x64), publish to `devhost`, ffx driver register
```

`scripts/emu driver` prints `Successfully bound:` and the parent nodes when the driver
index matched the rule to a spec.

**One driver per node.** Registrations are ephemeral, and the first driver registered for
a spec keeps it until the target reboots. If another driver (the pilot, or an older copy)
is already bound to the node, the new one registers but does not bind. Start from a fresh
boot: `scripts/emu stop`, `scripts/emu start`, then register only the driver you want.

**Reloading after a rebuild.** The driver index keeps the first registration of a URL
until reboot, so when the URL is already registered, `scripts/emu driver` reboots the target
first (about 2 minutes under TCG), then registers again; this also drops every other
ephemeral registration. `ffx target wait` may print an ssh retry message and an empty
backtrace on stderr during the reboot; it is harmless.

## 7. Check the bind

```bash
scripts/emu ffx driver list --loaded                  # lists fuchsia-pkg://devhost/my_driver#meta/my_driver.cm
scripts/emu ffx driver composite show 00_06_0         # Driver: …/my_driver#…; Node: PCI0.bus.00_06_0.00_06_0
scripts/emu ffx driver list-devices -v PCI0.bus.00_06_0.00_06_0   # Driver: …/my_driver#…
scripts/emu log my_driver                              # the driver's own log lines
```

For the copied source, the log shows `SimpleRustDriver::start() was invoked.`, and
`list-devices -v` shows its child node `simple_child` under the composite node. The edu
PCI node itself stays `owned by composite(s)`.

**Logging.** The driver logs with the `log` crate through `fdf_component`; the `.cml`
must include `syslog/client.shard.cml` (and `inspect/client.shard.cml`), which gives it
`fuchsia.logger.LogSink`, and `manifest_test` checks both. Unlike components run with
`scripts/emu run`, a driver does not route `LogSink` from `parent/diagnostics` itself.

## Limits at this release

- **Bind targets on the emulator:** `edu` is the one device on `core.x64` that no shipped
  driver claims. Other QEMU devices would need a `-device` argument in `scripts/emu` and a
  node no in-tree driver binds first.
- **arm64** builds and passes its tests, but loads only on hardware (the VIM3, M13).
- **FIDL:** bindings exist only for the libraries in `vendor/crates.txt` (pilot 1's
  closure). Another IDK library is a line `sdk/fidl/<library> idk` there. A library
  outside the IDK needs the non-IDK route: `sdk/fidl/<library> upstream` (as
  `fuchsia.sys2`), so `regen.py` copies its `.fidl` files from fuchsia.git at the lock's
  revision; such an interface is not a published contract. Then `uv run scripts/regen.py`
  (see its `--help`) regenerates `vendor/`.
- **Crates:** only crates the overlay vendors. A new in-tree crate goes through
  `regen.py` (`vendor/crates.txt`, `overlays/`, `patches/`; never hand edits); the
  crates.io roots in `vendor/crates_io.txt` are pilot 1's (pytest keeps them equal to
  `docs/closure/pilot1.json`), so a new crates.io crate needs the closure updated too
  (M14 automates this). `fidl` is visible to `//drivers`; other restricted in-tree
  targets (e.g. `rust_next` bindings) need a visibility patch or an allowlist entry.
- **Unit tests** (`with_unit_tests`, `test_deps`) are accepted and ignored until M16.
- **Licensing:** a copied `.cml` keeps upstream's header and the JSON has none: before
  committing a new driver, add its files to `REUSE.toml` (as pilot 1's are) so `uv run
  reuse lint` passes.
