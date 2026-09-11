#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
project_name=${MAKERSVAULT_SMOKE_PROJECT:-makersvault-gate0-smoke}
api_port=${MAKERSVAULT_SMOKE_API_PORT:-18000}
web_port=${MAKERSVAULT_SMOKE_WEB_PORT:-15173}
cookie_dir=$(mktemp -d)

cd "$app_dir"

compose() {
  API_PORT="$api_port" \
  WEB_PORT="$web_port" \
  VITE_API_URL="http://localhost:$api_port" \
  CORS_ORIGINS="http://localhost:$web_port" \
    docker compose \
      --project-name "$project_name" \
      -f docker-compose.yml \
      -f docker-compose.smoke.yml \
      "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}

final_cleanup() {
  cleanup
  rm -rf -- "$cookie_dir"
}

trap final_cleanup EXIT HUP INT TERM
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

for service in api web; do
  # Check PID 1 itself; docker exec runs with separate container credentials.
  process_status=$(compose exec -T "$service" cat /proc/1/status)
  printf '%s\n' "$process_status" | python3 "$script_dir/container_privileges.py"
done

schema_output=$(compose exec -T api python -m migrations)
case "$schema_output" in
  *"schema version: 17"*) ;;
  *)
    echo "Smoke test failed: unexpected schema output: $schema_output" >&2
    exit 1
    ;;
esac

if ! compose exec -T web grep -q "client_max_body_size 513m;" /etc/nginx/conf.d/default.conf; then
  echo "Smoke test failed: generated Nginx configuration does not allow the default file limit plus multipart framing" >&2
  exit 1
fi

web_headers=$(curl --fail --silent --show-error --head "http://localhost:$web_port/")
for expected_header in \
  "content-security-policy: default-src 'self'" \
  "script-src 'self' 'wasm-unsafe-eval'" \
  "connect-src 'self' http://localhost:$api_port" \
  "worker-src 'self' blob:" \
  "x-content-type-options: nosniff" \
  "referrer-policy: no-referrer" \
  "permissions-policy: camera=()" \
  "x-frame-options: DENY"; do
  if ! printf '%s\n' "$web_headers" | grep -Fqi "$expected_header"; then
    echo "Smoke test failed: web response omitted security header: $expected_header" >&2
    exit 1
  fi
done

api_headers=$(curl --fail --silent --show-error --dump-header - --output /dev/null "http://localhost:$api_port/health")
for expected_header in \
  "x-content-type-options: nosniff" \
  "referrer-policy: no-referrer" \
  "permissions-policy: camera=()" \
  "x-frame-options: DENY"; do
  if ! printf '%s\n' "$api_headers" | grep -Fqi "$expected_header"; then
    echo "Smoke test failed: API response omitted security header: $expected_header" >&2
    exit 1
  fi
done

direct_cookie_jar="$cookie_dir/direct.cookies"
direct_login=$(curl --fail --silent --show-error \
  --cookie-jar "$direct_cookie_jar" \
  --header "Content-Type: application/json" \
  --data '{"username":"admin","password":"local-development-only"}' \
  "http://localhost:$api_port/login")
direct_csrf=$(printf '%s' "$direct_login" | python3 -c 'import json,sys; print(json.load(sys.stdin)["csrf_token"])')
if ! grep -q 'makersvault_session_dev' "$direct_cookie_jar"; then
  echo "Smoke test failed: direct login omitted the development session cookie" >&2
  exit 1
fi
curl --fail --silent --show-error \
  --cookie "$direct_cookie_jar" \
  "http://localhost:$api_port/session" >/dev/null
curl --fail --silent --show-error \
  --cookie "$direct_cookie_jar" \
  --header "Origin: http://localhost:$web_port" \
  --header "X-CSRF-Token: $direct_csrf" \
  --request POST \
  "http://localhost:$api_port/logout" >/dev/null
if curl --fail --silent --show-error \
  --cookie "$direct_cookie_jar" \
  "http://localhost:$api_port/session" >/dev/null 2>&1; then
  echo "Smoke test failed: logout did not revoke the direct browser session" >&2
  exit 1
fi

proxy_cookie_jar="$cookie_dir/proxy.cookies"
curl --fail --silent --show-error \
  --cookie-jar "$proxy_cookie_jar" \
  --header "Content-Type: application/json" \
  --data '{"username":"admin","password":"local-development-only"}' \
  "http://localhost:$web_port/api/login" >/dev/null
curl --fail --silent --show-error \
  --cookie "$proxy_cookie_jar" \
  "http://localhost:$web_port/api/session" >/dev/null

echo "Container smoke test passed (direct and same-origin cookie sessions, logout revocation, security headers, 512 MiB file policy, API UID $api_uid, web UID $web_uid, schema 17)."
