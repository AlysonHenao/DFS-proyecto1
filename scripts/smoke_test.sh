#!/usr/bin/env sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root_dir"
source_file="$root_dir/smoke-input.txt"
destination_file="$root_dir/smoke-output.txt"
trap 'rm -f "$source_file" "$destination_file"' EXIT

printf '%s' 'DFSha integration smoke test' > "$source_file"
docker compose build control-leader client
docker compose up -d control-leader datanode1 datanode2
docker compose run --rm client mkdir /smoke
docker compose run --rm client ls /
docker compose run --rm client put /work/smoke-input.txt /smoke/input.txt
docker compose run --rm client get /smoke/input.txt /work/smoke-output.txt

source_hash=$(sha256sum "$source_file" | awk '{print $1}')
destination_hash=$(sha256sum "$destination_file" | awk '{print $1}')
test "$source_hash" = "$destination_hash"

docker compose run --rm client rm /smoke/input.txt
docker compose run --rm client rmdir /smoke
printf '%s\n' 'Smoke test passed: RF1 + RF2 + SHA-256'
