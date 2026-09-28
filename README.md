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
