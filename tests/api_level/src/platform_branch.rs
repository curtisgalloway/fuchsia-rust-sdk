// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! Host builds set no Fuchsia API level, so the toolchains pass the `PLATFORM` cfgs:
//! upstream's host code builds at its flag's default, `PLATFORM`, too
//! (rules/rustc_api_level.bzl). Each `compile_error!` fails the build otherwise.

#[cfg(not(fuchsia_api_level_at_least = "PLATFORM"))]
compile_error!("fuchsia_api_level_at_least=\"PLATFORM\" is not set on a host build");

#[cfg(fuchsia_api_level_less_than = "PLATFORM")]
compile_error!("fuchsia_api_level_less_than=\"PLATFORM\" is set on a host build");

#[cfg(not(fuchsia_api_level_at_least = "HEAD"))]
compile_error!("fuchsia_api_level_at_least=\"HEAD\" is not set on a host build");

/// The API-level branch this crate was compiled on.
#[cfg(fuchsia_api_level_at_least = "PLATFORM")]
pub const BRANCH: &str = "PLATFORM";

/// The API-level branch this crate was compiled on.
#[cfg(not(fuchsia_api_level_at_least = "PLATFORM"))]
pub const BRANCH: &str = "not PLATFORM";

#[cfg(test)]
mod tests {
    #[test]
    fn host_takes_the_platform_branch() {
        assert_eq!(super::BRANCH, "PLATFORM");
    }
}
