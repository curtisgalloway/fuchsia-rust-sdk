<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# Contributing

Issues are welcome: bugs, unclear documentation, a driver the overlay cannot build.

## Pull requests

A pull request must pass:

```bash
uv run pytest
uv run reuse lint
scripts/bazel test --config=fuchsia_x64 //...
scripts/bazel test --config=fuchsia_arm64 //...
```

The build host is linux-x64; [README.md](README.md) lists what the build and the
emulator need.

- **License headers.** Every new file carries an SPDX header for Apache-2.0, as the
  existing files do. A file that cannot carry a comment (JSON, for example) gets an entry
  in [`REUSE.toml`](REUSE.toml).
- **No hand edits in `vendor/` or `third_party/crates/`.** Both are generated from
  `fuchsia.git` at the lock's revision by `scripts/regen.py`. Change them through
  `regen.py`'s inputs, a file under `overlays/`, or a patch under `patches/`, then run
  `uv run scripts/regen.py vendor`; `uv run scripts/regen.py --check` reports drift.

To write a new driver, follow the [driver guide](docs/driver-guide.md).
