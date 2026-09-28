#!/bin/bash
# SPDX-FileCopyrightText: 2026 Curtis Galloway
# SPDX-License-Identifier: Apache-2.0
#
# The test fuchsia_driver_elf_test runs (//rules:fuchsia_rust_driver.bzl; design R7,
# milestone M10). Arguments: llvm-readelf, the package's resource list (lines
# "<dest>=<runfiles path>"), the driver's dest (driver/<name>.so), the expected exported
# symbols, the allowed DT_NEEDED set and the system libraries (each space-separated).
set -euo pipefail
readelf="$1"; resources="$2"; driver="$3"; exported="$4"; allowed="$5"; system="$6"

src_of() { awk -F= -v d="$1" '$1 == d { print $2 }' "$resources"; }
needed_of() { "$readelf" --dynamic --wide "$1" | sed -n 's/.*(NEEDED).*\[\(.*\)\].*/\1/p' | sort; }
has() { case " $1 " in *" $2 "*) return 0 ;; *) return 1 ;; esac; }

src="$(src_of "$driver")"
if [[ -z "$src" ]]; then
  echo "FAIL: the package has no $driver" >&2
  exit 1
fi
status=0

# 1. The defined, non-local dynamic symbols are exactly the expected set (design F3).
got="$("$readelf" --dyn-syms --wide "$src" \
  | awk '$1 ~ /^[0-9]+:$/ && $7 != "UND" && $5 != "LOCAL" { print $8 }' | sort -u)"
got="$(echo $got)"
if [[ "$got" != "$exported" ]]; then
  echo "FAIL: $driver exports [$got], expected [$exported]" >&2
  status=1
else
  echo "ok: $driver exports only [$exported]"
fi

# 2. Its soname is its file name, as GN's drivers have.
soname="$("$readelf" --dynamic --wide "$src" | sed -n 's/.*(SONAME).*\[\(.*\)\].*/\1/p')"
if [[ "$soname" != "${driver##*/}" ]]; then
  echo "FAIL: $driver has soname [$soname], expected [${driver##*/}]" >&2
  status=1
else
  echo "ok: $driver has soname $soname"
fi

# 3. The driver's DT_NEEDED set is within the allowed set (the reference driver's).
needed="$(needed_of "$src")" || { echo "FAIL: llvm-readelf could not read $driver" >&2; exit 1; }
needed="$(echo $needed)"
echo "$driver DT_NEEDED: [$needed]"
for lib in $needed; do
  if ! has "$allowed" "$lib"; then
    echo "FAIL: $driver needs $lib, not in the allowed set [$allowed]" >&2
    status=1
  fi
done

# 4. Every ELF file in the package (the driver and lib/) finds each library it needs in
# the package's lib/ or among the system libraries, so the loader can resolve them all.
checked=0
while IFS='=' read -r dest path; do
  case "$dest" in driver/*.so | lib/*) ;; *) continue ;; esac
  if ! libs="$(needed_of "$path")"; then
    echo "FAIL: llvm-readelf could not read $dest ($path)" >&2
    status=1
    continue
  fi
  checked=$((checked + 1))
  for lib in $libs; do
    if ! has "$system" "$lib" && [[ -z "$(src_of "lib/$lib")" ]]; then
      echo "FAIL: $dest needs $lib, which is neither at lib/$lib nor a system library" >&2
      status=1
    fi
  done
done < "$resources"
if [[ $checked -lt 2 ]]; then
  echo "FAIL: read $checked ELF files; expected the driver and its lib/ files" >&2
  status=1
elif [[ $status == 0 ]]; then
  echo "ok: every library the $checked ELF files need is packaged or a system library [$system]"
fi
exit $status
