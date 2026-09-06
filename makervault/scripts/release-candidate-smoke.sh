#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
# Current cookie-session/schema-17 contract. Gate 5's schema-5/JWT smoke remains
# reproducible from its immutable f6ff55b checkout, not a compatibility bypass here.
exec python3 "$script_dir/current-image-smoke.py" "$@"
