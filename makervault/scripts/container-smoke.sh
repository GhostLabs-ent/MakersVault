#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
project_name=${MAKERSVAULT_SMOKE_PROJECT:-makersvault-gate0-smoke}
api_port=${MAKERSVAULT_SMOKE_API_PORT:-18000}
web_port=${MAKERSVAULT_SMOKE_WEB_PORT:-15173}

cd "$app_dir"

compose() {
  API_PORT="$api_port" \
  WEB_PORT="$web_port" \
  VITE_API_URL="http://localhost:$api_port" \
    docker compose \
      --project-name "$project_name" \
      -f docker-compose.yml \
      -f docker-compose.smoke.yml \
      "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}

trap cleanup EXIT HUP INT TERM
cleanup
compose up --detach --build

attempt=1
while [ "$attempt" -le 60 ]; do
  if curl --fail --silent --show-error "http://localhost:$api_port/health" >/dev/null 2>&1 \
    && curl --fail --silent --show-error "http://localhost:$web_port/" >/dev/null 2>&1 \
    && curl --fail --silent --show-error "http://localhost:$web_port/runtime-config.js" >/dev/null 2>&1 \
    && curl --fail --silent --show-error "http://localhost:$web_port/api/health" >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 60 ]; then
    compose ps
    compose logs --no-color --tail=100
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 1
done

api_uid=$(compose exec -T api stat -c %u /proc/1)
web_uid=$(compose exec -T web stat -c %u /proc/1)
if [ "$api_uid" = "0" ] || [ "$web_uid" = "0" ]; then
  echo "Smoke test failed: application PID 1 must not run as root (API $api_uid, web $web_uid)" >&2
  exit 1
fi

expected_schema=$(sed -n 's/^ *Migration(\([0-9][0-9]*\),.*/\1/p' "$app_dir/api/migrations.py" | sort -n | tail -1)
if [ -z "$expected_schema" ]; then
  echo "Smoke test failed: could not determine expected schema version from api/migrations.py" >&2
  exit 1
fi
schema_output=$(compose exec -T api python -m migrations)
case "$schema_output" in
  *"schema version: $expected_schema"*) ;;
  *)
    echo "Smoke test failed: expected schema version $expected_schema, got: $schema_output" >&2
    exit 1
    ;;
esac

echo "Container smoke test passed (direct and same-origin API, API UID $api_uid, web UID $web_uid, schema $expected_schema)."
