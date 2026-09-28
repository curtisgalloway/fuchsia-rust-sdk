# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0

"""Reads overlay.lock.json, the only per-release input (design R1), for module extensions.

Everything a build fetches for a release is named here by content hash: CIPD instances
by their SHA-256 instance digest, the IDK tarball by its SHA-256. A digest that does not
match what the server returns fails the fetch; nothing is re-resolved by tag.
"""

LOCK = Label("//:overlay.lock.json")

_HEX = "0123456789abcdef"
_B64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

# CIPD's /dl/ endpoint redirects to the instance's blob in Google Storage.
_CIPD_DL = "https://chrome-infra-packages.appspot.com/dl/{package}/+/{instance_id}"

def read_lock(module_ctx):
    """Returns the decoded lock. Reading it makes the extension re-run when it changes."""
    return json.decode(module_ctx.read(LOCK))

def _sha256(field, value):
    if type(value) != "string" or len(value) != 64 or [c for c in value.elems() if c not in _HEX.elems()]:
        fail("overlay.lock.json: %s: value %r is not a lowercase hex SHA-256" % (field, value))
    return value

def lock_field(lock, field):
    """Returns lock[field] after checking it has a SHA-256 "value"."""
    entry = lock.get(field)
    if type(entry) != "dict":
        fail("overlay.lock.json: missing field %r" % field)
    _sha256(field, entry.get("value"))
    return entry

def cipd_instance_id(field, hexdigest):
    """The instance ID CIPD accepts for a SHA-256 digest.

    It is the unpadded base64url of the 32 digest bytes followed by the hash-algorithm
    byte (2 = SHA-256), so it names exactly one package zip: the one with that digest.
    """
    hexdigest = _sha256(field, hexdigest)
    data = [int(hexdigest[i:i + 2], 16) for i in range(0, 64, 2)] + [2]
    out = []
    for i in range(0, len(data), 3):
        n = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
        for shift in (18, 12, 6, 0):
            out.append(_B64URL[(n >> shift) & 63])
    return "".join(out)

def cipd_package(lock, field):
    """Returns struct(package, sha256, url) for a CIPD lock field."""
    entry = lock_field(lock, field)
    package = entry.get("package")
    if type(package) != "string" or not package:
        fail("overlay.lock.json: %s: no CIPD package" % field)
    return struct(
        package = package,
        sha256 = entry["value"],
        url = _CIPD_DL.format(package = package, instance_id = cipd_instance_id(field, entry["value"])),
    )
