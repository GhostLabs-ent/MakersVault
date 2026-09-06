#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
# Compatibility entry point for the current lifecycle drill. Reproduce historical
# Gate 5 qualification from f6ff55b; never accept schema 5 as current schema 17.
exec python3 "$script_dir/gate13-lifecycle-drill.py" "$@"
