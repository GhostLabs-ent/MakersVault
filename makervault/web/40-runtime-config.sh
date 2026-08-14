#!/bin/sh
set -eu

file_max_mb=${FILE_MAX_MB:-${IMPORT_MAX_MB:-512}}
case "$file_max_mb" in
  ''|*[!0-9]*)
    echo "FILE_MAX_MB must be a positive integer" >&2
    exit 1
    ;;
  0)
    echo "FILE_MAX_MB must be greater than zero" >&2
    exit 1
    ;;
esac

normalized_file_max_mb=$(printf '%s\n' "$file_max_mb" | sed 's/^0*//')
if [ -z "$normalized_file_max_mb" ]; then
  echo "FILE_MAX_MB must be greater than zero" >&2
  exit 1
fi
# Allow space for multipart framing while the API enforces the exact file limit.
proxy_body_max_mb=$((normalized_file_max_mb + 1))

sed "s/__MAKERSVAULT_PROXY_BODY_MAX_MB__/${proxy_body_max_mb}/g" \
  /etc/nginx/conf.d/default.conf.template \
  > /etc/nginx/conf.d/default.conf

api_url="${VITE_API_URL:-}"
if [ -z "$api_url" ] && [ -n "${PUBLIC_URL:-}" ]; then
  api_url="${PUBLIC_URL%/}/api"
fi

escaped_api_url=$(printf '%s' "$api_url" | sed 's/\\/\\\\/g; s/"/\\"/g')
rm -f /usr/share/nginx/html/runtime-config.js
printf 'window.__MAKERSVAULT_CONFIG__ = { apiUrl: "%s" };\n' "$escaped_api_url" > /usr/share/nginx/html/runtime-config.js
