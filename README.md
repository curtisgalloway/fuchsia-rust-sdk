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
toolchain, each pinned by SHA-256 in the lock) and uses about 20 GB of disk: 16 GB in
Bazel's output base (13 GB of it the extracted IDK) and 4 GB in its repository cache
(measured in [M2](docs/evidence/M2.md)).
