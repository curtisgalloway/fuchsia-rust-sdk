// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! Fuchsia code is compiled at the configured API level (HEAD) and its FIDL bindings must
//! be generated at the same level (milestone M8). `fuchsia.io`'s `NodeInfoDeprecated` is
//! `@available(removed=32)`: present in bindings made at PLATFORM (which includes levels
//! 27 to 31), absent at HEAD. `src/lib/fuchsia-fs` (`src/node.rs`) guards its use with
//! the cfg below, so bindings at the wrong level break real crates.

// The cfgs say HEAD; this fails to compile if they said PLATFORM or a level below 32.
#[cfg(any(fuchsia_api_level_at_least = "PLATFORM", not(fuchsia_api_level_at_least = "32")))]
compile_error!("Fuchsia code is expected at HEAD");

mod absent {
    /// Stands in for the binding's type, which must not exist at HEAD.
    pub struct NodeInfoDeprecated;
}

// Two glob imports: if the bindings define NodeInfoDeprecated (made at PLATFORM), the name
// below is ambiguous (error E0659) and this crate does not compile.
use absent::*;
use fidl_fuchsia_io::*;

/// Resolves to `absent::NodeInfoDeprecated` only when the bindings lack the type.
pub fn node_info() -> NodeInfoDeprecated {
    NodeInfoDeprecated
}

/// Uses the bindings' glob import (a type present at every level).
pub fn directory() -> DirectoryMarker {
    DirectoryMarker
}
