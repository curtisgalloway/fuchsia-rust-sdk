<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# fuchsia-rust-sdk

An overlay for building Fuchsia DFv2 drivers written in Rust outside `fuchsia.git`,
against a released Fuchsia SDK, to run on a device whose OS comes from the same
release. Every per-release input is pinned in [`overlay.lock.json`](overlay.lock.json),
which `uv run scripts/resolve_pins.py <sdk-version>` produces from anonymous upstream
lookups. See the [design](docs/design.md) and the
[implementation plan](docs/implementation-plan.md).

To write a driver, start with the [driver guide](docs/driver-guide.md): copy pilot 1
(`drivers/simple_rust`), write its bind rule, build it for both targets and bind it on
the emulator.

## Build

Bazel runs through `scripts/bazel`, which downloads the release in `.bazelversion` once
and checks it against `scripts/bazel.sha256`. The build host is linux-x64.

```bash
scripts/bazel build --config=fuchsia_x64 //examples/hello_rust    # or --config=fuchsia_arm64
scripts/bazel build //examples/hello_host                         # host toolchain + a proc macro
```

A cold build downloads about 4 GB (mostly the release's IDK, then clang and the Rust
toolchain, each pinned by SHA-256 in the lock).

The two FIDL binding generators are host tools. `fidlgen_rust` is built from vendored
source with `rules_go` and the release's Go SDK (the lock's `go` field);
`fidlgen_rust_next` is the release's prebuilt binary (the lock's `fidlgen_rust_next`
field, from the public debug-symbol store):

```bash
scripts/bazel run //tools/fidlgen_rust -- --help
scripts/bazel run //tools/fidlgen_rust_next -- --help
scripts/bazel test //tests/fidlgen/...    # both reproduce upstream's goldens; fuchsia.mem
```

### Disk and environment profiles

Disk limits belong to the environment (design C6). The default profile, `hosted`, fits
the Anthropic-hosted container (about 30 GB of disk; budget 25 GiB in total, 15 GiB for
Bazel's output base plus repository cache; 12 until M9b). Under it:

- the IDK is extracted without what the build never uses (other API levels' prebuilts,
  riscv64 libraries, host tools for arm64 hosts), after its SHA-256 check: 3.6 GB
  instead of 13 GB;
- `scripts/bazel` removes the 3 GB IDK tarball from Bazel's repository cache after
  each command that can fetch (so a refetch downloads it again).

A cold build then leaves about 7.7 GiB in Bazel's caches, with a peak of about
10.8 GiB while the IDK is fetched (measured in [M2a](docs/evidence/M2a.md)). An
environment with more disk declares `large-disk`, which skips both, with
`OVERLAY_PROFILE=large-disk` or a file `~/.config/fuchsia-rust-sdk/profile` (under
`$XDG_CONFIG_HOME` if set) holding the name; changing it refetches the IDK. Fetching
the IDK needs `python3` (3.11 or later) on `PATH`.

```bash
uv run scripts/overlay_profile.py        # the active profile and where it came from
uv run scripts/disk_report.py            # disk per bucket against the profile's budget
uv run scripts/check_sdk_files.py        # every SDK file the configs can reach exists
```

## Emulator

`scripts/emu` boots the lock's release of `core.x64` in QEMU and runs packages on it
(ported from [`fuchsia-cloud-dev`](https://github.com/curtisgalloway/fuchsia-cloud-dev)'s
`dev`). Nothing in it names a release: ffx and QEMU come from the lock's IDK
(`tools/x64/ffx`, `tools/x64/qemu_internal`; the release pins that QEMU in fuchsia.git
`manifests/prebuilts`), and the `core.x64` product bundle is the lock's
`product_bundle`: its transfer manifest and a digest over every file's SHA-256, which
`scripts/emu` checks after each download and in `setup` (a mismatch is refused).

```bash
scripts/emu setup                          # IDK (via Bazel), core.x64 bundle, package repo; idempotent
scripts/emu verify                         # the cached bundle matches the lock's digest
scripts/emu start                          # boot: about 1 min under TCG
scripts/emu check                          # the target's version must equal the lock's sdk_version
scripts/emu run //examples/hello_rust:pkg  # build, publish, ffx component run
scripts/emu log hello_rust                 # → "Hello from Rust on Fuchsia; …"
scripts/emu stop
scripts/emu env                            # what was detected, and where state lives
```

Components started with `scripts/emu run` must take `fuchsia.logger.LogSink`
`from: "parent/diagnostics"` (see `examples/hello_rust/meta/hello_rust.cml`). Use
`scripts/emu ffx …` rather than a bare `ffx`: it sets the short isolate directory
QEMU's socket-path limit needs.

### Host contract

The harness runs on any linux-x64 host or container that meets this contract; it
detects the rest.

| Need | Detail |
|---|---|
| OS, tools | linux-x64 (C5); `python3` ≥ 3.11 and `curl` (as for the build); an `ssh` client. When it is missing and setup runs as root with `apt-get`, setup installs `openssh-client` from the host's configured apt mirrors (not probed in advance; apt's own error is shown if that fails); otherwise setup stops and says so |
| Network, first setup | `storage.googleapis.com` (IDK, product bundle); while the IDK is not yet fetched also `chrome-infra-packages.appspot.com`, `github.com`, `release-assets.githubusercontent.com`, `bcr.bazel.build`. Setup probes the hosts it needs first and exits non-zero naming any it cannot reach. After setup, booting and running packages contact no outside host |
| Disk | the active profile's budget (`uv run scripts/disk_report.py`); the emulator adds about 0.5 GiB (bundle 0.36 GiB, running instance), and its disk image can grow toward 10 GiB with guest writes |
| Acceleration | optional: KVM when `/dev/kvm` opens read-write, otherwise TCG (no flag needed) |
| Loopback | IPv4; IPv6 used when `::1` can be bound, otherwise the package server binds `127.0.0.1:8083` |

| Setting | Default | Effect |
|---|---|---|
| `OVERLAY_STATE_DIR` | `$XDG_STATE_HOME/fuchsia-rust-sdk` or `~/.local/state/fuchsia-rust-sdk` | parent of the emulator directory |
| `OVERLAY_EMULATOR_DIR` | `<state>/emulator` | product bundles, package repository, ffx isolate dir, instance files (the disk report's `emulator` bucket) |
| `OVERLAY_FFX_ISOLATE_DIR` | `<emulator>/ffx` | must be short: QEMU's sockets under it must stay below 108 bytes (setup checks) |
| `OVERLAY_EMU_ACCEL` | the profile's `emulator_accel` (`auto`) | `auto`, `kvm` (fail if unusable) or `tcg` |

**In a Claude Code cloud session** nothing starts automatically; ask for
`scripts/emu setup` (about 1 minute once the IDK is fetched). A SessionStart hook is
optional and should stay a thin wrapper that runs `scripts/emu setup` (guarded by
`CLAUDE_CODE_REMOTE=true`, output to a log file outside the checkout); the harness does
not depend on one. Other commands wait while a setup holds its lock.
