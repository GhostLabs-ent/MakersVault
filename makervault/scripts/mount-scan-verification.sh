#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
project_name=${MAKERSVAULT_MOUNT_SCAN_PROJECT:-makersvault-gate4-mount-scan}
api_port=${MAKERSVAULT_MOUNT_SCAN_API_PORT:-18004}
web_port=${MAKERSVAULT_MOUNT_SCAN_WEB_PORT:-15177}
output_path="$app_dir/benchmarks/organization/.artifacts/mount-scan.json"
api_image=${MAKERSVAULT_BENCHMARK_API_IMAGE:-}
web_image=${MAKERSVAULT_BENCHMARK_WEB_IMAGE:-}

if [ -n "$api_image" ] || [ -n "$web_image" ]; then
  if [ -z "$api_image" ] || [ -z "$web_image" ]; then
    echo "MAKERSVAULT_BENCHMARK_API_IMAGE and MAKERSVAULT_BENCHMARK_WEB_IMAGE must be set together" >&2
    exit 2
  fi
  base_manifest=docker-compose.deploy.yml
  release_candidate=true
else
  base_manifest=docker-compose.yml
  release_candidate=false
fi

fixture_dir=$(mktemp -d)

mkdir -p "$fixture_dir/parts"
printf 'solid gate4-one\nendsolid gate4-one\n' > "$fixture_dir/one.stl"
printf 'solid gate4-two\nendsolid gate4-two\n' > "$fixture_dir/parts/two.stl"
printf 'excluded by extension\n' > "$fixture_dir/ignored.txt"
ln -s one.stl "$fixture_dir/rejected.stl"

cd "$app_dir"

compose() {
  (
    cd "$app_dir"
    API_PORT="$api_port" \
    WEB_PORT="$web_port" \
    VITE_API_URL="http://localhost:$api_port" \
    CORS_ORIGINS="http://localhost:$web_port" \
    MAKERSVAULT_MOUNT_FIXTURE="$fixture_dir" \
    API_IMAGE="$api_image" \
    WEB_IMAGE="$web_image" \
    AUTH_PASSWORD="local-development-only" \
    AUTH_SECRET="gate5-release-candidate-benchmark-secret-000000000000000000000000" \
      docker compose \
        --project-name "$project_name" \
        -f "$base_manifest" \
        -f docker-compose.mount-scan-verification.yml \
        "$@"
  )
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$fixture_dir"
}

trap cleanup EXIT HUP INT TERM
compose down --volumes --remove-orphans >/dev/null 2>&1 || true
if [ "$release_candidate" = true ]; then
  compose up --detach
else
  compose up --detach --build
fi

attempt=1
while [ "$attempt" -le 90 ]; do
  if curl --fail --silent --show-error "http://localhost:$api_port/health" >/dev/null 2>&1 \
    && curl --fail --silent --show-error "http://localhost:$web_port/" >/dev/null 2>&1; then
    break
  fi
  if [ "$attempt" -eq 90 ]; then
    compose ps
    compose logs --no-color --tail=100
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 1
done

if [ "$release_candidate" = true ]; then
  sh "$script_dir/verify-running-release-images.sh" \
    "$api_image" "$web_image" "$(compose ps -q api)" "$(compose ps -q web)"
fi

cd benchmarks/organization
MAKERSVAULT_BENCHMARK_API_URL="http://localhost:$api_port" \
MAKERSVAULT_BENCHMARK_WEB_URL="http://localhost:$web_port" \
MAKERSVAULT_MOUNT_SCAN_OUTPUT="$output_path" \
  npm run mount-scan
