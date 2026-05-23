#!/usr/bin/env bash
set -euo pipefail

image="${1:-agent-orchestrator:runtime-check}"

docker run --rm --entrypoint sh "$image" -c '
set -eu

root="${CACHE_CHECK_ROOT:-}"
cache_paths="
/var/cache/apt
/var/lib/apt/lists
/root/.cache
/home/ao/.cache
/tmp
/var/tmp
"

for cache_path in $cache_paths; do
  path="${root}${cache_path}"
  if [ -d "$path" ] && [ -n "$(find "$path" -mindepth 1 -print -quit)" ]; then
    echo "Runtime image contains cache files in $path" >&2
    find "$path" -mindepth 1 -maxdepth 2 -print >&2
    exit 1
  fi
done
'
