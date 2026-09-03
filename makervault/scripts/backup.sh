#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
repo_dir=$(CDPATH= cd -- "$app_dir/.." && pwd)
compose_file="$app_dir/docker-compose.deploy.yml"
env_file="$app_dir/.env"
project_name=${COMPOSE_PROJECT_NAME:-makersvault}
release=${MAKERSVAULT_RELEASE:-v5.1.0}
source_revision=${MAKERSVAULT_SOURCE_REVISION:-}
output=""
overwrite=false
leave_stopped=false
administrator_recovery_snapshot=false

usage() {
  cat <<'EOF'
Usage: ./scripts/backup.sh --output PATH [options]

Options:
  --compose-file PATH   Compose manifest (default: docker-compose.deploy.yml)
  --env-file PATH       Sensitive deployment environment file (default: .env)
  --project-name NAME   Exact Compose project (default: makersvault)
  --release VERSION     Release identity stored in the manifest (default: v5.1.0)
  --source-revision SHA Source revision stored in the manifest
  --overwrite           Replace an existing backup path
  --leave-stopped       Do not restart services after backup (including on failure)
  --administrator-recovery-snapshot
                        Permit only a missing-enabled-Administrator readiness finding
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) output=${2:-}; shift 2 ;;
    --compose-file) compose_file=${2:-}; shift 2 ;;
    --env-file) env_file=${2:-}; shift 2 ;;
    --project-name) project_name=${2:-}; shift 2 ;;
    --release) release=${2:-}; shift 2 ;;
    --source-revision) source_revision=${2:-}; shift 2 ;;
    --overwrite) overwrite=true; shift ;;
    --leave-stopped) leave_stopped=true; shift ;;
    --administrator-recovery-snapshot) administrator_recovery_snapshot=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$output" ]; then
  echo "--output is required" >&2
  exit 2
fi
case "$project_name" in
  ""|*[!A-Za-z0-9_.-]*) echo "Invalid Compose project name" >&2; exit 2 ;;
esac
if [ ! -f "$compose_file" ]; then
  echo "Compose manifest not found: $compose_file" >&2
  exit 2
fi
if [ ! -f "$env_file" ]; then
  echo "Environment file not found: $env_file" >&2
  exit 2
fi
if [ -e "$output" ] && [ "$overwrite" != true ]; then
  echo "Backup already exists: $output" >&2
  exit 2
fi
if [ -z "$source_revision" ]; then
  source_revision=$(git -C "$repo_dir" rev-parse HEAD 2>/dev/null || true)
fi
if [ -z "$source_revision" ]; then
  echo "--source-revision is required outside a Git checkout" >&2
  exit 2
fi

compose() {
  docker compose \
    --project-name "$project_name" \
    --env-file "$env_file" \
    -f "$compose_file" \
    "$@"
}

compose config -q
temporary=$(mktemp -d)
api_was_running=$(compose ps --status running -q api 2>/dev/null || true)
web_was_running=$(compose ps --status running -q web 2>/dev/null || true)

restart_previous() {
  if [ -n "$api_was_running" ]; then
    compose start api >/dev/null
  fi
  if [ -n "$web_was_running" ]; then
    compose start web >/dev/null
  fi
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$leave_stopped" != true ]; then
    restart_previous || true
  fi
  rm -rf -- "$temporary"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

compose stop api web >/dev/null
compose run --rm -T --no-deps --entrypoint tar api -C /app/data -cf - . > "$temporary/database.tar"
compose run --rm -T --no-deps --entrypoint tar api -C /app/storage -cf - . > "$temporary/storage.tar"

create_args=""
if [ "$overwrite" = true ]; then
  create_args="--overwrite"
fi
if [ "$administrator_recovery_snapshot" = true ]; then
  create_args="$create_args --administrator-recovery-snapshot"
fi
python3 "$app_dir/api/recovery.py" create \
  --database-tar "$temporary/database.tar" \
  --storage-tar "$temporary/storage.tar" \
  --config-env "$env_file" \
  --output "$output" \
  --release "$release" \
  --source-revision "$source_revision" \
  --compose-project "$project_name" \
  --compose-manifest "$(basename "$compose_file")" \
  --database-source "${project_name}_makersvault_db" \
  --storage-source "${project_name}_makersvault_storage" \
  $create_args \
  > "$temporary/manifest.json"
verify_args=""
if [ "$administrator_recovery_snapshot" = true ]; then
  verify_args="--administrator-recovery-snapshot"
fi
python3 "$app_dir/api/recovery.py" verify --archive "$output" $verify_args >/dev/null

echo "MakersVault backup created and verified: $output"
echo "The archive contains sensitive deployment configuration; keep its permissions restricted."
