# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""The emulator harness's view of the host: paths, detected capabilities, host contract.

`scripts/emu` (ported ffx flows, in `emu.py`) asks this module where its state lives and
what the host can do, so that the same harness runs in the hosted cloud container, on a
developer VM or on a lab machine (owner direction 2026-09-27; design C6). Everything is
detected or configured, never assumed:

- **Directories** (`resolve_paths`): `$OVERLAY_STATE_DIR` (default
  `$XDG_STATE_HOME/fuchsia-rust-sdk`, else `~/.local/state/fuchsia-rust-sdk`) holds
  `$OVERLAY_EMULATOR_DIR` (default `<state>/emulator`): product bundles, the package
  repository, the ffx isolate directory and the emulator's instance files. The ffx
  isolate directory can be moved with `$OVERLAY_FFX_ISOLATE_DIR`, since QEMU refuses unix
  socket paths of 108 bytes or more (`check_socket_room`).
- **Acceleration** (`choose_accel`): KVM when `/dev/kvm` opens read-write, TCG otherwise;
  `$OVERLAY_EMU_ACCEL` (`auto`, `kvm`, `tcg`) overrides the profile's `emulator_accel`.
- **IPv6** (`ipv6_loopback`): without it, the package server binds `127.0.0.1` (ffx's
  default `[::]` fails).
- **ssh** (`ssh_plan`): ffx reaches the target over ssh. When `ssh` is missing and the
  harness runs as root with `apt-get`, it installs `openssh-client` (from whatever
  mirrors the host's apt uses; apt's own error is reported if that fails); otherwise it
  stops and says what to install.
- **Network** (`HOSTS`, `preflight`): the hosts setup may contact, each with a probe URL;
  a blocked host fails setup with its name before any download starts.

Run `python3 scripts/emu.py env` to print what was detected.
"""

from __future__ import annotations

import errno
import os
import shutil
import socket
import stat
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

APP = "fuchsia-rust-sdk"
# QEMU (and Linux) limit a unix socket path to 107 bytes plus the terminating NUL.
UNIX_PATH_MAX = 108
# ffx puts each emulator instance's QMP/serial sockets at
# <isolate>/data/emu/instances/<name>/ (qmp, serial, monitor), as ffx does at this release
# (seen in M3); the longest name is the one to check.
SOCKET_SUFFIX_TEMPLATE = "data/emu/instances/{name}/monitor"  # also qmp, serial
ACCEL_CHOICES = ("auto", "kvm", "tcg")


class EnvError(Exception):
    """The host cannot run the harness as configured; the message says why and what to do."""


@dataclass(frozen=True)
class Paths:
    state: Path
    emulator: Path
    ffx_isolate: Path

    @property
    def product_bundles(self) -> Path:
        return self.emulator / "pb"

    @property
    def repo(self) -> Path:
        return self.emulator / "repo"

    @property
    def setup_lock(self) -> Path:
        return self.emulator / "setup.lock"

    @property
    def setup_status(self) -> Path:
        return self.emulator / "setup.json"

    def product_bundle(self, product: str, version: str) -> Path:
        return self.product_bundles / f"{product}-{version}"


def state_dir(env: Mapping[str, str]) -> Path:
    if env.get("OVERLAY_STATE_DIR"):
        return Path(env["OVERLAY_STATE_DIR"])
    if env.get("XDG_STATE_HOME"):
        return Path(env["XDG_STATE_HOME"]) / APP
    return Path(env.get("HOME", "/")) / ".local" / "state" / APP


def emulator_dir(env: Mapping[str, str]) -> Path:
    """`$OVERLAY_EMULATOR_DIR`, else `<state>/emulator`. `disk_report.py` counts it."""
    if env.get("OVERLAY_EMULATOR_DIR"):
        return Path(env["OVERLAY_EMULATOR_DIR"])
    return state_dir(env) / "emulator"


def resolve_paths(env: Mapping[str, str]) -> Paths:
    emu = emulator_dir(env)
    isolate = Path(env["OVERLAY_FFX_ISOLATE_DIR"]) if env.get("OVERLAY_FFX_ISOLATE_DIR") else emu / "ffx"
    for p in (emu, isolate):
        if not p.is_absolute():
            raise EnvError(f"{p}: emulator paths must be absolute")
    return Paths(state=state_dir(env), emulator=emu, ffx_isolate=isolate)


def check_socket_room(isolate: Path, instance_name: str) -> None:
    """Fails when the deepest socket ffx creates under `isolate` would be too long for QEMU."""
    sock = isolate / SOCKET_SUFFIX_TEMPLATE.format(name=instance_name)
    if len(os.fsencode(sock)) >= UNIX_PATH_MAX:
        raise EnvError(
            f"ffx isolate dir {isolate} is too long: QEMU's socket {sock} would be "
            f"{len(os.fsencode(sock))} bytes (limit {UNIX_PATH_MAX - 1}); set "
            "OVERLAY_FFX_ISOLATE_DIR (or OVERLAY_EMULATOR_DIR) to a shorter absolute path"
        )


# --- acceleration ----------------------------------------------------------------------


def kvm_usable(path: str = "/dev/kvm", opener: Callable[[str, int], int] = os.open) -> tuple[bool, str]:
    """Whether `path` is a character device this process can open read-write (as QEMU must)."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False, f"{path} does not exist"
    except OSError as e:
        return False, f"{path}: {e.strerror}"
    if not stat.S_ISCHR(st.st_mode):
        return False, f"{path} is not a character device"
    try:
        fd = opener(path, os.O_RDWR | os.O_CLOEXEC)
    except OSError as e:
        why = "permission denied (join the kvm group?)" if e.errno in (errno.EACCES, errno.EPERM) else e.strerror
        return False, f"{path}: {why}"
    os.close(fd)
    return True, f"{path} opens read-write"


