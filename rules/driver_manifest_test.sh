#!/bin/bash
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
#
# The test fuchsia_driver_manifest_test runs (//rules:fuchsia_rust_driver.bzl, milestone
# M10). Arguments: the compiled manifest (.cm) as packaged, the shards it must have been
# compiled with (paths such as syslog/client.shard.cml) and the protocols it must use
# (each space-separated). cmc records the manifest's source and include files in the .cm,
# so both are checked on the packaged file.
set -euo pipefail
cm="$1"; shards="$2"; protocols="$3"
status=0
for shard in $shards; do
  if grep -a -q -F "/$shard" "$cm"; then
    echo "ok: compiled with $shard"
  else
    echo "FAIL: $cm was not compiled with $shard" >&2
    status=1
  fi
done
for protocol in $protocols; do
  if grep -a -q -F "/svc/$protocol" "$cm"; then
    echo "ok: uses $protocol"
  else
    echo "FAIL: $cm does not use $protocol" >&2
    status=1
  fi
done
exit $status
