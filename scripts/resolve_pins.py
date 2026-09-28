#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Resolve a Fuchsia SDK version to the pins in overlay.lock.json (design R1).

Usage: resolve_pins.py <sdk-version> [--out overlay.lock.json]

Every lookup is anonymous (C1): HTTPS GETs to GCS, CIPD's public pRPC API, and
git over HTTPS to fuchsia.googlesource.com (never gitiles). The lock is written
only when every field resolves, atomically (temp file, then os.replace), with
sorted keys and a trailing newline, so two runs give byte-identical output.

Lock schema: one object per field, each with "value" and "source", a list of the
upstream artifacts the value came from. CIPD fields also carry "package", and
bazel_sdk carries "url".
Git sources read "<repo> <revision>:<path>", a revspec for `git cat-file -p`.

  sdk_version           the requested version, as the product bundles list it
  fuchsia_revision      fuchsia.git commit; every product build must agree
  integration_revision  integration commit; the builds and the IDK's CIPD tag agree
  rust_host             CIPD instance (hex SHA-256), host toolchain, linux-amd64
  rust_target           CIPD instance, Fuchsia target std libraries
  rust_host_std         CIPD instance, x86_64-unknown-linux-gnu std (the host package
                        has none; proc macros and host tools need it)
  clang                 CIPD instance, clang for linux-amd64 (@fuchsia_clang)
  go                    CIPD instance, Fuchsia's Go SDK for linux-amd64 (rules_go's SDK,
                        which builds fidlgen_rust; milestone M7)
  bazel_sdk             SHA-256 of the release's IDK core.tar.gz (linux-amd64);
                        "url" is where to download it
  rules_fuchsia         CIPD instance of fuchsia/development/rules_fuchsia at the
                        integration revision
  cargo_lock_sha256     SHA-256 of third_party/rust_crates/Cargo.lock at the revision
  product_bundle        the core.x64 product bundle the emulator boots (scripts/emu):
                        "url" is its transfer manifest (from product_bundles.json),
                        "files" the number of files, and "value" the bundle digest:
                        SHA-256 over the UTF-8 lines "<path>\t<sha256>\n", one per file,
                        sorted by path, where <path> is the file's path inside the
                        downloaded bundle directory (blobs/1/<merkle>, product_bundle.json,
                        system_a/fuchsia.zbi, ...) and <sha256> the hex SHA-256 of its
                        bytes as served (see bundle_digest). Upstream pins none of these
                        files by content hash, so resolving streams every file (~364 MB
                        for 33.20260927.4.1) without storing it.
  fidlgen_rust_next     the release's prebuilt FIDL generator for rust_next bindings
                        (host_x64), from the public debug-symbol store (docs/evidence/I2.md):
                        "build_id" is the ELF build ID the release's build manifests
                        (build-ids.json) give its GN label, "url" the store's
                        buildid/<id>/executable object, and "value" the SHA-256 of that
                        object's bytes as served (decoded; see resolve_fidlgen_rust_next).
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import http.client
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

GCS = "https://storage.googleapis.com"
CIPD_RPC = "https://chrome-infra-packages.appspot.com/prpc/cipd.Repository"
CIPD_UI = "https://chrome-infra-packages.appspot.com/p"
FUCHSIA_GIT = "https://fuchsia.googlesource.com/fuchsia"
HOST_PLATFORM = "linux-amd64"  # C5

IDK_CIPD_PACKAGE = f"fuchsia/sdk/core/{HOST_PLATFORM}"
# Lock field -> package name as manifests/toolchain spells it. All are resolved for
# HOST_PLATFORM. The Rust packages must share one pin: std must come from the same
# compiler build as rustc.
TOOLCHAIN_PACKAGES = (
    ("rust_host", "fuchsia/third_party/rust/host/${platform}"),
    ("rust_target", "fuchsia/third_party/rust/target/fuchsia"),
    ("rust_host_std", "fuchsia/third_party/rust/target/x86_64-unknown-linux-gnu"),
    ("clang", "fuchsia/third_party/clang/${platform}"),
    ("go", "fuchsia/go/${platform}"),
)
RUST_FIELDS = ("rust_host", "rust_target", "rust_host_std")
RULES_FUCHSIA_PACKAGE = "fuchsia/development/rules_fuchsia"
TOOLCHAIN_MANIFEST = "manifests/toolchain"
CARGO_LOCK = "third_party/rust_crates/Cargo.lock"
EMULATOR_PRODUCT = "core.x64"
# The rust_next FIDL generator (milestone M7): the GN label the release's build-ids.json
# files map its ELF build ID to, and the store the executable is fetched from.
FIDLGEN_RUST_NEXT_LABEL = "//tools/fidl/fidlgen_rust_next:fidlgen_rust_next.actual(//build/toolchain:host_x64)"
RELEASE_BUCKET = f"{GCS}/fuchsia-public-artifacts-release"
# Files are hashed in parallel; each request streams one file.
BUNDLE_WORKERS = 8

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "overlay.lock.json"

