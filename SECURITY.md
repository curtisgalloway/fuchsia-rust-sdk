<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue. On this repository's
GitHub page, open the **Security** tab and choose **Report a vulnerability** (GitHub's
private vulnerability reporting). Include what is affected (a script, a Bazel rule, a
pinned input in `overlay.lock.json`), how to reproduce it, and its impact as you see it.

## Scope

This repository builds Fuchsia drivers from pinned upstream inputs; it is not an official
Google or Fuchsia project. A vulnerability in Fuchsia itself, in its SDK, or in code
vendored here from `fuchsia.git` (`vendor/`, `third_party/crates/`) belongs upstream:
follow the Fuchsia project's own security reporting process. Report here anything this
repository adds: its scripts, rules, overlays and patches, and how it fetches and checks
its pinned inputs.
