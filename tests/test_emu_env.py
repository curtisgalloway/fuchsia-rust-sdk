# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/emu_env.py: paths, KVM/TCG choice, IPv6, ssh and the host preflight."""

from __future__ import annotations

import errno
import http.server
import os
import threading
from pathlib import Path

import pytest

import emu_env as ee
import overlay_profile as op

# --- paths ------------------------------------------------------------------------------


def test_state_dir_precedence(tmp_path):
    assert ee.state_dir({"HOME": "/h"}) == Path("/h/.local/state/fuchsia-rust-sdk")
    assert ee.state_dir({"HOME": "/h", "XDG_STATE_HOME": "/x"}) == Path("/x/fuchsia-rust-sdk")
    env = {"HOME": "/h", "XDG_STATE_HOME": "/x", "OVERLAY_STATE_DIR": "/s"}
    assert ee.state_dir(env) == Path("/s")


def test_emulator_dir_defaults_inside_state_dir():
    assert ee.emulator_dir({"OVERLAY_STATE_DIR": "/s"}) == Path("/s/emulator")
    assert ee.emulator_dir({"OVERLAY_STATE_DIR": "/s", "OVERLAY_EMULATOR_DIR": "/e"}) == Path("/e")


def test_resolve_paths_layout():
    p = ee.resolve_paths({"OVERLAY_EMULATOR_DIR": "/e"})
    assert p.ffx_isolate == Path("/e/ffx")
    assert p.repo == Path("/e/repo")
    assert p.product_bundle("core.x64", "1.2.3.4") == Path("/e/pb/core.x64-1.2.3.4")
    p = ee.resolve_paths({"OVERLAY_EMULATOR_DIR": "/e", "OVERLAY_FFX_ISOLATE_DIR": "/f"})
    assert p.ffx_isolate == Path("/f")


def test_resolve_paths_rejects_relative():
    with pytest.raises(ee.EnvError, match="absolute"):
        ee.resolve_paths({"OVERLAY_EMULATOR_DIR": "rel/emu"})
    with pytest.raises(ee.EnvError, match="absolute"):
        ee.resolve_paths({"OVERLAY_EMULATOR_DIR": "/e", "OVERLAY_FFX_ISOLATE_DIR": "ffx"})


def test_socket_room():
    ee.check_socket_room(Path("/home/u/.local/state/fuchsia-rust-sdk/emulator/ffx"), "fuchsia-emu")
    long = Path("/" + "d" * 80)
    with pytest.raises(ee.EnvError, match="OVERLAY_FFX_ISOLATE_DIR"):
        ee.check_socket_room(long, "fuchsia-emu")


def test_socket_room_boundary():
    suffix = "/" + ee.SOCKET_SUFFIX_TEMPLATE.format(name="n")
    ok = Path("/" + "a" * (ee.UNIX_PATH_MAX - 2 - len(suffix)))  # total 107 bytes
    ee.check_socket_room(ok, "n")
    with pytest.raises(ee.EnvError):
        ee.check_socket_room(Path(str(ok) + "a"), "n")  # 108 bytes


# --- acceleration -----------------------------------------------------------------------


def test_kvm_missing(tmp_path):
    usable, why = ee.kvm_usable(str(tmp_path / "kvm"))
    assert not usable and "does not exist" in why


def test_kvm_not_a_char_device(tmp_path):
    f = tmp_path / "kvm"
    f.write_text("")
    usable, why = ee.kvm_usable(str(f))
    assert not usable and "not a character device" in why


def test_kvm_char_device_opens():
    # /dev/null is a character device anyone can open read-write, as QEMU opens /dev/kvm.
    usable, why = ee.kvm_usable("/dev/null")
    assert usable and "read-write" in why


def test_kvm_permission_denied():
    def deny(path, flags):
        raise PermissionError(errno.EACCES, "Permission denied")

    usable, why = ee.kvm_usable("/dev/null", opener=deny)
    assert not usable and "kvm group" in why


def test_kvm_open_passes_read_write():
    seen = []

    def opener(path, flags):
        seen.append(flags & os.O_ACCMODE)
        return os.open(os.devnull, os.O_RDONLY)

    assert ee.kvm_usable("/dev/null", opener=opener)[0]
    assert seen == [os.O_RDWR]


@pytest.mark.parametrize("requested,usable,expected", [
    ("auto", True, "kvm"),
    ("auto", False, "tcg"),
    ("tcg", True, "tcg"),
    ("tcg", False, "tcg"),
    ("kvm", True, "kvm"),
])
def test_choose_accel(requested, usable, expected):
    accel, why = ee.choose_accel(requested, (usable, "because"))
    assert accel == expected and why


def test_choose_accel_auto_without_kvm_says_why():
    assert ee.choose_accel("auto", (False, "/dev/kvm does not exist")) == (
        "tcg", "no KVM: /dev/kvm does not exist")