_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"[0-9]+(\.[0-9]+)+")


class ResolveError(Exception):
    """A field could not be resolved. `field` names the lock key."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field = field


class FetchError(Exception):
    """An upstream request failed; `status` is the HTTP status when there was one."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Digest:
    sha256: str  # hex
    md5: str  # hex
    size: int


class Upstream(Protocol):
    """Every network access the resolver makes. Tests substitute a stub.

    Each method raises FetchError on any failure, including a missing git path.
    """

    def get(self, url: str) -> bytes: ...

    def post_json(self, url: str, payload: dict) -> bytes: ...

    def digest(self, url: str) -> Digest: ...

    def git_show(self, repo: str, revision: str, path: str) -> bytes: ...


# Environment variables git may keep: CA trust for TLS only. Every other GIT_* variable
# (including GIT_CONFIG_COUNT/KEY/VALUE and GIT_CONFIG_PARAMETERS, which inject config)
# is dropped, as is SSH_ASKPASS.
_GIT_ENV_KEEP = ("GIT_SSL_CAINFO", "GIT_SSL_CAPATH")


def isolated_git(gitdir: Path, home: Path, *args: str, stdin: bytes | None = None,
                 extra_env: dict[str, str] | None = None) -> bytes:
    """Run `git -C gitdir args...` isolated from user and system configuration (C1).

    No system or global config, HOME and XDG_CONFIG_HOME set to `home` (so curl does not
    read ~/.netrc), no credential helper, cookie file or askpass, and no inherited GIT_*
    variables except CA trust. `extra_env` adds variables after that scrub (regen.py
    uses it for GIT_CEILING_DIRECTORIES). Returns stdout; raises FetchError on failure.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "SSH_ASKPASS"}
    env.update({k: os.environ[k] for k in _GIT_ENV_KEEP if k in os.environ})
    env.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home),
    })
    env.update(extra_env or {})
    cmd = ["git", "-c", "credential.helper=", "-c", "http.cookieFile=", "-c", "core.askPass=",
           "-c", "protocol.version=2", "-C", str(gitdir), *args]
    p = subprocess.run(cmd, env=env, capture_output=True, input=stdin)
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise FetchError(f"git {' '.join(args)}: {err[-1] if err else f'exit {p.returncode}'}")
    return p.stdout


class LiveUpstream:
    """Anonymous HTTPS (urllib) and git (subprocess). Sends no credentials (C1).

    urllib sends no credentials unless given an auth handler; it does not read
    ~/.netrc. git runs with no system or global config, an empty HOME (so curl does not
    read ~/.netrc), no credential helper, cookie file or askpass, and no inherited
    GIT_* configuration.
    """

    TIMEOUT = 120
    HEADERS = {"User-Agent": "fuchsia-rust-sdk-resolve-pins/1"}

    def __init__(self):
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._fetched: dict[tuple[str, str], Path] = {}

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
            self._fetched.clear()

    def _request(self, request: urllib.request.Request, consume):
        """Open `request` and pass the response to `consume`; any failure is a FetchError."""
        what = f"{request.get_method()} {request.full_url}"
        try:
            with urllib.request.urlopen(request, timeout=self.TIMEOUT) as r:
                return consume(r)
        except urllib.error.HTTPError as e:
            body = e.read(200).decode("utf-8", "replace").strip()
            raise FetchError(f"{what}: HTTP {e.code} {body}", e.code) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            # OSError covers TimeoutError and connection resets mid-stream;
            # HTTPException covers IncompleteRead (a truncated body).
            raise FetchError(f"{what}: {type(e).__name__}: {e}") from None

    def get(self, url: str) -> bytes:
        return self._request(urllib.request.Request(url, headers=self.HEADERS), lambda r: r.read())

    def post_json(self, url: str, payload: dict) -> bytes:
        headers = {**self.HEADERS, "Content-Type": "application/json", "Accept": "application/json"}
        data = json.dumps(payload).encode()
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        return self._request(request, lambda r: r.read())

    def digest(self, url: str) -> Digest:
        def consume(r) -> Digest:
            sha, md5, size = hashlib.sha256(), hashlib.md5(), 0
            while chunk := r.read(1 << 20):
                sha.update(chunk)
                md5.update(chunk)
                size += len(chunk)
            # read(amt) returns a short body without raising, so check the length.
            expected = r.headers.get("Content-Length")
            if expected is not None and int(expected) != size:
                raise http.client.IncompleteRead(b"", int(expected) - size)
            return Digest(sha.hexdigest(), md5.hexdigest(), size)

        return self._request(urllib.request.Request(url, headers=self.HEADERS), consume)

    def _git(self, gitdir: Path, home: Path, *args: str) -> bytes:
        return isolated_git(gitdir, home, *args)

    def _commit(self, repo: str, revision: str) -> tuple[Path, Path]:
        """A depth-1, blobless fetch of one commit, done once per (repo, revision).

        `cat-file` later fetches only the blobs asked for. No clone, no checkout, no gitiles.
        """
        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="resolve_pins-")
        root = Path(self._tmp.name)
        home = root / "home"
        home.mkdir(exist_ok=True)
        key = (repo, revision)
        if key not in self._fetched:
            gitdir = root / f"repo{len(self._fetched)}.git"
            gitdir.mkdir()
            self._git(gitdir, home, "init", "-q", "--bare")
            self._git(gitdir, home, "fetch", "-q", "--depth", "1", "--filter=blob:none", repo, revision)
            fetched = self._git(gitdir, home, "rev-parse", "FETCH_HEAD").decode().strip()
            if fetched != revision:
                raise FetchError(f"git fetch {repo} {revision}: got {fetched}")
            self._fetched[key] = gitdir
        return self._fetched[key], home

    def git_show(self, repo: str, revision: str, path: str) -> bytes:
        gitdir, home = self._commit(repo, revision)
        return self._git(gitdir, home, "cat-file", "-p", f"{revision}:{path}")


# --- lookups -----------------------------------------------------------------


def _json(field: str, raw: bytes, what: str, shape: type = dict):
    """Parse JSON whose top level must be `shape` (dict or list)."""
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ResolveError(field, f"{what}: not JSON ({e})") from None
    if not isinstance(data, shape):
        raise ResolveError(field, f"{what}: expected a JSON {shape.__name__}, got {type(data).__name__}")
    return data


def _obj(field: str, value, what: str) -> dict:
    """`value` must be a JSON object; anything else is a field-named error."""
    if not isinstance(value, dict):
        raise ResolveError(field, f"{what}: expected an object, got {type(value).__name__}")
    return value


def _cipd_call(up: Upstream, field: str, method: str, payload: dict, missing_ok: bool = False) -> dict | None:
    try:
        raw = up.post_json(f"{CIPD_RPC}/{method}", payload)
    except FetchError as e:
        if missing_ok and e.status == 404:
            return None
        raise ResolveError(field, f"CIPD {method} {payload.get('package')} {payload.get('version', '')}: {e}") from None
    # pRPC prefixes JSON replies with an XSSI guard line.
    if raw.startswith(b")]}'"):
        raw = raw.split(b"\n", 1)[1] if b"\n" in raw else b""
    return _json(field, raw, f"CIPD {method}")


def cipd_resolve(up: Upstream, field: str, package: str, version: str, missing_ok: bool = False) -> str | None:
    """Return the hex SHA-256 instance ID that `version` (a tag or ref) names.

    With missing_ok, a 404 (no such tag or package) returns None; other errors raise.
    """
    reply = _cipd_call(up, field, "ResolveVersion", {"package": package, "version": version}, missing_ok)
    if reply is None:
        return None
    instance = _obj(field, reply.get("instance", {}), f"CIPD ResolveVersion {package} {version} instance")
    digest = instance.get("hexDigest", "")
    if instance.get("hashAlgo") != "SHA256" or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ResolveError(field, f"CIPD ResolveVersion {package} {version}: unexpected instance {instance!r}")
    return digest


def cipd_tags(up: Upstream, field: str, package: str, digest: str) -> dict[str, set[str]]:
    reply = _cipd_call(up, field, "DescribeInstance", {
        "package": package,
        "instance": {"hashAlgo": "SHA256", "hexDigest": digest},
        "describeTags": True,
    })
    tags: dict[str, set[str]] = {}
    raw_tags = reply.get("tags", [])
    if not isinstance(raw_tags, list):
        raise ResolveError(field, f"CIPD DescribeInstance {package} {digest}: tags is {type(raw_tags).__name__}")
    for tag in raw_tags:
        tag = _obj(field, tag, f"CIPD DescribeInstance {package} {digest} tag")
        tags.setdefault(tag.get("key", ""), set()).add(tag.get("value", ""))
    return tags


def cipd_source(package: str, version: str) -> str:
    return f"{CIPD_UI}/{package}/+/{version}"


def git_source(path: str, revision: str) -> str:
    return f"{FUCHSIA_GIT} {revision}:{path}"


def resolve_revisions(up: Upstream, version: str) -> dict:
    """I1 method: product bundles -> build source manifests, tied to the IDK via CIPD."""
    pb_url = f"{GCS}/fuchsia/development/{version}/product_bundles.json"
    try:
        bundles = _json("sdk_version", up.get(pb_url), pb_url, list)
    except FetchError as e:
        raise ResolveError("sdk_version", f"unknown SDK version? {e}") from None
    if not bundles:
        raise ResolveError("sdk_version", f"{pb_url}: no product bundles")
    build_ids = set()
    for b in bundles:
        b = _obj("sdk_version", b, f"{pb_url} entry")
        if b.get("product_version") != version:
            raise ResolveError("sdk_version", f"{pb_url}: {b.get('name')} has product_version {b.get('product_version')!r}")
        m = re.search(r"/builds/(\d+)/", b.get("transfer_manifest_url", ""))
        if not m:
            raise ResolveError("sdk_version", f"{pb_url}: no build id in {b.get('transfer_manifest_url')!r}")
        build_ids.add(m.group(1))

    manifests = sorted(f"{GCS}/fuchsia-public-artifacts-release/builds/{i}/source_manifest.json" for i in build_ids)
    fuchsia, integration = {}, {}
    for url in manifests:
        try:
            dirs = _json("fuchsia_revision", up.get(url), url)["directories"]
            f, i = dirs["."]["git_checkout"], dirs["integration"]["git_checkout"]
            f_repo, f_rev, i_rev = f.get("repo_url"), f.get("revision"), i.get("revision")
        except FetchError as e:
            raise ResolveError("fuchsia_revision", str(e)) from None
        except (KeyError, TypeError, AttributeError) as e:
            raise ResolveError("fuchsia_revision", f"{url}: malformed ({type(e).__name__}: {e})") from None
        if f_repo != FUCHSIA_GIT:
            raise ResolveError("fuchsia_revision", f"{url}: '.' is {f_repo!r}, not {FUCHSIA_GIT}")
        fuchsia[url], integration[url] = f_rev, i_rev

    if len(set(fuchsia.values())) != 1:
        raise ResolveError("fuchsia_revision", f"product builds disagree: {sorted(set(fuchsia.values()), key=str)}")
    if len(set(integration.values())) != 1:
        raise ResolveError("integration_revision", f"product builds disagree: {sorted(set(integration.values()), key=str)}")
    fx_rev, int_rev = fuchsia[manifests[0]], integration[manifests[0]]
    if not isinstance(fx_rev, str) or not _SHA1.fullmatch(fx_rev):
        raise ResolveError("fuchsia_revision", f"not a commit id: {fx_rev!r}")
    if not isinstance(int_rev, str) or not _SHA1.fullmatch(int_rev):
        raise ResolveError("integration_revision", f"not a commit id: {int_rev!r}")

    idk_version = f"version:{version}"
    idk = cipd_resolve(up, "integration_revision", IDK_CIPD_PACKAGE, idk_version)
    idk_integration = cipd_tags(up, "integration_revision", IDK_CIPD_PACKAGE, idk).get("git_revision", set())
    if idk_integration != {int_rev}:
        raise ResolveError(
            "integration_revision",
            f"IDK {IDK_CIPD_PACKAGE} {idk} has git_revision {sorted(idk_integration)}, builds have {int_rev}",
        )
    return {
        "sdk_version": {"value": version, "source": [pb_url]},
        "fuchsia_revision": {"value": fx_rev, "source": manifests},
        "integration_revision": {
            "value": int_rev,
            "source": [*manifests, cipd_source(IDK_CIPD_PACKAGE, idk_version)],
        },
    }


def parse_toolchain_manifest(text: bytes) -> dict[str, str]:
    """Map each TOOLCHAIN_PACKAGES field to its pinned version tag in manifests/toolchain."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ResolveError("rust_host", f"{TOOLCHAIN_MANIFEST}: not XML ({e})") from None
    found: dict[str, list[ET.Element]] = {}
    for pkg in root.iter("package"):
        found.setdefault(pkg.get("name", ""), []).append(pkg)
    pins = {}
    for field, name in TOOLCHAIN_PACKAGES:
        entries = found.get(name, [])
        if len(entries) != 1:
            raise ResolveError(field, f"{TOOLCHAIN_MANIFEST}: expected one package {name}, found {len(entries)}")
        pkg = entries[0]
        if HOST_PLATFORM not in pkg.get("platforms", "").split(","):
            raise ResolveError(field, f"{TOOLCHAIN_MANIFEST}: {name} not pinned for {HOST_PLATFORM}")
        if not pkg.get("version"):
            raise ResolveError(field, f"{TOOLCHAIN_MANIFEST}: {name} has no version")
        pins[field] = pkg.get("version")
    for field in RUST_FIELDS[1:]:
        if pins[field] != pins["rust_host"]:
            raise ResolveError(field, f"{TOOLCHAIN_MANIFEST}: pinned at {pins[field]}, "
                                      f"but rust_host is pinned at {pins['rust_host']}")
    return pins


