#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
compose_file="$app_dir/docker-compose.deploy.yml"
env_file="$app_dir/.env"
project_name=${COMPOSE_PROJECT_NAME:-makersvault}
backup=""
username=""
leave_stopped=false

usage() {
  cat <<'EOF'
Usage: ./scripts/recover-administrator.sh --backup PATH --username USERNAME [options]

Options:
  --compose-file PATH  Compose manifest (default: docker-compose.deploy.yml)
  --env-file PATH      Deployment environment file (default: .env)
  --project-name NAME  Exact Compose project (default: makersvault)
  --leave-stopped      Do not restart previously running services after success

The backup path must not exist. A verified matched backup is created there before
the interactive recovery mutation. On any failure after shutdown, services remain
stopped for operator review.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --backup) backup=${2:-}; shift 2 ;;
    --username) username=${2:-}; shift 2 ;;
    --compose-file) compose_file=${2:-}; shift 2 ;;
    --env-file) env_file=${2:-}; shift 2 ;;
    --project-name) project_name=${2:-}; shift 2 ;;
    --leave-stopped) leave_stopped=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$backup" ] || [ -z "$username" ]; then
  echo "--backup and --username are required" >&2
  exit 2
fi
if [ -e "$backup" ]; then
  echo "Backup path already exists: $backup" >&2
  exit 2
fi
case "$project_name" in
  ""|*[!A-Za-z0-9_.-]*) echo "Invalid Compose project name" >&2; exit 2 ;;
esac
if [ ! -f "$compose_file" ] || [ ! -f "$env_file" ]; then
  echo "Compose manifest and environment file must exist" >&2
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
api_was_running=$(compose ps --status running -q api 2>/dev/null || true)
web_was_running=$(compose ps --status running -q web 2>/dev/null || true)
recovery_complete=false

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$recovery_complete" != true ]; then
    echo "Administrator recovery did not complete; services remain stopped." >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

"$script_dir/backup.sh" \
  --output "$backup" \
  --compose-file "$compose_file" \
  --env-file "$env_file" \
  --project-name "$project_name" \
  --administrator-recovery-snapshot \
  --leave-stopped

backup_dir=$(CDPATH= cd -- "$(dirname "$backup")" && pwd)
backup_absolute="$backup_dir/$(basename "$backup")"
compose run --rm --no-deps \
  -v "$backup_absolute:/recovery/prechange.tar.gz:ro" \
  --entrypoint python api \
  /app/offline_recovery.py \
  --database /app/data/app.db \
  --backup /recovery/prechange.tar.gz \
  --username "$username"

recovery_complete=true
if [ "$leave_stopped" != true ]; then
  if [ -n "$api_was_running" ]; then
    compose start api >/dev/null
  fi
  if [ -n "$web_was_running" ]; then
    compose start web >/dev/null
  fi
fi

echo "Existing account recovered as Administrator; all browser sessions were revoked."
echo "The recovered account must change its temporary password at next sign-in."
