#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)

if env -u AUTH_PASSWORD -u AUTH_SECRET \
  docker compose \
    --project-directory "$app_dir" \
    --env-file /dev/null \
    -f "$app_dir/docker-compose.deploy.yml" \
    config -q >/dev/null 2>&1; then
  echo "Production Compose validation unexpectedly accepted missing secrets." >&2
  exit 1
fi

echo "Production Compose rejects missing authentication secrets."
