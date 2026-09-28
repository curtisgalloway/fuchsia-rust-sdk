# Copyright 2026 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file (in this repository: LICENSES/BSD-3-Clause.txt).
#
# SPDX-FileCopyrightText: 2026 The Fuchsia Authors
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: BSD-3-Clause
"""scripts/emu: run the lock's release of core.x64 in QEMU and put packages on it.

    scripts/emu setup            fetch the IDK (ffx, QEMU) and the lock's core.x64 bundle
    scripts/emu start | stop     boot / stop the emulator (KVM if usable, else TCG)
    scripts/emu check            the running target's version must equal the lock's
    scripts/emu run //pkg:target   build, publish and `ffx component run` its component
    scripts/emu driver //pkg:target  build, publish and `ffx driver register` its driver
    scripts/emu log [FILTER]     dump target logs
    scripts/emu ffx ARGS...      the IDK's ffx, pointed at the harness's isolate dir
    scripts/emu env              print the detected environment and paths

Ported from `dev` in github.com/curtisgalloway/fuchsia-cloud-dev (commit 5c6e5c1,
BSD-style, The Fuchsia Authors), rewritten in Python. Changes from `dev`:

- every per-release input comes from overlay.lock.json (design C3): ffx and QEMU from
  the lock's IDK (`tools/x64/ffx`, `tools/x64/qemu_internal`, which the release pins in
  fuchsia.git `manifests/prebuilts`), the product bundle from the lock's `sdk_version`;
- the host is detected, not assumed (`emu_env.py`): KVM or TCG, IPv6, ssh, and the
  network hosts setup needs; state lives in configurable directories;
- packages build with `--config=fuchsia_x64` through `scripts/bazel`.

The container workarounds from `dev` (fuchsia-cloud-dev README, "Container workarounds")
are marked `Workaround N` below; the root-user one (4) is in MODULE.bazel.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import emu_env
import overlay_profile

ROOT = Path(__file__).resolve().parent.parent
BAZEL = ROOT / "scripts" / "bazel"
LOCK = ROOT / "overlay.lock.json"
PRODUCT = "core.x64"
EMU_NAME = "fuchsia-emu"
REPO_NAME = "devhost"
# @fuchsia_idk's directory in Bazel's output base (the lock_repos extension's canonical name).
IDK_REPO = "+lock_repos+fuchsia_idk"
TARGET_CONFIG = "--config=fuchsia_x64"
# Extra QEMU devices. `edu` (PCI 1234:11e8) is the bind target I3 and M11 use; it is
# inert for everything else.
DEV_CONFIG = {"args": ["-device", "edu"], "kernel_args": [], "env": {}}
STARTUP_TIMEOUT = {"kvm": 300, "tcg": 580}  # seconds; TCG boots in about a minute


class EmuError(Exception):
    pass


def log(msg: str) -> None:
    print(f"emu: {msg}", file=sys.stderr, flush=True)


# --- the lock ---------------------------------------------------------------------------


def read_lock(path: Path = LOCK) -> dict:
    return json.loads(path.read_text())


def lock_version(lock: dict) -> str:
    version = lock["sdk_version"]["value"]
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)+", version):
        raise EmuError(f"overlay.lock.json: sdk_version {version!r} is not a version")
    return version


def product_bundles_url(lock: dict) -> str:
    """The lock's own source for sdk_version: the release's product_bundles.json."""
    version = lock_version(lock)
    url = f"https://storage.googleapis.com/fuchsia/development/{version}/product_bundles.json"
    if url not in lock["sdk_version"].get("source", []):
        raise EmuError(f"overlay.lock.json: sdk_version source does not list {url}")
    return url


def transfer_manifest_url(bundles: list, product: str, version: str) -> str:
    """The transfer manifest of `product` at `version` in a product_bundles.json."""
    matches = [b for b in bundles if isinstance(b, dict) and b.get("name") == product]
    if len(matches) != 1:
        raise EmuError(f"product_bundles.json lists {len(matches)} entries named {product}")
    entry = matches[0]
    if entry.get("product_version") != version:
        raise EmuError(f"{product} in product_bundles.json has version "
                       f"{entry.get('product_version')!r}, the lock has {version}")
    url = entry.get("transfer_manifest_url", "")
    if not url.startswith("gs://") or not url.endswith("/transfer.json"):
        raise EmuError(f"{product}: unexpected transfer manifest URL {url!r}")
    return url


def check_bundle_version(pb_dir: Path, product: str, version: str) -> None:
    """A downloaded bundle must name the lock's release as both product and SDK version."""
    meta = json.loads((pb_dir / "product_bundle.json").read_text())
    got = (meta.get("product_name"), meta.get("product_version"), meta.get("sdk_version"))
    if got != (product, version, version):
        raise EmuError(f"{pb_dir}: product_bundle.json says {got}, expected "
                       f"({product!r}, {version!r}, {version!r})")


