#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)

if [ "$#" -ne 1 ]; then
  echo "Usage: ./scripts/verify-backup.sh BACKUP.tar.gz" >&2
  exit 2
fi

python3 "$app_dir/api/recovery.py" verify --archive "$1"
