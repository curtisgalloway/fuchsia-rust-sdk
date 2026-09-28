// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! Violates `unused_must_use`, which upstream's lint config denies (rules/lints) and the
//! toolchains' -Dwarnings would deny anyway. It builds only with `vendored = True`
//! (--cap-lints=allow); the first-party build of the same file must fail.

fn fallible() -> Result<(), ()> {
    Ok(())
}

/// Drops a `Result` unused.
pub fn ignores_a_result() {
    fallible();
}