def hash_tree(root: Path) -> dict[str, str]:
    """SHA-256 of every file under `root`, by relative path (a record, not a pin)."""
    out = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
        h = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        out[path.relative_to(root).as_posix()] = h.hexdigest()
    return out


# --- tools ------------------------------------------------------------------------------


def bazel(*args: str, capture: bool = False) -> str:
    proc = subprocess.run([str(BAZEL), *args], cwd=ROOT, text=True,
                          stdout=subprocess.PIPE if capture else None)
    if proc.returncode != 0:
        raise EmuError(f"scripts/bazel {' '.join(args)} failed (exit {proc.returncode})")
    return proc.stdout if capture else ""


def idk_dir() -> Path:
    base = bazel("info", "output_base", capture=True).strip()
    return Path(base) / "external" / IDK_REPO


class Harness:
    def __init__(self, env: dict[str, str] | None = None):
        self.env = dict(os.environ if env is None else env)
        self.paths = emu_env.resolve_paths(self.env)
        self.profile, _ = overlay_profile.resolve(self.env)
        self.lock = read_lock()
        self.version = lock_version(self.lock)
        self._idk: Path | None = None

    # ffx always runs from the lock's IDK with the harness's isolate dir. Workaround 2:
    # QEMU refuses unix socket paths of 108 bytes or more, and ffx puts its QMP socket
    # inside the isolate dir, so that dir must be short (checked in setup and start).
    @property
    def idk(self) -> Path:
        if self._idk is None:
            self._idk = idk_dir()
        return self._idk

    def ffx_cmd(self, *args: str) -> list[str]:
        return [str(self.idk / "tools" / "x64" / "ffx"), "--isolate-dir", str(self.paths.ffx_isolate), *args]

    def ffx(self, *args: str, capture: bool = False, check: bool = True, cwd: Path | None = None,
            quiet: bool = False) -> subprocess.CompletedProcess:
        out = subprocess.PIPE if capture else (subprocess.DEVNULL if quiet else None)
        proc = subprocess.run(self.ffx_cmd(*args), text=True, stdout=out,
                              stderr=subprocess.PIPE if capture else None, cwd=cwd)
        if check and proc.returncode != 0:
            detail = f":\n{proc.stderr.strip()}" if capture and proc.stderr else ""
            raise EmuError(f"ffx {' '.join(args)} failed (exit {proc.returncode}){detail}")
        return proc

    @property
    def pb_dir(self) -> Path:
        return self.paths.product_bundle(PRODUCT, self.version)

    # --- setup ------------------------------------------------------------------------

    def setup(self) -> None:
        emu = self.paths.emulator
        emu.mkdir(parents=True, exist_ok=True)
        emu_env.check_socket_room(self.paths.ffx_isolate, EMU_NAME)
        with open(self.paths.setup_lock, "w") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            self._write_status("running")
            try:
                self._setup()
            except BaseException:
                self._write_status("failed")
                raise
            self._write_status("ok")

    def _write_status(self, state: str) -> None:
        self.paths.setup_status.write_text(json.dumps(
            {"state": state, "sdk_version": self.version, "product": PRODUCT}) + "\n")

    def _setup(self) -> None:
        ssh = emu_env.ssh_plan()
        base = bazel("info", "output_base", capture=True).strip()
        need_bazel = not (Path(base) / "external" / IDK_REPO / "tools" / "x64" / "ffx").exists()
        need_pb = not (self.pb_dir / "product_bundle.json").exists()
        hosts = emu_env.hosts_needed(need_bazel=need_bazel, need_product_bundle=need_pb,
                                     need_apt=ssh.action == "apt-install")
        blocked = emu_env.preflight(hosts)
        if blocked:
            raise EmuError(emu_env.describe_blocked(blocked))

        # Workaround 1: ffx reaches the target over ssh; containers may lack a client.
        if ssh.action == "missing":
            raise EmuError(ssh.detail)
        if ssh.action == "apt-install":
            log(ssh.detail)
            install = ["apt-get", "install", "-y", "-q", "openssh-client"]
            quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            # A stale package index makes the first try fail; update it and retry once.
            if subprocess.run(install, **quiet).returncode != 0:
                for cmd in (["apt-get", "update", "-q"], install):
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    if proc.returncode != 0:
                        raise EmuError(f"{' '.join(cmd)} failed:\n{proc.stderr.strip()}")

        if need_bazel:
            log("fetching the lock's IDK through Bazel (first time: about 3 GB, a few minutes)")
        bazel("fetch", "--repo=@fuchsia_idk")
        ffx_bin = self.idk / "tools" / "x64" / "ffx"
        qemu = self.idk / "tools" / "x64" / "qemu_internal"
        for path in (ffx_bin, qemu / "bin" / "qemu-system-x86_64", qemu / ".versions" / "qemu.cipd_version"):
            if not path.exists():
                raise EmuError(f"the lock's IDK has no {path.relative_to(self.idk)}")
        sdk_id = json.loads((self.idk / "meta" / "manifest.json").read_text())["id"]
        if sdk_id != self.version:
            raise EmuError(f"IDK {self.idk} is {sdk_id}, the lock says {self.version}")
        # No usage analytics from an automated harness; this also silences the notice.
        self.ffx("config", "analytics", "disable", quiet=True, check=False)
        self.ffx("config", "set", "sdk.root", str(self.idk), quiet=True)
        self.ffx("config", "set", "emu.qemu.internal_path", str(qemu), quiet=True)

        if need_pb:
            self._download_bundle()
        check_bundle_version(self.pb_dir, PRODUCT, self.version)
        if not (self.paths.repo / "repository").is_dir():
            self.ffx("repository", "create", str(self.paths.repo), quiet=True)
        log(f"setup done: ffx, QEMU and {PRODUCT} at {self.version} ({self.pb_dir})")

    def _download_bundle(self) -> None:
        index_url = product_bundles_url(self.lock)
        with urllib.request.urlopen(index_url, timeout=120) as r:
            bundles = json.loads(r.read())
        manifest = transfer_manifest_url(bundles, PRODUCT, self.version)
        partial = self.pb_dir.with_name(self.pb_dir.name + ".partial")
        if partial.exists():
            subprocess.run(["rm", "-rf", str(partial)], check=True)
        partial.parent.mkdir(parents=True, exist_ok=True)
        log(f"downloading {PRODUCT} {self.version} from {manifest}")
        self.ffx("product", "download", "--auth", "no-auth", manifest, str(partial), quiet=True)
        check_bundle_version(partial, PRODUCT, self.version)
        # Nothing upstream pins the bundle's files by hash (only package blobs are
        # content-addressed), so record what was downloaded for later comparison.
        record = {"transfer_manifest": manifest, "product_bundles": index_url, "sha256": hash_tree(partial)}
        (partial.parent / f"{partial.name.removesuffix('.partial')}.sha256.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n")
        partial.rename(self.pb_dir)

    def require_setup(self) -> None:
        try:
            status = json.loads(self.paths.setup_status.read_text())
        except (FileNotFoundError, ValueError):
            raise EmuError("run scripts/emu setup first") from None
        if status.get("state") == "running":
            log("waiting for scripts/emu setup to finish")
            with open(self.paths.setup_lock) as lockf:
                fcntl.flock(lockf, fcntl.LOCK_SH)
            status = json.loads(self.paths.setup_status.read_text())
        if status.get("state") != "ok" or status.get("sdk_version") != self.version:
            raise EmuError(f"setup is {status.get('state')} for {status.get('sdk_version')}; "
                           f"the lock is {self.version}: run scripts/emu setup")

    # --- emulator ---------------------------------------------------------------------

    def running(self) -> bool:
        proc = self.ffx("emu", "list", capture=True, check=False)
        return proc.returncode == 0 and EMU_NAME in proc.stdout

    def accel(self) -> tuple[str, str]:
        requested = emu_env.requested_accel(self.env, self.profile.emulator_accel)
        return emu_env.choose_accel(requested, emu_env.kvm_usable())

    def start(self) -> None:
        self.require_setup()
        emu_env.check_socket_room(self.paths.ffx_isolate, EMU_NAME)
        if self.running():
            log("emulator already running")
        else:
            accel, why = self.accel()
            devcfg = self.paths.emulator / "emu-dev-config.json"
            devcfg.write_text(json.dumps(DEV_CONFIG) + "\n")
            smp = str(min(4, os.cpu_count() or 1))
            log(f"booting {PRODUCT} {self.version} with {accel.upper()} ({why}), {smp} vCPU")
            t0 = time.monotonic()
            self.ffx("emu", "start", str(self.pb_dir), "--name", EMU_NAME, "--engine", "qemu",
                     "--accel", emu_env.ffx_accel_flag(accel), "--headless", "--net", "user",
                     "--smp", smp, "--startup-timeout", str(STARTUP_TIMEOUT[accel]),
                     "--dev-config", str(devcfg))
            log(f"emulator up in {time.monotonic() - t0:.0f} s")
        self.serve()

    def serve(self) -> None:
        # Workaround 3: without IPv6, ffx's default package-server address [::] fails.
        address = emu_env.package_server_address(emu_env.ipv6_loopback())
        self.ffx("repository", "server", "stop", "--all", check=False, quiet=True, capture=True)
        args = ["repository", "server", "start", "--background", "--repo-path", str(self.paths.repo),
                "-r", REPO_NAME]
        if address:
            args += ["--address", address]
        self.ffx(*args, quiet=True)

    def stop(self) -> None:
        self.ffx("repository", "server", "stop", "--all", check=False, quiet=True, capture=True)
        if self.running():
            self.ffx("emu", "stop", EMU_NAME)
        else:
            log("emulator not running")

    def target_version(self) -> str:
        proc = self.ffx("--machine", "json", "target", "show", capture=True)
        return find_version(json.loads(proc.stdout))

    def check(self) -> None:
        got = self.target_version()
        print(f"target {EMU_NAME}: {PRODUCT} {got}; lock sdk_version {self.version}")
        if got != self.version:
            raise EmuError(f"the target runs {got}, the lock is {self.version} (design C3)")

    # --- packages ---------------------------------------------------------------------

    def build_and_publish(self, target: str) -> tuple[str, list[str]]:
        """Builds a fuchsia_package target and publishes it; returns (name, component manifests)."""
        if not self.running():
            raise EmuError("emulator not running; run scripts/emu start")
        bazel("build", TARGET_CONFIG, target)
        execroot = Path(bazel("info", "execution_root", capture=True).strip())
        files = bazel("cquery", TARGET_CONFIG, "--output=files", target, capture=True).split()
        manifests = [f for f in files if f.endswith("/package_manifest.json")]
        if not manifests:
            raise EmuError(f"{target} is not a fuchsia_package")
        manifest = manifests[0]
        # Workaround 5: package manifests hold paths relative to the execution root.
        self.ffx("repository", "publish", "--package", manifest, str(self.paths.repo), cwd=execroot, quiet=True)
        pkg = json.loads((execroot / manifest).read_text())
        name = pkg["package"]["name"]
        meta = (execroot / manifest).parent / "manifest"
        components = [line.split("=", 1)[0] for line in meta.read_text().splitlines()
                      if re.match(r"meta/[^=]+\.cm=", line)] if meta.exists() else []
        if not components:
            components = [b["path"] for b in pkg.get("blobs", []) if re.fullmatch(r"meta/[^/]+\.cm", b.get("path", ""))]
        return name, components

    def run(self, target: str, component: str | None = None) -> None:
        name, components = self.build_and_publish(target)
        cm = component or (components[0] if components else None)
        if cm is None:
            raise EmuError(f"{target}: no component manifest in the package")
        self.ffx("component", "run", "--recreate", f"/core/ffx-laboratory:{name}",
                 f"fuchsia-pkg://{REPO_NAME}/{name}#{cm}")

    def driver(self, target: str) -> None:
        name, components = self.build_and_publish(target)
        if not components:
            raise EmuError(f"{target}: no component manifest in the package")
        url = f"fuchsia-pkg://{REPO_NAME}/{name}#{components[0]}"
        # Workaround 6: the driver index keeps the first registration of a URL until reboot.
        listed = self.ffx("driver", "list", capture=True, check=False).stdout or ""
        if url in listed:
            log(f"{url} already registered; rebooting the target to load the new build")
            self.ffx("target", "reboot", quiet=True)
            self.ffx("target", "wait", "--timeout", "300", quiet=True, check=False)
            self.serve()
        self.ffx("driver", "register", url)

    def log_dump(self, filt: str | None) -> None:
        args = ["log"] + (["--filter", filt] if filt else []) + ["dump"]
        self.ffx(*args)

    def describe(self) -> str:
        kvm = emu_env.kvm_usable()
        try:
            accel = "%s (%s)" % self.accel()
        except emu_env.EnvError as e:
            accel = f"error: {e}"
        ipv6 = emu_env.ipv6_loopback()
        rows = [
            ("profile", f"{self.profile.name} (emulator_accel={self.profile.emulator_accel})"),
            ("lock sdk_version", self.version),
            ("state dir", str(self.paths.state)),
            ("emulator dir", str(self.paths.emulator)),
            ("ffx isolate dir", str(self.paths.ffx_isolate)),
            ("product bundle", str(self.pb_dir)),
            ("kvm", f"{'usable' if kvm[0] else 'not usable'}: {kvm[1]}"),
            ("acceleration", accel),
            ("ipv6 loopback", "yes" if ipv6 else "no"),
            ("package server", emu_env.package_server_address(ipv6) or "ffx default ([::]:8083)"),
            ("ssh", f"{emu_env.ssh_plan().action}: {emu_env.ssh_plan().detail}"),
            ("euid", str(os.geteuid())),
        ]
        return "\n".join(f"{k:<17} {v}" for k, v in rows)