def read_git_file(up: Upstream, field: str, path: str, revision: str) -> bytes:
    """Read one file at the release revision; a failure names the field that needs it.

    The first read also fetches the commit, so a fetch failure is reported by the
    first field that needs the commit's files (rust_host).
    """
    try:
        data = up.git_show(FUCHSIA_GIT, revision, path)
    except FetchError as e:
        raise ResolveError(field, f"{git_source(path, revision)}: {e}") from None
    if not data:
        raise ResolveError(field, f"{git_source(path, revision)}: empty")
    return data


def resolve_toolchain(up: Upstream, manifest: bytes, revision: str) -> dict:
    pins = parse_toolchain_manifest(manifest)
    out = {}
    for field, name in TOOLCHAIN_PACKAGES:
        package = name.replace("${platform}", HOST_PLATFORM)
        out[field] = {
            "package": package,
            "value": cipd_resolve(up, field, package, pins[field]),
            "source": [git_source(TOOLCHAIN_MANIFEST, revision), cipd_source(package, pins[field])],
        }
    return out


def resolve_bazel_sdk(up: Upstream, version: str, integration: str) -> dict:
    """The release's own IDK tarball by SHA-256, and rules_fuchsia at its integration commit."""
    obj = f"development/{version}/sdk/{HOST_PLATFORM}/core.tar.gz"
    url = f"{GCS}/fuchsia/{obj}"
    meta_url = f"{GCS}/storage/v1/b/fuchsia/o/{obj.replace('/', '%2F')}"
    try:
        meta = _json("bazel_sdk", up.get(meta_url), meta_url)
        size, md5 = int(meta["size"]), base64.b64decode(meta["md5Hash"]).hex()
    except FetchError as e:
        raise ResolveError("bazel_sdk", str(e)) from None
    except (KeyError, ValueError, TypeError) as e:
        raise ResolveError("bazel_sdk", f"{meta_url}: bad metadata ({e})") from None
    try:
        d = up.digest(url)
    except FetchError as e:
        raise ResolveError("bazel_sdk", str(e)) from None
    if (d.size, d.md5) != (size, md5):
        raise ResolveError("bazel_sdk", f"{url}: got {d.size} bytes md5 {d.md5}, GCS says {size} bytes md5 {md5}")

    by_rev = f"git_revision:{integration}"
    rules = cipd_resolve(up, "rules_fuchsia", RULES_FUCHSIA_PACKAGE, by_rev)
    # Cross-check: if the package also carries version:<V>, it must be the same instance.
    by_version = f"version:{version}"
    other = cipd_resolve(up, "rules_fuchsia", RULES_FUCHSIA_PACKAGE, by_version, missing_ok=True)
    if other is not None and other != rules:
        raise ResolveError("rules_fuchsia", f"{by_rev} is {rules} but {by_version} is {other}")
    return {
        "bazel_sdk": {"url": url, "value": d.sha256, "source": [url]},
        "rules_fuchsia": {
            "package": RULES_FUCHSIA_PACKAGE,
            "value": rules,
            "source": [cipd_source(RULES_FUCHSIA_PACKAGE, by_rev)],
        },
    }


