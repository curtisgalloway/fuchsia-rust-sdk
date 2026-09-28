// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! Every `rust_next`-flavor binding crate of pilot 1's FIDL libraries, by the crate names
//! the vendored crates use (upstream's GN naming, build/rust/fidl_rust_next.gni:
//! `fidl_next_<lib>` and `fidl_next_common_<lib>`, with `.` in the library name as `_`).
//! The names are written out rather than computed, so this compiles only if the rule names
//! each crate as upstream does (milestone M8b; fuchsia.driver.framework's, with the driver
//! transport, M9a). fuchsia.power.broker's are left out: upstream restricts their
//! visibility.

pub use fidl_next_fuchsia_component;
pub use fidl_next_common_fuchsia_component;
pub use fidl_next_fuchsia_component_decl;
pub use fidl_next_common_fuchsia_component_decl;
pub use fidl_next_fuchsia_component_resolution;
pub use fidl_next_common_fuchsia_component_resolution;
pub use fidl_next_fuchsia_component_runner;
pub use fidl_next_common_fuchsia_component_runner;
pub use fidl_next_fuchsia_component_sandbox;
pub use fidl_next_common_fuchsia_component_sandbox;
pub use fidl_next_fuchsia_data;
pub use fidl_next_common_fuchsia_data;
pub use fidl_next_fuchsia_device_fs;
pub use fidl_next_common_fuchsia_device_fs;
pub use fidl_next_fuchsia_diagnostics;
pub use fidl_next_common_fuchsia_diagnostics;
pub use fidl_next_fuchsia_diagnostics_types;
pub use fidl_next_common_fuchsia_diagnostics_types;
pub use fidl_next_fuchsia_driver_framework;
pub use fidl_next_common_fuchsia_driver_framework;
pub use fidl_next_fuchsia_io;
pub use fidl_next_common_fuchsia_io;
pub use fidl_next_fuchsia_ldsvc;
pub use fidl_next_common_fuchsia_ldsvc;
pub use fidl_next_fuchsia_logger;
pub use fidl_next_common_fuchsia_logger;
pub use fidl_next_fuchsia_mem;
pub use fidl_next_common_fuchsia_mem;
pub use fidl_next_fuchsia_process;
pub use fidl_next_common_fuchsia_process;
pub use fidl_next_fuchsia_unknown;
pub use fidl_next_common_fuchsia_unknown;
pub use fidl_next_fuchsia_url;
pub use fidl_next_common_fuchsia_url;
pub use fidl_next_fuchsia_version;
pub use fidl_next_common_fuchsia_version;