def find_version(show: object) -> str:
    """The product version in `ffx --machine json target show` output.

    The JSON nests sections; the build section carries `product_version` (older ffx
    releases: a `version` entry labelled `version`). Searched recursively so a layout
    change fails with a clear error rather than a KeyError.
    """
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key in ("product_version", "version"):
                if isinstance(node.get(key), str) and re.fullmatch(r"[0-9]+(\.[0-9]+)+", node[key]):
                    found.append(node[key])
            if node.get("label") == "version" and isinstance(node.get("value"), str):
                found.append(node["value"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(show)
    versions = sorted(set(found))
    if len(versions) != 1:
        raise EmuError(f"ffx target show: expected one product version, found {versions}")
    return versions[0]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd, args = (argv[0], argv[1:]) if argv else ("help", [])
    if cmd in ("help", "-h", "--help"):
        print(__doc__.split("\n\n")[1])
        return 0
    try:
        h = Harness()
        if cmd == "setup":
            h.setup()
        elif cmd == "start":
            h.start()
        elif cmd == "stop":
            h.stop()
        elif cmd == "check":
            h.check()
        elif cmd == "run" and args:
            h.require_setup()
            h.run(args[0], args[1] if len(args) > 1 else None)
        elif cmd == "driver" and args:
            h.require_setup()
            h.driver(args[0])
        elif cmd == "log":
            h.log_dump(args[0] if args else None)
        elif cmd == "ffx":
            os.execv(h.ffx_cmd()[0], h.ffx_cmd(*args))
        elif cmd == "env":
            print(h.describe())
        else:
            print(f"emu: unknown command {shlex.join(argv)}; see scripts/emu help", file=sys.stderr)
            return 2
    except (EmuError, emu_env.EnvError, overlay_profile.ProfileError) as e:
        log(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