def bundle_digest(sha256_by_path: dict[str, str]) -> str:
    """The product_bundle lock value: SHA-256 over sorted "<path>\t<sha256>\n" lines.

    scripts/emu computes the same over the downloaded bundle directory and refuses a
    mismatch, so this function is the one definition both sides use.
    """
    lines = "".join(f"{path}\t{sha256_by_path[path]}\n" for path in sorted(sha256_by_path))
    return hashlib.sha256(lines.encode()).hexdigest()


def gs_to_https(url: str) -> str:
    if not url.startswith("gs://"):
        raise ValueError(f"not a gs:// URL: {url!r}")
    return f"{GCS}/{url[len('gs://'):]}"


_BUNDLE_PART = re.compile(r"[A-Za-z0-9._,+=@-]+")


def _bundle_path(field: str, path: str, what: str) -> str:
    parts = path.split("/")
    if not path or any(p in ("", ".", "..") or not _BUNDLE_PART.fullmatch(p) for p in parts):
        raise ResolveError(field, f"{what}: unsafe path {path!r}")
    return path


def parse_transfer_manifest(field: str, raw: bytes, url: str) -> dict[str, str]:
    """Map each file's path inside the downloaded bundle to its HTTPS URL.

    A transfer manifest (version 1) lists entries of type "blobs" or "files", each with
    a "local" directory ("product_bundle" or below it: the bundle directory), a "remote"
    object prefix in the manifest's own bucket, and the file names.
    """
    data = _json(field, raw, url)
    if data.get("version") not in ("1", 1):  # served as the string "1"
        raise ResolveError(field, f"{url}: transfer manifest version {data.get('version')!r}, expected 1")
    bucket = url.split("/")[3]
    files: dict[str, str] = {}
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ResolveError(field, f"{url}: no entries")
    for entry in entries:
        entry = _obj(field, entry, f"{url} entry")
        if entry.get("type") not in ("blobs", "files"):
            raise ResolveError(field, f"{url}: entry type {entry.get('type')!r}")
        local = entry.get("local")
        if not isinstance(local, str) or not (local == "product_bundle" or local.startswith("product_bundle/")):
            raise ResolveError(field, f"{url}: entry local {local!r} is outside product_bundle")
        prefix = local[len("product_bundle"):].lstrip("/")
        if prefix:
            _bundle_path(field, prefix, f"{url} local")
        remote = entry.get("remote")
        if not isinstance(remote, str):
            raise ResolveError(field, f"{url}: entry remote {remote!r}")
        _bundle_path(field, remote, f"{url} remote")
        names = entry.get("entries")
        if not isinstance(names, list) or not names:
            raise ResolveError(field, f"{url}: {entry['type']} entry has no files")
        for item in names:
            name = _obj(field, item, f"{url} file").get("name")
            if not isinstance(name, str):
                raise ResolveError(field, f"{url}: file name {name!r}")
            _bundle_path(field, name, f"{url} file")
            path = f"{prefix}/{name}" if prefix else name
            if path in files:
                raise ResolveError(field, f"{url}: {path} listed twice")
            files[path] = f"{GCS}/{bucket}/{remote}/{name}"
    return files


