#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
compose_file="$app_dir/docker-compose.deploy.yml"
env_file="$app_dir/.env"
project_name=${COMPOSE_PROJECT_NAME:-makersvault}
archive=""
replace=false
config_output=""
leave_stopped=false

usage() {
  cat <<'EOF'
Usage: ./scripts/restore.sh --archive PATH [options]

Options:
  --compose-file PATH  Compose manifest (default: docker-compose.deploy.yml)
  --env-file PATH      Current deployment environment file (default: .env)
  --project-name NAME  Exact Compose project (default: makersvault)
  --replace            Clear and replace non-empty database/storage volumes
  --config-output PATH Extract archived config to a new comparison file
  --leave-stopped      Do not restart services after a successful restore
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --archive) archive=${2:-}; shift 2 ;;
    --compose-file) compose_file=${2:-}; shift 2 ;;
    --env-file) env_file=${2:-}; shift 2 ;;
    --project-name) project_name=${2:-}; shift 2 ;;
    --replace) replace=true; shift ;;
    --config-output) config_output=${2:-}; shift 2 ;;
    --leave-stopped) leave_stopped=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$archive" ] || [ ! -f "$archive" ]; then
  echo "A readable --archive is required" >&2
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
  echo "Current environment file not found: $env_file" >&2
  exit 2
fi
if [ -n "$config_output" ] && [ -e "$config_output" ]; then
  echo "Config output already exists: $config_output" >&2
  exit 2
fi

compose() {
  docker compose \
    --project-name "$project_name" \
    --env-file "$env_file" \
    -f "$compose_file" \
    "$@"
}

temporary=$(mktemp -d)
api_was_running=""
web_was_running=""
services_stopped=false
mutation_started=false
restore_complete=false

restart_services() {
  if [ "$services_stopped" != true ]; then
    return
  fi
  if [ -n "$api_was_running" ] && ! compose start api >/dev/null; then
    echo "Warning: the API could not be restarted automatically" >&2
  fi
  if [ -n "$web_was_running" ] && ! compose start web >/dev/null; then
    echo "Warning: the web service could not be restarted automatically" >&2
  fi
  services_stopped=false
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  rm -rf -- "$temporary"
  if [ "$mutation_started" = false ] || { [ "$restore_complete" = true ] && [ "$leave_stopped" != true ]; }; then
    restart_services
  elif [ "$restore_complete" != true ] && [ "$services_stopped" = true ]; then
    echo "Restore failed after volume mutation began; services remain stopped for operator recovery." >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

python3 "$app_dir/api/recovery.py" extract --archive "$archive" --output-dir "$temporary/extracted" >/dev/null
compose config -q

api_was_running=$(compose ps --status running -q api 2>/dev/null || true)
web_was_running=$(compose ps --status running -q web 2>/dev/null || true)
services_stopped=true
compose stop api web >/dev/null

if ! compose run --rm -T --no-deps --entrypoint sh api -eu -c \
  'test -z "$(find /app/data -mindepth 1 -maxdepth 1 -print -quit)" && test -z "$(find /app/storage -mindepth 1 -maxdepth 1 -print -quit)"'; then
  if [ "$replace" != true ]; then
    echo "Restore targets are not empty. Re-run with --replace only after preserving the current matched backup." >&2
    exit 2
  fi
  mutation_started=true
  compose run --rm -T --no-deps --entrypoint sh api -eu -c \
    'find /app/data -mindepth 1 -delete; find /app/storage -mindepth 1 -delete'
fi

mutation_started=true
compose run --rm -T --no-deps --entrypoint tar api -C /app/storage -xf - < "$temporary/extracted/storage.tar"
compose run --rm -T --no-deps --entrypoint tar api -C /app/data -xf - < "$temporary/extracted/database.tar"
compose run --rm -T --no-deps --entrypoint sh api -eu -c \
  'chown -R "${PUID:-1000}:${PGID:-1000}" /app/data /app/storage'
compose run --rm -T --no-deps --entrypoint tar api -C /app/data -cf - . > "$temporary/restored-database.tar"
compose run --rm -T --no-deps --entrypoint tar api -C /app/storage -cf - . > "$temporary/restored-storage.tar"
python3 "$app_dir/api/recovery.py" verify-restored \
  --archive "$archive" \
  --database-tar "$temporary/restored-database.tar" \
  --storage-tar "$temporary/restored-storage.tar" \
  >/dev/null

# Exact archive equality is proven above. The only permitted post-restore database
# mutation revokes copied sessions and queues a startup audit marker.
compose run --rm -T --no-deps --entrypoint python api \
  /app/recovery_mutation.py --database /app/data/app.db >/dev/null
compose run --rm -T --no-deps --entrypoint tar api -C /app/data -cf - . \
  > "$temporary/post-recovery-database.tar"
python3 "$app_dir/api/recovery.py" audit-components \
  --database-tar "$temporary/post-recovery-database.tar" \
  --storage-tar "$temporary/restored-storage.tar" \
  >/dev/null

if [ -n "$config_output" ]; then
  if [ ! -f "$temporary/extracted/config.env" ]; then
    echo "Backup does not contain deployment configuration" >&2
    exit 2
  fi
  install -m 600 "$temporary/extracted/config.env" "$config_output"
fi

restore_complete=true
if [ "$leave_stopped" != true ]; then
  restart_services
fi

echo "MakersVault database and storage restored as a matched set from: $archive"
