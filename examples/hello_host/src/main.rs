// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! A host binary built with the release's pinned host toolchain.

fn main() {
    println!("{}", greeting::greeting!());
}