def resolve_product_bundle(up: Upstream, version: str, product: str = EMULATOR_PRODUCT) -> dict:
    """The emulator's product bundle: transfer manifest and a digest over every file."""
    field = "product_bundle"
    pb_url = f"{GCS}/fuchsia/development/{version}/product_bundles.json"
    try:
        bundles = _json(field, up.get(pb_url), pb_url, list)
    except FetchError as e:
        raise ResolveError(field, str(e)) from None
    matches = [b for b in bundles if isinstance(b, dict) and b.get("name") == product]
    if len(matches) != 1:
        raise ResolveError(field, f"{pb_url}: {len(matches)} entries named {product}")
    gs_url = matches[0].get("transfer_manifest_url", "")
    if not isinstance(gs_url, str) or not re.fullmatch(r"gs://[a-z0-9._-]+/\S+/transfer\.json", gs_url):
        raise ResolveError(field, f"{pb_url}: {product} transfer manifest URL {gs_url!r}")
    manifest_url = gs_to_https(gs_url)
    try:
        files = parse_transfer_manifest(field, up.get(manifest_url), manifest_url)
    except FetchError as e:
        raise ResolveError(field, str(e)) from None
    with concurrent.futures.ThreadPoolExecutor(BUNDLE_WORKERS) as pool:
        futures = {path: pool.submit(up.digest, url) for path, url in files.items()}
        sha: dict[str, str] = {}
        for path, future in futures.items():
            try:
                sha[path] = future.result().sha256
            except FetchError as e:
                pool.shutdown(cancel_futures=True)  # do not fetch the rest
                raise ResolveError(field, f"{path}: {e}") from None
    return {"product_bundle": {
        "product": product,
        "url": gs_url,
        "files": len(sha),
        "value": bundle_digest(sha),
        "source": [pb_url, manifest_url],
    }}


