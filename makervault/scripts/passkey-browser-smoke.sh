#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
project_name=${MAKERSVAULT_PASSKEY_PROJECT:-makersvault-gate11e-passkey}
api_port=${MAKERSVAULT_PASSKEY_API_PORT:-18005}
web_port=${MAKERSVAULT_PASSKEY_WEB_PORT:-15178}
playwright_image=${MAKERSVAULT_PASSKEY_PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.62.1-noble@sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e}

compose() {
  API_PORT="$api_port" \
  WEB_PORT="$web_port" \
  VITE_API_URL="http://localhost:$api_port" \
  CORS_ORIGINS="http://localhost:$web_port" \
  WEBAUTHN_RP_ID="localhost" \
  WEBAUTHN_ORIGIN="http://localhost:$web_port" \
  WEBAUTHN_RP_NAME="MakersVault browser drill" \
  AUTH_PASSWORD="local-development-only" \
  AUTH_SECRET="gate11e-passkey-browser-secret-000000000000000000000000" \
    docker compose \
      --project-directory "$app_dir" \
      --project-name "$project_name" \
      -f "$app_dir/docker-compose.yml" \
      -f "$app_dir/docker-compose.organization-benchmark.yml" \
      "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}

trap cleanup EXIT HUP INT TERM
cleanup
compose up --detach --build

attempt=1
while [ "$attempt" -le 90 ]; do
  if curl --fail --silent "http://localhost:$api_port/health" >/dev/null 2>&1 \
    && curl --fail --silent "http://localhost:$web_port/" >/dev/null 2>&1; then
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

docker run --rm --network host --ipc=host \
  -e MAKERSVAULT_PASSKEY_WEB_URL="http://localhost:$web_port" \
  -e MAKERSVAULT_PASSKEY_OUTPUT="/work/.artifacts/passkey-browser.json" \
  -v "$app_dir/benchmarks/organization:/work" \
  -v /work/node_modules \
  -w /work \
  "$playwright_image" sh -c 'npm ci --ignore-scripts --no-audit --no-fund && npm run passkey'
