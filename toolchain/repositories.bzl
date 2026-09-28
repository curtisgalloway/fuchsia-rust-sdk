# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0

"""Repositories fetched from overlay.lock.json pins (module extension `lock_repos`).

- `rules_fuchsia`: the lock's CIPD instance of fuchsia/development/rules_fuchsia.
- `fuchsia_idk`: the release's IDK core.tar.gz, checked by SHA-256.
- `fuchsia_rust_toolchain`: the release's pinned Rust toolchain (design D3): the host
  compiler, the Fuchsia target std libraries and the host (x86_64-unknown-linux-gnu) std,
  three CIPD instances merged into one tree the way upstream's prebuilt directory is.

`@fuchsia_sdk` and `@fuchsia_clang` need rules from `@rules_fuchsia`, so they come from a
second extension (`fuchsia.bzl`).
"""

load(":lock.bzl", "cipd_package", "lock_field", "read_lock")

def _cipd_repository_impl(rctx):
    if len(rctx.attr.urls) != len(rctx.attr.sha256s):
        fail("urls and sha256s differ in length")
    for url, sha256 in zip(rctx.attr.urls, rctx.attr.sha256s):
        # The CIPD instance ID in the URL and `sha256` name the same bytes; Bazel fails
        # the fetch if the downloaded zip hashes to anything else.
        rctx.download_and_extract(url = url, sha256 = sha256, type = "zip")

    # Each CIPD package carries its own metadata directory; it is not toolchain content.
    rctx.delete(".cipdpkg")
    if rctx.attr.build_file:
        rctx.symlink(rctx.attr.build_file, "BUILD.bazel")
    elif not rctx.path("BUILD.bazel").exists:
        fail("%s: the package has no BUILD.bazel and no build_file was given" % rctx.name)

cipd_repository = repository_rule(
    implementation = _cipd_repository_impl,
    doc = "Extracts one or more CIPD instances, each pinned by SHA-256, into one tree.",
    attrs = {
        "urls": attr.string_list(mandatory = True, doc = "CIPD /dl/ URLs, one per instance."),
        "sha256s": attr.string_list(mandatory = True, doc = "The instance SHA-256 for each URL."),
        "build_file": attr.label(
            allow_single_file = True,
            doc = "BUILD file for the tree; omit when the package ships its own.",
        ),
    },
)

def _idk_repository_impl(rctx):
    rctx.download_and_extract(url = rctx.attr.url, sha256 = rctx.attr.sha256, type = "tar.gz")

    # @fuchsia_sdk is generated from this tree by rules_fuchsia; nothing builds here.
    rctx.file("BUILD.bazel", "# The release's IDK, as downloaded. @fuchsia_sdk is generated from it.\n")

idk_repository = repository_rule(
    implementation = _idk_repository_impl,
    doc = "The release's IDK (core.tar.gz), checked by SHA-256.",
    attrs = {
        "url": attr.string(mandatory = True),
        "sha256": attr.string(mandatory = True),
    },
)

def _cipd_repo(name, lock, fields, **kwargs):
    pkgs = [cipd_package(lock, f) for f in fields]
    cipd_repository(
        name = name,
        urls = [p.url for p in pkgs],
        sha256s = [p.sha256 for p in pkgs],
        **kwargs
    )

def _lock_repos_impl(module_ctx):
    lock = read_lock(module_ctx)
    _cipd_repo("rules_fuchsia", lock, ["rules_fuchsia"])
    idk = lock_field(lock, "bazel_sdk")
    idk_repository(name = "fuchsia_idk", url = idk["url"], sha256 = idk["value"])
    _cipd_repo(
        "fuchsia_rust_toolchain",
        lock,
        ["rust_host", "rust_target", "rust_host_std"],
        build_file = Label("//toolchain:rust.BUILD.bazel"),
    )
    return module_ctx.extension_metadata(reproducible = True)

lock_repos = module_extension(
    implementation = _lock_repos_impl,
    doc = "Repositories pinned by overlay.lock.json that need nothing from rules_fuchsia.",
)