# --- fidlgen_rust_next (milestone M7) ----------------------------------------------

_ELF_MAGIC = b"\x7fELF"
_EM_X86_64 = 62
_SHT_NOTE = 7
_NT_GNU_BUILD_ID = 3


def elf_build_ids(field: str, data: bytes, what: str) -> set[str]:
    """The GNU build IDs (hex) in the SHT_NOTE sections of a little-endian ELF64 x86-64 file.

    Anything else, and any header or note that runs past the end of the file, is a
    field-named error.
    """
    if len(data) < 64 or data[:4] != _ELF_MAGIC:
        raise ResolveError(field, f"{what}: not an ELF file")
    if data[4] != 2 or data[5] != 1:
        raise ResolveError(field, f"{what}: not a little-endian ELF64 file (class {data[4]}, data {data[5]})")
    machine = struct.unpack_from("<H", data, 18)[0]
    if machine != _EM_X86_64:
        raise ResolveError(field, f"{what}: e_machine {machine}, expected x86-64 ({_EM_X86_64})")
    shoff = struct.unpack_from("<Q", data, 40)[0]
    shentsize, shnum = struct.unpack_from("<HH", data, 58)
    if shnum == 0 or shentsize < 64 or shoff + shnum * shentsize > len(data):
        raise ResolveError(field, f"{what}: bad section header table")
    ids: set[str] = set()
    for i in range(shnum):
        sh = shoff + i * shentsize
        sh_type = struct.unpack_from("<I", data, sh + 4)[0]
        if sh_type != _SHT_NOTE:
            continue
        offset, size = struct.unpack_from("<QQ", data, sh + 24)
        if offset + size > len(data):
            raise ResolveError(field, f"{what}: note section {i} runs past the end of the file")
        pos, end = offset, offset + size
        while pos + 12 <= end:
            namesz, descsz, ntype = struct.unpack_from("<III", data, pos)
            name_end = pos + 12 + namesz
            desc = name_end + (-namesz % 4)
            desc_end = desc + descsz
            if desc_end > end:
                raise ResolveError(field, f"{what}: note in section {i} runs past its section")
            if ntype == _NT_GNU_BUILD_ID and data[pos + 12:name_end] == b"GNU\0":
                ids.add(data[desc:desc_end].hex())
            pos = desc_end + (-descsz % 4)
    return ids


