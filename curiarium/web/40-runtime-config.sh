#!/bin/sh
set -eu

api_url="${VITE_API_URL:-}"
if [ -z "$api_url" ] && [ -n "${PUBLIC_URL:-}" ]; then
  api_url="${PUBLIC_URL%/}/api"
fi

escaped_api_url=$(printf '%s' "$api_url" | sed 's/\\/\\\\/g; s/"/\\"/g')
rm -f /usr/share/nginx/html/runtime-config.js
printf 'window.__CURIARIUM_CONFIG__ = { apiUrl: "%s" };\n' "$escaped_api_url" > /usr/share/nginx/html/runtime-config.js
