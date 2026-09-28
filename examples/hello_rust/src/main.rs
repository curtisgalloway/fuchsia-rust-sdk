// SPDX-FileCopyrightText: 2026 Curtis Galloway
// SPDX-License-Identifier: Apache-2.0

//! A Rust binary for Fuchsia that calls into `libfdio.so` (design R2: the toolchain
//! links against the IDK's prebuilt libraries and sysroot).

// From the IDK's pkg/fdio (lib/fdio/fd.h):
// zx_status_t fdio_fd_clone(int fd, zx_handle_t* out_handle);
unsafe extern "C" {
    fn fdio_fd_clone(fd: i32, out_handle: *mut u32) -> i32;
}

fn main() {
    let mut handle: u32 = 0;
    // SAFETY: `handle` is a valid place for fdio to write one handle value.
    let status = unsafe { fdio_fd_clone(1, &mut handle) };
    println!("Hello from Rust on Fuchsia; fdio_fd_clone(stdout) returned {status}");
}
