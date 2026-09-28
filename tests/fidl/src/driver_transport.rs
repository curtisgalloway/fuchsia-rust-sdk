// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! The FIDL driver transport is on for pilot 1's driver library (milestone M9a), as GN has
//! it: fuchsia.driver.framework sets `contains_drivers` and `enable_rust_drivers`, so its
//! `rust` crates get feature `driver` with `fidl_driver` and `fdf`, and its `rust_next`
//! crates get feature `driver` with `fdf_fidl`. Each item below exists or type-checks only
//! with the feature on, so this crate compiles only if the transport is on.

use fidl_next::HasTransport;

/// `rust` flavor: the `Driver` protocol's driver-transport marker is generated under
/// `#[cfg(feature = "driver")]`.
pub use fidl_fuchsia_driver_framework::DriverMarker;

/// `rust_next` flavor: `Driver`'s transport is the driver runtime's channel (the
/// `HasTransport` impl is generated under `#[cfg(feature = "driver")]`).
pub fn driver_protocol_transport(
    transport: <fidl_next_fuchsia_driver_framework::Driver as HasTransport>::Transport,
) -> fdf_fidl::DriverChannel {
    transport
}