def test_choose_accel_kvm_required_but_missing():
    with pytest.raises(ee.EnvError, match="KVM requested but not usable: nope"):
        ee.choose_accel("kvm", (False, "nope"))


def test_choose_accel_rejects_unknown():
    with pytest.raises(ee.EnvError, match="expected one of"):
        ee.choose_accel("hvf", (True, ""))


def test_requested_accel_env_overrides_profile():
    assert ee.requested_accel({}, "auto") == "auto"
    assert ee.requested_accel({"OVERLAY_EMU_ACCEL": "tcg"}, "auto") == "tcg"


def test_every_profile_accel_is_valid():
    for profile in op.PROFILES.values():
        assert profile.emulator_accel in ee.ACCEL_CHOICES


def test_hosted_profile_uses_tcg_without_flags_when_no_kvm(tmp_path):
    # Acceptance: with KVM unavailable (the hosted profile), TCG is chosen with no flags.
    hosted = op.PROFILES["hosted"]
    requested = ee.requested_accel({}, hosted.emulator_accel)
    accel, _ = ee.choose_accel(requested, ee.kvm_usable(str(tmp_path / "no-kvm")))
    assert accel == "tcg" and ee.ffx_accel_flag(accel) == "none"


def test_hosted_profile_uses_kvm_when_usable():
    requested = ee.requested_accel({}, op.PROFILES["hosted"].emulator_accel)
    accel, _ = ee.choose_accel(requested, ee.kvm_usable("/dev/null"))
    assert accel == "kvm" and ee.ffx_accel_flag(accel) == "hyper"


# --- IPv6 and ssh -----------------------------------------------------------------------


def test_package_server_address():
    assert ee.package_server_address(True) is None
    assert ee.package_server_address(False) == "127.0.0.1:8083"


def test_ipv6_loopback_is_bool():
    assert isinstance(ee.ipv6_loopback(), bool)


def test_ssh_present():
    plan = ee.ssh_plan(which=lambda n: "/usr/bin/ssh" if n == "ssh" else None, euid=1000)
    assert plan.action == "present"


def test_ssh_missing_root_with_apt_installs():
    plan = ee.ssh_plan(which=lambda n: "/usr/bin/apt-get" if n == "apt-get" else None, euid=0)
    assert plan.action == "apt-install" and "openssh-client" in plan.detail


def test_ssh_missing_not_root_stops():
    plan = ee.ssh_plan(which=lambda n: "/usr/bin/apt-get" if n == "apt-get" else None, euid=1000)
    assert plan.action == "missing" and "openssh-client" in plan.detail


def test_ssh_missing_root_without_apt_stops():
    assert ee.ssh_plan(which=lambda n: None, euid=0).action == "missing"


# --- host contract ----------------------------------------------------------------------


def names(hosts):
    return {h.name for h in hosts}


def test_hosts_needed_nothing_to_fetch():
    assert ee.hosts_needed(need_bazel=False, need_product_bundle=False) == []


def test_hosts_needed_product_bundle_only():
    assert names(ee.hosts_needed(need_bazel=False, need_product_bundle=True)) == {
        "storage.googleapis.com"}


def test_hosts_needed_bazel_includes_gcs():
    got = names(ee.hosts_needed(need_bazel=True, need_product_bundle=False))
    assert got == {"storage.googleapis.com", "chrome-infra-packages.appspot.com", "github.com",
                   "release-assets.githubusercontent.com", "bcr.bazel.build"}


def test_no_host_is_distribution_specific():
    # apt's mirrors depend on the host's configuration; the preflight does not guess them.
    assert all(h.probe.startswith("https://") and "ubuntu" not in h.name for h in ee.HOSTS)


def test_preflight_names_the_blocked_host():
    hosts = ee.hosts_needed(need_bazel=True, need_product_bundle=True)
    blocked = ee.preflight(hosts, fetch=lambda url: "403" if "github.com/" in url else None)
    assert [h.name for h, _ in blocked] == ["github.com"]
    msg = ee.describe_blocked(blocked)
    assert "github.com" in msg and "403" in msg and "scripts/emu setup" in msg


def test_preflight_all_reachable():
    assert ee.preflight(ee.HOSTS, fetch=lambda url: None) == []


@pytest.fixture
def http_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(403 if self.path == "/deny" else 200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_probe_plain_http(http_server, monkeypatch):
    for var in ("http_proxy", "HTTP_PROXY"):
        monkeypatch.delenv(var, raising=False)
    assert ee.probe(f"{http_server}/ok") is None
    assert "HTTP 403" in ee.probe(f"{http_server}/deny")


def test_probe_unreachable():
    # Port 9 (discard) on loopback: nothing listens there in a test environment.
    err = ee.probe("http://127.0.0.1:9/", timeout=5)
    assert err is not None
