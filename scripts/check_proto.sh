#!/usr/bin/env sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if ! cmp -s "$root_dir/dfsha.proto" "$root_dir/client/dfsha.proto" ||
   ! cmp -s "$root_dir/dfsha.proto" "$root_dir/datanode/dfsha.proto"; then
  echo "dfsha.proto copies differ" >&2
  exit 1
fi
echo "All checked dfsha.proto copies are identical"