def resolve_fidlgen_rust_next(up: Upstream, version: str, product: str = EMULATOR_PRODUCT) -> dict:
    """The prebuilt rust_next FIDL generator, tied to the release by its build manifests.

    Every product build of the release publishes build-ids.json (ELF build ID -> GN
    label). The ID labelled FIDLGEN_RUST_NEXT_LABEL must be present in the `product`
    build (core.x64, the lock's product_bundle), and every build that names that label
    must give the same, single ID; builds that do not name it (core.vim3 builds only a
    host_x64-novariant copy) are skipped. The executable is fetched from the debug-symbol
    store by that ID, its .note.gnu.build-id must equal it, and the lock pins the
    SHA-256 of the bytes as served. GCS stores the object gzip-encoded and decodes it for
    a client that does not send Accept-Encoding: gzip (urllib sends none), so the bytes
    hashed here are the ELF file, as Bazel's download sees them. Fails closed on any
    missing, extra or mismatching piece.
    """
    field = "fidlgen_rust_next"
    pb_url = f"{GCS}/fuchsia/development/{version}/product_bundles.json"
    try:
        bundles = _json(field, up.get(pb_url), pb_url, list)
    except FetchError as e:
        raise ResolveError(field, str(e)) from None
    builds: dict[str, str] = {}  # build id -> product name
    for b in bundles:
        b = _obj(field, b, f"{pb_url} entry")
        m = re.search(r"/builds/(\d+)/", str(b.get("transfer_manifest_url", "")))
        if not m:
            raise ResolveError(field, f"{pb_url}: no build id in {b.get('transfer_manifest_url')!r}")
        builds[m.group(1)] = str(b.get("name"))
    main = [build for build, name in builds.items() if name == product]
    if len(main) != 1:
        raise ResolveError(field, f"{pb_url}: {len(main)} builds named {product}")
    found: dict[str, str] = {}  # build-ids.json URL -> build ID
    for build in sorted(builds):
        url = f"{RELEASE_BUCKET}/builds/{build}/build-ids.json"
        try:
            ids = _json(field, up.get(url), url)
        except FetchError as e:
            raise ResolveError(field, str(e)) from None
        named = sorted(k for k, v in ids.items() if v == FIDLGEN_RUST_NEXT_LABEL)
        if len(named) > 1:
            raise ResolveError(field, f"{url}: {len(named)} build IDs for {FIDLGEN_RUST_NEXT_LABEL}")
        if named:
            found[url] = named[0]
        elif build == main[0]:
            raise ResolveError(field, f"{url} ({product}): no build ID for {FIDLGEN_RUST_NEXT_LABEL}")
    if len(set(found.values())) != 1:
        raise ResolveError(field, f"builds disagree on {FIDLGEN_RUST_NEXT_LABEL}: {sorted(set(found.values()))}")
    build_id = next(iter(found.values()))
    if not _SHA1.fullmatch(build_id):
        raise ResolveError(field, f"build ID {build_id!r} is not 40 hex digits")
    exe_url = f"{RELEASE_BUCKET}/buildid/{build_id}/executable"
    try:
        data = up.get(exe_url)
    except FetchError as e:
        raise ResolveError(field, str(e)) from None
    notes = elf_build_ids(field, data, exe_url)
    if notes != {build_id}:
        raise ResolveError(field, f"{exe_url}: .note.gnu.build-id is {sorted(notes)}, expected {build_id}")
    return {field: {
        "build_id": build_id,
        "url": exe_url,
        "value": hashlib.sha256(data).hexdigest(),
        "source": [pb_url, *sorted(found), exe_url],
    }}


