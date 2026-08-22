#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
compose_file="$app_dir/docker-compose.deploy.yml"
api_image=""
web_image=""
version=""
revision=""

usage() {
  cat <<'EOF'
Usage: ./scripts/release-candidate-smoke.sh --api-image IMAGE --web-image IMAGE --version VERSION --revision SHA

Starts the exact local versioned images with the canonical production manifest in
unique disposable volumes, verifies identity/security/persistence, and removes them.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --api-image) api_image=${2:-}; shift 2 ;;
    --web-image) web_image=${2:-}; shift 2 ;;
    --version) version=${2:-}; shift 2 ;;
    --revision) revision=${2:-}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
if [ -z "$api_image" ] || [ -z "$web_image" ] || [ -z "$version" ] || [ -z "$revision" ]; then
  usage >&2
  exit 2
fi

for item in "$api_image" "$web_image"; do
  docker image inspect "$item" >/dev/null
  actual_version=$(docker image inspect "$item" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')
  actual_revision=$(docker image inspect "$item" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  if [ "$actual_version" != "$version" ] || [ "$actual_revision" != "$revision" ]; then
    echo "Release image identity mismatch: $item" >&2
    exit 2
  fi
done

temporary=$(mktemp -d)
env_file="$temporary/release.env"
imports="$temporary/imports"
model="$temporary/persistent.stl"
project="mv-g5-rc-$(printf '%s' "$revision" | cut -c1-12)-$$"
mkdir -p "$imports"
printf 'solid persisted\nendsolid persisted\n' > "$model"
sed \
  -e "s|^API_IMAGE=.*|API_IMAGE=$api_image|" \
  -e "s|^WEB_IMAGE=.*|WEB_IMAGE=$web_image|" \
  -e 's|^API_PORT=.*|API_PORT=0|' \
  -e 's|^WEB_PORT=.*|WEB_PORT=0|' \
  -e 's|^AUTH_USERNAME=.*|AUTH_USERNAME=gate5rc|' \
  -e 's|^AUTH_PASSWORD=.*|AUTH_PASSWORD=gate5-release-smoke-password|' \
  -e 's|^AUTH_SECRET=.*|AUTH_SECRET=gate5-release-smoke-signing-secret-value-32-bytes|' \
  -e "s|^IMPORT_MOUNT_PATH_HOST=.*|IMPORT_MOUNT_PATH_HOST=$imports|" \
  "$app_dir/.env.example" > "$env_file"
chmod 600 "$env_file"

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    -f "$compose_file" \
    "$@"
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$status" -ne 0 ]; then
    compose logs --no-color --tail 120 >&2 || true
  fi
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$temporary"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

compose config -q
compose up -d api web

refresh_urls() {
  api_port=$(compose port api 8000)
  web_port=$(compose port web 5173)
  api_url="http://127.0.0.1:${api_port##*:}"
  web_url="http://127.0.0.1:${web_port##*:}"
}
refresh_urls

wait_for_health() {
  attempt=1
  while [ "$attempt" -le 60 ]; do
    if curl --fail --silent "$api_url/health" >/dev/null 2>&1 \
      && curl --fail --silent "$web_url/" >/dev/null 2>&1 \
      && curl --fail --silent "$web_url/api/health" >/dev/null 2>&1; then
      return
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  echo "Release candidate did not become healthy" >&2
  exit 1
}
wait_for_health

health=$(curl --fail --silent "$api_url/health")
printf '%s' "$health" | jq -e \
  --arg version "$version" --arg revision "$revision" \
  '.ok == true and .auth_required == true and .version == $version and .revision == $revision' \
  >/dev/null

token=$(curl --fail --silent \
  -H 'Content-Type: application/json' \
  -d '{"username":"gate5rc","password":"gate5-release-smoke-password"}' \
  "$api_url/login" | jq -r '.token')
asset=$(curl --fail --silent \
  -H "Authorization: Bearer $token" \
  -F "file=@$model;type=model/stl" \
  -F 'title=Persistent RC Fixture' \
  "$api_url/upload")
asset_id=$(printf '%s' "$asset" | jq -r '.id')
file_url=$(printf '%s' "$asset" | jq -r '.url')
test -n "$asset_id"

compose restart api web >/dev/null
refresh_urls
wait_for_health
curl --fail --silent -H "Authorization: Bearer $token" "$api_url/assets?limit=100" | \
  jq -e --arg id "$asset_id" 'any(.[]; .id == $id and .name == "Persistent RC Fixture")' >/dev/null
restored_sha=$(curl --fail --silent -H "Authorization: Bearer $token" "$api_url$file_url" | sha256sum | cut -d' ' -f1)
original_sha=$(sha256sum "$model" | cut -d' ' -f1)
test "$restored_sha" = "$original_sha"

api_uid=$(compose exec -T api stat -c %u /proc/1)
web_uid=$(compose exec -T web stat -c %u /proc/1)
test "$api_uid" != 0
test "$web_uid" != 0
compose exec -T api python -m migrations | grep -F 'schema version: 5' >/dev/null

echo "Release candidate smoke passed: $version $revision (API UID $api_uid, web UID $web_uid)"
