// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! A minimal proc macro: `greeting!()` expands to a string literal. Proc macros run on
//! the build host, so this needs the host toolchain's std.

use proc_macro::TokenStream;

#[proc_macro]
pub fn greeting(_input: TokenStream) -> TokenStream {
    "\"hello from a proc macro\"".parse().unwrap()
}
