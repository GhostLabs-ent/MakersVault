#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
repo_dir=$(CDPATH= cd -- "$app_dir/.." && pwd)
compose_file="$app_dir/docker-compose.deploy.yml"
allow_dirty=false

usage() {
  cat <<'EOF'
Usage: ./scripts/gate5-recovery-drill.sh [--allow-dirty]

Builds a versioned local API candidate, upgrades a representative pre-v5.1
library, restores it into a clean Compose project, and proves matched rollback.
All containers, volumes, fixtures, and archives are disposable and project-scoped.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --allow-dirty) allow_dirty=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

revision=$(git -C "$repo_dir" rev-parse HEAD)
short_revision=$(git -C "$repo_dir" rev-parse --short=12 HEAD)
if [ "$allow_dirty" != true ]; then
  if ! git -C "$repo_dir" diff --quiet || ! git -C "$repo_dir" diff --cached --quiet ||
     [ -n "$(git -C "$repo_dir" ls-files --others --exclude-standard)" ]; then
    echo "Recovery drill requires a clean source revision (or --allow-dirty for development only)" >&2
    exit 2
  fi
fi

candidate_image="makersvault-api:v5.1.0-gate5-$short_revision"
temporary=$(mktemp -d)
fixture="$temporary/fixture"
env_file="$fixture/deploy.env"
clean_env_file="$temporary/clean.env"
clean_imports="$temporary/clean-imports"
pre_backup="$temporary/pre-v5.1.backup.tar.gz"
upgraded_backup="$temporary/v5.1-upgraded.backup.tar.gz"
project_suffix="${short_revision}-$$"
upgrade_project="mv-g5-upgrade-$project_suffix"
clean_project="mv-g5-clean-$project_suffix"

compose() {
  project=$1
  environment=$2
  shift 2
  docker compose \
    --project-name "$project" \
    --env-file "$environment" \
    -f "$compose_file" \
    "$@"
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$status" -ne 0 ]; then
    echo "Gate 5 drill failed; collecting disposable API logs before cleanup" >&2
    if [ -f "$env_file" ]; then
      compose "$upgrade_project" "$env_file" logs --no-color --tail 120 api >&2 || true
    fi
    if [ -f "$clean_env_file" ]; then
      compose "$clean_project" "$clean_env_file" logs --no-color --tail 120 api >&2 || true
    fi
  fi
  if [ -f "$env_file" ]; then
    compose "$upgrade_project" "$env_file" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  if [ -f "$clean_env_file" ]; then
    compose "$clean_project" "$clean_env_file" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf -- "$temporary"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Building local Gate 5 candidate $candidate_image from $revision"
docker build \
  --target runtime \
  --label "org.opencontainers.image.version=v5.1.0" \
  --label "org.opencontainers.image.revision=$revision" \
  -t "$candidate_image" \
  "$app_dir/api"

python3 "$app_dir/api/tests/gate5_fixture.py" \
  --output "$fixture" \
  --api-image "$candidate_image" \
  >/dev/null
mkdir -p "$clean_imports"
sed "s|^IMPORT_MOUNT_PATH_HOST=.*|IMPORT_MOUNT_PATH_HOST=$clean_imports|" \
  "$env_file" > "$clean_env_file"
chmod 600 "$clean_env_file"

echo "Seeding representative schema-4 database and managed storage"
tar -C "$fixture/database" -cf - . | \
  compose "$upgrade_project" "$env_file" run --rm -T --no-deps --entrypoint tar api -C /app/data -xf -
tar -C "$fixture/storage" -cf - . | \
  compose "$upgrade_project" "$env_file" run --rm -T --no-deps --entrypoint tar api -C /app/storage -xf -

echo "Creating the stopped matched pre-upgrade backup"
"$script_dir/backup.sh" \
  --compose-file "$compose_file" \
  --env-file "$env_file" \
  --project-name "$upgrade_project" \
  --output "$pre_backup" \
  --release "pre-v5.1-schema-4-fixture" \
  --source-revision "gate5-fixture-schema-4"
python3 "$app_dir/api/recovery.py" verify --archive "$pre_backup" > "$temporary/pre-manifest.json"
python3 -c \
  'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")); assert value["database"]["schema_version"] == 4' \
  "$temporary/pre-manifest.json"

echo "Starting the v5.1 candidate and verifying the upgraded library through the API"
compose "$upgrade_project" "$env_file" up -d api
upgrade_port=$(compose "$upgrade_project" "$env_file" port api 8000)
upgrade_base_url="http://127.0.0.1:${upgrade_port##*:}"
python3 "$app_dir/api/tests/gate5_api_verify.py" \
  --base-url "$upgrade_base_url" \
  --username gate5 \
  --password gate5-recovery-password \
  --expected "$fixture/expected.json" \
  --external available

echo "Creating and checking the post-upgrade matched backup"
"$script_dir/backup.sh" \
  --compose-file "$compose_file" \
  --env-file "$env_file" \
  --project-name "$upgrade_project" \
  --output "$upgraded_backup" \
  --release "v5.1.0" \
  --source-revision "$revision"
python3 "$app_dir/api/recovery.py" verify --archive "$upgraded_backup" > "$temporary/upgraded-manifest.json"
python3 -c \
  'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")); assert value["database"]["schema_version"] == 5; assert value["source_revision"] == sys.argv[2]' \
  "$temporary/upgraded-manifest.json" "$revision"

echo "Restoring the upgraded backup into an empty, independent Compose project"
"$script_dir/restore.sh" \
  --compose-file "$compose_file" \
  --env-file "$clean_env_file" \
  --project-name "$clean_project" \
  --archive "$upgraded_backup"
compose "$clean_project" "$clean_env_file" up -d api
clean_port=$(compose "$clean_project" "$clean_env_file" port api 8000)
clean_base_url="http://127.0.0.1:${clean_port##*:}"
python3 "$app_dir/api/tests/gate5_api_verify.py" \
  --base-url "$clean_base_url" \
  --username gate5 \
  --password gate5-recovery-password \
  --expected "$fixture/expected.json" \
  --external unavailable

echo "Restoring the original project to the exact pre-upgrade matched snapshot"
"$script_dir/restore.sh" \
  --compose-file "$compose_file" \
  --env-file "$env_file" \
  --project-name "$upgrade_project" \
  --archive "$pre_backup" \
  --replace \
  --leave-stopped

echo "Gate 5 recovery drill passed"
echo "Candidate revision: $revision"
echo "Verified: schema-4 upgrade, authenticated API state, clean restore, no-copy limitation, exact rollback"
