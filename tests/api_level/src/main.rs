// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! Uses all three rustc_* wrappers: this rustc_binary, the head_branch rustc_library
//! (which fails to compile unless the HEAD branch is taken) and a rustc_proc_macro.

fn main() {
    println!(
        "target branch: {}; exec (proc macro) branch: {}",
        head_branch::BRANCH,
        exec_branch::exec_branch!()
    );
}
