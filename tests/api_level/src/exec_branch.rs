// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! A proc macro (built for the exec platform) that expands to the API-level branch it
//! was itself compiled on. It exercises rustc_proc_macro; what it reports for a Fuchsia
//! build is recorded in docs/evidence/M4.md, not asserted.

use proc_macro::TokenStream;

/// Expands to a string literal: "PLATFORM", "HEAD" or "other".
#[proc_macro]
pub fn exec_branch(_input: TokenStream) -> TokenStream {
    let branch = if cfg!(fuchsia_api_level_at_least = "PLATFORM") {
        "PLATFORM"
    } else if cfg!(fuchsia_api_level_at_least = "HEAD") {
        "HEAD"
    } else {
        "other"
    };
    format!("{branch:?}").parse().unwrap()
}
