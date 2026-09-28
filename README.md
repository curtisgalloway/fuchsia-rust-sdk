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

## Build

Bazel runs through `scripts/bazel`, which downloads the release in `.bazelversion` once
and checks it against `scripts/bazel.sha256`. The build host is linux-x64.

```bash
scripts/bazel build --config=fuchsia_x64 //examples/hello_rust    # or --config=fuchsia_arm64
scripts/bazel build //examples/hello_host                         # host toolchain + a proc macro
```

A cold build downloads about 4 GB (mostly the release's IDK, then clang and the Rust
toolchain, each pinned by SHA-256 in the lock).

### Disk and environment profiles

Disk limits belong to the environment (design C6). The default profile, `hosted`, fits
the Anthropic-hosted container (about 30 GB of disk; budget 25 GiB in total, 12 GiB for
Bazel's output base plus repository cache). Under it:

- the IDK is extracted without what the build never uses (other API levels' prebuilts,
  riscv64 libraries, host tools for arm64 hosts), after its SHA-256 check: 3.6 GB
  instead of 13 GB;
- `scripts/bazel` removes the 3 GB IDK tarball from Bazel's repository cache after
  each command that can fetch (so a refetch downloads it again).

A cold build then uses about 7.7 GiB (measured in [M2a](docs/evidence/M2a.md)). An
environment with more disk declares `large-disk`, which skips both, with
`OVERLAY_PROFILE=large-disk` or a file `~/.config/fuchsia-rust-sdk/profile` (under
`$XDG_CONFIG_HOME` if set) holding the name; changing it refetches the IDK. Fetching
the IDK needs `python3` (3.11 or later) on `PATH`.

```bash
uv run scripts/overlay_profile.py        # the active profile and where it came from
uv run scripts/disk_report.py            # disk per bucket against the profile's budget
uv run scripts/check_sdk_files.py        # every SDK file the configs can reach exists
```
