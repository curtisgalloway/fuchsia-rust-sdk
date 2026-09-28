// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! Build assertion for design R3: a Fuchsia build targeting `HEAD` compiles the `HEAD`
//! branch. Each `compile_error!` below fails the build if the API-level cfgs the
//! toolchain passes put the target anywhere else.

#[cfg(not(fuchsia_api_level_at_least = "HEAD"))]
compile_error!("fuchsia_api_level_at_least=\"HEAD\" is not set: the HEAD branch was not taken");

#[cfg(fuchsia_api_level_less_than = "HEAD")]
compile_error!("fuchsia_api_level_less_than=\"HEAD\" is set: the target is below HEAD");

// NEXT is the level below HEAD (RFC-0246), so a HEAD build is at least NEXT.
#[cfg(not(fuchsia_api_level_at_least = "NEXT"))]
compile_error!("fuchsia_api_level_at_least=\"NEXT\" is not set for a HEAD build");

// PLATFORM is above HEAD: its cfg must be the less_than one, never at_least.
#[cfg(not(fuchsia_api_level_less_than = "PLATFORM"))]
compile_error!("fuchsia_api_level_less_than=\"PLATFORM\" is not set for a HEAD build");

#[cfg(fuchsia_api_level_at_least = "PLATFORM")]
compile_error!("fuchsia_api_level_at_least=\"PLATFORM\" is set: the PLATFORM branch was taken");

/// The API-level branch this crate was compiled on.
#[cfg(fuchsia_api_level_at_least = "HEAD")]
pub const BRANCH: &str = "HEAD";

/// The API-level branch this crate was compiled on.
#[cfg(not(fuchsia_api_level_at_least = "HEAD"))]
pub const BRANCH: &str = "not HEAD";