def resolve(up: Upstream, version: str) -> dict:
    """Resolve every field, or raise ResolveError naming the first that fails."""
    if not _VERSION.fullmatch(version):
        raise ResolveError("sdk_version", f"not an SDK version: {version!r}")
    lock = resolve_revisions(up, version)
    revision = lock["fuchsia_revision"]["value"]
    # manifests/toolchain serves every TOOLCHAIN_PACKAGES field; rust_host is resolved first.
    manifest = read_git_file(up, "rust_host", TOOLCHAIN_MANIFEST, revision)
    lock.update(resolve_toolchain(up, manifest, revision))
    cargo_lock = read_git_file(up, "cargo_lock_sha256", CARGO_LOCK, revision)
    lock["cargo_lock_sha256"] = {
        "value": hashlib.sha256(cargo_lock).hexdigest(),
        "source": [git_source(CARGO_LOCK, revision)],
    }
    lock.update(resolve_bazel_sdk(up, version, lock["integration_revision"]["value"]))
    lock.update(resolve_product_bundle(up, version))
    lock.update(resolve_fidlgen_rust_next(up, version))
    return lock


def render(lock: dict) -> bytes:
    return (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode()


def write_atomically(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory, then os.replace; never partial.

    The new file keeps an existing lock's permission bits, else 0644 (mkstemp's 0600
    would make a committed lock unreadable to others). The directory is fsynced after
    the rename so the replacement itself survives a crash.
    """
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fchmod(f.fileno(), mode)
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def main(argv: list[str] | None = None, upstream: Upstream | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sdk_version", help="e.g. 33.20260927.4.1")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="lock file (default: repo root overlay.lock.json)")
    args = parser.parse_args(argv)
    live = LiveUpstream() if upstream is None else None
    try:
        lock = resolve(upstream or live, args.sdk_version)
    except ResolveError as e:
        print(f"resolve_pins: error: {e}", file=sys.stderr)
        print(f"resolve_pins: {args.out} left unchanged", file=sys.stderr)
        return 1
    finally:
        if live is not None:
            live.close()
    write_atomically(args.out, render(lock))
    print(f"resolve_pins: wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
