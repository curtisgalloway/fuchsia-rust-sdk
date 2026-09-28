// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! Every `rust`-flavor binding crate of pilot 1's FIDL libraries, by the crate names the
//! vendored crates use (upstream's GN naming, build/rust/fidl_rust.gni: `fidl_<lib>`,
//! `fidl_<lib>_common` and `flex_<lib>`, with `.` in the library name as `_`). The names
//! are written out rather than computed, so this compiles only if the rule names each
//! crate as upstream does (milestone M8). fuchsia.power.broker is left out: upstream
//! restricts its visibility (experimental), so this package cannot depend on it; the
//! fuchsia.driver.framework crates, which use it, show its names.

pub use fidl_fuchsia_component;
pub use fidl_fuchsia_component_common;
pub use flex_fuchsia_component;
pub use fidl_fuchsia_component_decl;
pub use fidl_fuchsia_component_decl_common;
pub use flex_fuchsia_component_decl;
pub use fidl_fuchsia_component_resolution;
pub use fidl_fuchsia_component_resolution_common;
pub use flex_fuchsia_component_resolution;
pub use fidl_fuchsia_component_runner;
pub use fidl_fuchsia_component_runner_common;
pub use flex_fuchsia_component_runner;
pub use fidl_fuchsia_component_runtime;
pub use fidl_fuchsia_component_runtime_common;
pub use flex_fuchsia_component_runtime;
pub use fidl_fuchsia_component_sandbox;
pub use fidl_fuchsia_component_sandbox_common;
pub use flex_fuchsia_component_sandbox;
pub use fidl_fuchsia_data;
pub use fidl_fuchsia_data_common;
pub use flex_fuchsia_data;
pub use fidl_fuchsia_device_fs;
pub use fidl_fuchsia_device_fs_common;
pub use flex_fuchsia_device_fs;
pub use fidl_fuchsia_diagnostics;
pub use fidl_fuchsia_diagnostics_common;
pub use flex_fuchsia_diagnostics;
pub use fidl_fuchsia_diagnostics_types;
pub use fidl_fuchsia_diagnostics_types_common;
pub use flex_fuchsia_diagnostics_types;
pub use fidl_fuchsia_driver_framework;
pub use fidl_fuchsia_driver_framework_common;
pub use flex_fuchsia_driver_framework;
pub use fidl_fuchsia_inspect;
pub use fidl_fuchsia_inspect_common;
pub use flex_fuchsia_inspect;
pub use fidl_fuchsia_io;
pub use fidl_fuchsia_io_common;
pub use flex_fuchsia_io;
pub use fidl_fuchsia_ldsvc;
pub use fidl_fuchsia_ldsvc_common;
pub use flex_fuchsia_ldsvc;
pub use fidl_fuchsia_logger;
pub use fidl_fuchsia_logger_common;
pub use flex_fuchsia_logger;
pub use fidl_fuchsia_mem;
pub use fidl_fuchsia_mem_common;
pub use flex_fuchsia_mem;
pub use fidl_fuchsia_process;
pub use fidl_fuchsia_process_common;
pub use flex_fuchsia_process;
pub use fidl_fuchsia_process_lifecycle;
pub use fidl_fuchsia_process_lifecycle_common;
pub use flex_fuchsia_process_lifecycle;
pub use fidl_fuchsia_sys2;
pub use fidl_fuchsia_sys2_common;
pub use flex_fuchsia_sys2;
pub use fidl_fuchsia_unknown;
pub use fidl_fuchsia_unknown_common;
pub use flex_fuchsia_unknown;
pub use fidl_fuchsia_url;
pub use fidl_fuchsia_url_common;
pub use flex_fuchsia_url;
pub use fidl_fuchsia_version;
pub use fidl_fuchsia_version_common;
pub use flex_fuchsia_version;
