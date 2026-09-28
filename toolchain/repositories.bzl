# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0

"""Repositories fetched from overlay.lock.json pins (module extension `lock_repos`).

- `rules_fuchsia`: the lock's CIPD instance of fuchsia/development/rules_fuchsia.
- `fuchsia_idk`: the release's IDK core.tar.gz, checked by SHA-256, then extracted in
  full or trimmed according to the environment profile (design C6).
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

# The environment profile (design C6) is resolved by scripts/overlay_profile.py, which
# reads these variables and this file under the config directory. The rule reads them
# through rctx.getenv/rctx.watch so that Bazel refetches the IDK when the profile changes.
_PROFILE_ENV = ["OVERLAY_PROFILE", "XDG_CONFIG_HOME", "HOME"]
_PROFILE_FILE = "fuchsia-rust-sdk/profile"
_ARCHIVE = "_overlay_idk.tar.gz"

def _python(rctx):
    python = rctx.which("python3")
    if not python:
        fail("fuchsia_idk: python3 (>= 3.11) not found on PATH; it extracts the IDK")
    return python

def _run_script(rctx, python, script, args, env):
    result = rctx.execute([python, script] + args, environment = env, quiet = True, timeout = 1800)
    if result.return_code != 0:
        fail("fuchsia_idk: %s failed (exit %d):\n%s%s" % (
            script.basename,
            result.return_code,
            result.stdout,
            result.stderr,
        ))
    return result.stdout

def _profile(rctx, python):
    env = {k: rctx.getenv(k, "") for k in _PROFILE_ENV}
    config_dir = env["XDG_CONFIG_HOME"] or (env["HOME"] + "/.config" if env["HOME"] else "")
    if config_dir:
        # Watched whether or not it exists, so creating the file refetches too.
        rctx.watch(config_dir + "/" + _PROFILE_FILE)
    script = rctx.path(Label("//:scripts/overlay_profile.py"))
    rctx.watch(script)
    return json.decode(_run_script(rctx, python, script, ["--json"], env))

def _idk_repository_impl(rctx):
    python = _python(rctx)
    profile = _profile(rctx, python)

    # Bazel checks the SHA-256 of the whole archive before writing it out, so a tampered
    # or substituted archive fails here, before any extraction or trim. (Bazel also puts
    # the archive in the repository cache; the hosted profile removes it afterwards, see
    # scripts/bazel and scripts/disk_report.py --prune.)
    rctx.download(url = rctx.attr.url, output = _ARCHIVE, sha256 = rctx.attr.sha256)

    # idk_extract.py checks the SHA-256 again (it is also a standalone tool), then
    # extracts, trimmed under a profile with trim_idk, and writes .overlay-idk-trim.json.
    # It imports overlay_profile.py, which _profile() already watches.
    script = rctx.path(Label("//:scripts/idk_extract.py"))
    rctx.watch(script)
    out = _run_script(rctx, python, script, [
        "--archive",
        _ARCHIVE,
        "--sha256",
        rctx.attr.sha256,
        "--profile",
        profile["name"],
        "--dest",
        ".",
    ], {})
    rctx.report_progress(out.strip())
    rctx.delete(_ARCHIVE)

    # @fuchsia_sdk is generated from this tree by rules_fuchsia; nothing builds here.
    rctx.file("BUILD.bazel", "# The release's IDK (%s profile). @fuchsia_sdk is generated from it.\n" % profile["name"])

idk_repository = repository_rule(
    implementation = _idk_repository_impl,
    doc = "The release's IDK (core.tar.gz), checked by SHA-256, trimmed per the environment profile.",
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
