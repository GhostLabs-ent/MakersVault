#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)

# The compose project name allows only [a-z0-9_-] and must start with an
# alphanumeric, so normalise whatever MV_RUN_ID holds (Mf-ly4o).
run_id=$(printf '%s' "${MV_RUN_ID:-}" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9_-]/-/g')
project_name=${MAKERSVAULT_SMOKE_PROJECT:-makersvault-gate0-smoke${run_id:+-$run_id}}

# curl is the only guaranteed dependency. Exit code 7 is "connection refused",
# which means nothing is listening and the port is therefore free; anything
# else (including a response) counts as occupied.
port_free() {
  rc=0
  curl --silent --max-time 1 --output /dev/null "http://127.0.0.1:$1/" || rc=$?
  [ "$rc" -eq 7 ]
}

# Lane locks make the claim atomic: `compose up --build` needs minutes before
# it binds the ports, so probing alone would let two simultaneous runs pick the
# same lane. mkdir is atomic, and the pid inside lets a later run take over a
# lock left behind by a run that was killed (Mf-ly4o).
lock_root=${TMPDIR:-/tmp}/makersvault-smoke-lanes
claimed_lane=

claim_lane() {
  lane_lock="$lock_root/lane-$1"
  mkdir -p "$lock_root"
  if mkdir "$lane_lock" 2>/dev/null; then
    printf '%s\n' "$$" > "$lane_lock/pid"
    claimed_lane=$1
    return 0
  fi
  owner=$(cat "$lane_lock/pid" 2>/dev/null || true)
  if [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; then
    return 1
  fi
  # The holder is gone, so the lock is stale and this run may take it over.
  rm -rf "$lane_lock"
  if mkdir "$lane_lock" 2>/dev/null; then
    printf '%s\n' "$$" > "$lane_lock/pid"
    claimed_lane=$1
    return 0
  fi
  return 1
}

release_lane() {
  if [ -n "$claimed_lane" ]; then
    rm -rf "$lock_root/lane-$claimed_lane"
    claimed_lane=
  fi
}

lane=0
if [ -n "${MV_LANE:-}" ]; then
  lane=$MV_LANE
  case "$lane" in
    ''|*[!0-9]*)
      echo "MV_LANE must be a non-negative integer" >&2
      exit 2
      ;;
  esac
fi

api_port=${MAKERSVAULT_SMOKE_API_PORT:-}
web_port=${MAKERSVAULT_SMOKE_WEB_PORT:-}
used_lane=

if [ -n "$api_port" ] || [ -n "$web_port" ]; then
  # The documented overrides win and disable scanning. A missing partner port
  # falls back to this lane's base ports. No lock is taken: the operator owns
  # that port decision.
  api_port=${api_port:-$((18000 + lane * 10))}
  web_port=${web_port:-$((15173 + lane * 10))}
elif [ -n "${MV_LANE:-}" ]; then
  # A pinned lane must fail fast rather than fight for a busy port. Claim first
  # so a run that is still building holds its lane for its whole lifetime.
  if ! claim_lane "$lane"; then
    echo "Smoke test failed: MV_LANE $lane is already claimed by another verification run" >&2
    exit 1
  fi
  used_lane=$lane
  api_port=$((18000 + lane * 10))
  web_port=$((15173 + lane * 10))
  if ! port_free "$api_port"; then
    release_lane
    echo "Smoke test failed: MV_LANE $lane needs API port $api_port, which is already in use" >&2
    exit 1
  fi
  if ! port_free "$web_port"; then
    release_lane
    echo "Smoke test failed: MV_LANE $lane needs web port $web_port, which is already in use" >&2
    exit 1
  fi
else
  # No lane pinned: take the first lane that is both unclaimed and has two free
  # ports, so two concurrent runs land on different lanes without any
  # configuration. Lane 0 being free keeps a single run on the historical
  # 18000/15173. The probe is the second check: it still catches ports held by
  # something that is not one of our runs.
  api_port=
  web_port=
  for candidate in 0 1 2; do
    candidate_api=$((18000 + candidate * 10))
    candidate_web=$((15173 + candidate * 10))
    if claim_lane "$candidate" && port_free "$candidate_api" && port_free "$candidate_web"; then
      api_port=$candidate_api
      web_port=$candidate_web
      used_lane=$candidate
      break
    fi
    release_lane
  done
  if [ -z "$api_port" ]; then
    echo "Smoke test failed: no free smoke lane in 0-2; set MV_LANE or MAKERSVAULT_SMOKE_API_PORT/MAKERSVAULT_SMOKE_WEB_PORT, and \`rm -rf /tmp/makersvault-smoke-lanes/*\` if a killed run left locks behind" >&2
    exit 1
  fi
fi

echo "Smoke project $project_name on host ports $api_port/$web_port${used_lane:+ (lane $used_lane)}"

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
  # --rmi local also drops the images this run built, so per-run tags do not
  # accumulate on the Docker daemon.
  compose down --volumes --remove-orphans --rmi local >/dev/null 2>&1 || true
}

# Releasing the lane belongs to the exit paths only: the pre-start `cleanup`
# below must not drop the claim this run has just made, or two runs could pick
# the same lane (Mf-ly4o).
on_exit() {
  release_lane
  cleanup
}

trap on_exit EXIT HUP INT TERM
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

response_headers() {
  curl --silent --show-error --dump-header - --output /dev/null "$1"
}

assert_header() {
  url=$1
  header=$2
  expected=$3

  if ! headers=$(response_headers "$url"); then
    echo "Smoke test failed: could not fetch $url while checking $header" >&2
    exit 1
  fi

  if printf '%s\n' "$headers" | grep -qi "^${header}:.*${expected}"; then
    return 0
  fi

  echo "Smoke test failed: $url is missing response header $header (expected to contain \"$expected\")" >&2
  printf '%s\n' "$headers" >&2
  exit 1
}

for web_url in "http://localhost:$web_port/" "http://localhost:$web_port/api/health"; do
  assert_header "$web_url" x-content-type-options nosniff
  assert_header "$web_url" referrer-policy strict-origin-when-cross-origin
  assert_header "$web_url" x-frame-options DENY
  assert_header "$web_url" strict-transport-security 'max-age='
  assert_header "$web_url" content-security-policy 'default-src'
done

assert_header "http://localhost:$web_port/runtime-config.js" cache-control no-store

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