def choose_accel(requested: str, kvm: tuple[bool, str]) -> tuple[str, str]:
    """Returns ("kvm" | "tcg", reason). `requested` is auto, kvm or tcg."""
    if requested not in ACCEL_CHOICES:
        raise EnvError(f"emulator acceleration {requested!r}: expected one of {', '.join(ACCEL_CHOICES)}")
    usable, why = kvm
    if requested == "tcg":
        return "tcg", "TCG requested"
    if requested == "kvm":
        if not usable:
            raise EnvError(f"KVM requested but not usable: {why}")
        return "kvm", why
    return ("kvm", why) if usable else ("tcg", f"no KVM: {why}")


def requested_accel(env: Mapping[str, str], profile_default: str) -> str:
    return env.get("OVERLAY_EMU_ACCEL") or profile_default


def ffx_accel_flag(accel: str) -> str:
    """`ffx emu start --accel` spells KVM `hyper` and TCG `none`."""
    return {"kvm": "hyper", "tcg": "none"}[accel]


# --- network and ssh -------------------------------------------------------------------


def ipv6_loopback() -> bool:
    """Whether this host can bind a socket on ::1 (containers without IPv6 cannot)."""
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
    except OSError:
        return False
    return True


def package_server_address(ipv6: bool, port: int = 8083) -> str | None:
    """The `ffx repository server start --address` to pass, or None for ffx's default ([::])."""
    return None if ipv6 else f"127.0.0.1:{port}"


@dataclass(frozen=True)
class SshPlan:
    action: str  # "present", "apt-install" or "missing"
    detail: str


def ssh_plan(which: Callable[[str], str | None] = shutil.which, euid: int | None = None) -> SshPlan:
    """What to do about the ssh client ffx needs: nothing, install it, or stop."""
    path = which("ssh")
    if path:
        return SshPlan("present", path)
    euid = os.geteuid() if euid is None else euid
    if euid == 0 and which("apt-get"):
        return SshPlan("apt-install", "no ssh client; installing openssh-client with apt-get (root)")
    return SshPlan(
        "missing",
        "no ssh client on PATH; ffx reaches the target over ssh. Install it "
        "(Debian/Ubuntu: openssh-client) and rerun setup",
    )


@dataclass(frozen=True)
class Host:
    name: str
    probe: str  # an HTTPS URL whose response (any HTTP status) proves the host is reachable
    purpose: str
    when: str  # "bazel" (fetching the SDK) or "product_bundle"


# The host contract (README "Emulator"). Bazel's hosts are needed only when the IDK is
# not yet in Bazel's output base. apt's mirrors are not probed: they depend on the
# host's apt configuration, and the ssh install reports apt's own error.
HOSTS: tuple[Host, ...] = (
    Host("storage.googleapis.com", "https://storage.googleapis.com/fuchsia/development/LATEST_LINUX",
         "the IDK (Bazel) and the product bundle (ffx)", "product_bundle"),
    Host("chrome-infra-packages.appspot.com", "https://chrome-infra-packages.appspot.com/",
         "CIPD: rules_fuchsia, clang and the Rust toolchain (Bazel)", "bazel"),
    Host("github.com", "https://github.com/", "Bazel itself and module archives", "bazel"),
    Host("release-assets.githubusercontent.com", "https://release-assets.githubusercontent.com/",
         "where github.com serves release downloads", "bazel"),
    Host("bcr.bazel.build", "https://bcr.bazel.build/", "Bazel Central Registry", "bazel"),
)


def hosts_needed(*, need_bazel: bool, need_product_bundle: bool) -> list[Host]:
    wanted = {"bazel": need_bazel, "product_bundle": need_product_bundle or need_bazel}
    return [h for h in HOSTS if wanted[h.when]]


def probe(url: str, timeout: float = 20) -> str | None:
    """None when the host is reachable; else the error text.

    Uses urllib, which honours HTTPS_PROXY/HTTP_PROXY/NO_PROXY and SSL_CERT_FILE like the
    tools setup runs. For HTTPS any HTTP status counts as reachable: a TLS session was
    established, and some hosts answer HEAD with 4xx. A proxy that refuses the host
    (CONNECT 403) is a failure. Plain HTTP goes through a proxy without a tunnel, so
    there an error status may come from the proxy itself: from 400 up counts as
    blocked. (Every host in HOSTS is HTTPS; tests use plain HTTP.)
    """
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": f"{APP}-emu/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return None
    except urllib.error.HTTPError as e:
        if url.startswith("https://") or e.code < 400:
            return None  # the host answered
        return f"HTTP {e.code} {e.reason} (from a proxy?)"
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        return f"{type(reason).__name__}: {reason}"


def preflight(hosts: Iterable[Host], fetch: Callable[[str], str | None] = probe) -> list[tuple[Host, str]]:
    """Every host that cannot be reached, with the error."""
    blocked = []
    for host in hosts:
        err = fetch(host.probe)
        if err is not None:
            blocked.append((host, err))
    return blocked


def describe_blocked(blocked: list[tuple[Host, str]]) -> str:
    lines = ["setup needs these hosts, which cannot be reached:"]
    lines += [f"  {h.name} ({h.purpose}): {err}" for h, err in blocked]
    lines.append("Allow them in the environment's network settings (README \"Emulator\"), "
                 "then rerun scripts/emu setup.")
    return "\n".join(lines)
