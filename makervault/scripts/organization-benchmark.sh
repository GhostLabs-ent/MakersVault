#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
project_name=${MAKERSVAULT_BENCHMARK_PROJECT:-makersvault-gate3-benchmark}
api_port=${MAKERSVAULT_BENCHMARK_API_PORT:-18003}
web_port=${MAKERSVAULT_BENCHMARK_WEB_PORT:-15176}
output_path="$app_dir/benchmarks/organization/.artifacts/baseline.json"

cd "$app_dir"

compose() {
  (
    cd "$app_dir"
    API_PORT="$api_port" \
    WEB_PORT="$web_port" \
    VITE_API_URL="http://localhost:$api_port" \
    CORS_ORIGINS="http://localhost:$web_port" \
      docker compose \
        --project-name "$project_name" \
        -f docker-compose.yml \
        -f docker-compose.organization-benchmark.yml \
        "$@"
  )
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}

trap cleanup EXIT HUP INT TERM
cleanup
compose up --detach --build

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

cd benchmarks/organization
MAKERSVAULT_BENCHMARK_API_URL="http://localhost:$api_port" \
MAKERSVAULT_BENCHMARK_WEB_URL="http://localhost:$web_port" \
MAKERSVAULT_BENCHMARK_OUTPUT="$output_path" \
  npm run baseline
