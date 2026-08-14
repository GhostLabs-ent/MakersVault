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

api_url="${VITE_API_URL:-}"
if [ -z "$api_url" ] && [ -n "${PUBLIC_URL:-}" ]; then
  api_url="${PUBLIC_URL%/}/api"
fi
single_line_api_url=$(printf '%s' "$api_url" | tr -d '\r\n')
if [ "$single_line_api_url" != "$api_url" ]; then
  echo "VITE_API_URL must not contain line breaks" >&2
  exit 1
fi

csp_api_source=""
case "$api_url" in
  http://*|https://*)
    csp_api_source=$(printf '%s\n' "$api_url" | sed -E 's#^(https?://[^/]+).*$#\1#')
    ;;
  //*)
    csp_host=$(printf '%s\n' "$api_url" | sed -E 's#^//([^/]+).*$#\1#')
    csp_api_source="http://${csp_host} https://${csp_host}"
    ;;
  ""|/*)
    ;;
  *)
    legacy_port=${api_url#:}
    case "$legacy_port" in
      ""|*[!0-9]*)
        echo "VITE_API_URL must be an HTTP(S) URL, root-relative path, or port" >&2
        exit 1
        ;;
    esac
    if [ "$legacy_port" -lt 1 ] || [ "$legacy_port" -gt 65535 ]; then
      echo "VITE_API_URL port must be between 1 and 65535" >&2
      exit 1
    fi
    csp_api_source="http://\$host:${legacy_port} https://\$host:${legacy_port}"
    ;;
esac

old_ifs=$IFS
IFS=,
set -f
for cors_url in ${CORS_ORIGINS:-}; do
  cors_url=$(printf '%s\n' "$cors_url" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
  [ -n "$cors_url" ] || continue
  case "$cors_url" in
    http://*|https://*)
      cors_source=$(printf '%s\n' "$cors_url" | sed -E 's#^(https?://[^/]+).*$#\1#')
      csp_api_source="${csp_api_source}${csp_api_source:+ }${cors_source}"
      ;;
    *)
      echo "CORS_ORIGINS entries must be HTTP(S) origins for the web CSP" >&2
      exit 1
      ;;
  esac
done
set +f
IFS=$old_ifs

single_line_csp_source=$(printf '%s' "$csp_api_source" | tr -d '\r\n')
if [ "$single_line_csp_source" != "$csp_api_source" ]; then
  echo "Configured API/CORS origins must not contain line breaks" >&2
  exit 1
fi
case "$csp_api_source" in
  *\"*|*\'*|*\;*|*\\*)
    echo "Configured API/CORS origins produced an unsafe CSP source" >&2
    exit 1
    ;;
esac

escaped_csp_api_source=$(printf '%s' "$csp_api_source" | sed 's/[&|\\]/\\&/g')
sed \
  -e "s|__MAKERSVAULT_PROXY_BODY_MAX_MB__|${proxy_body_max_mb}|g" \
  -e "s|__MAKERSVAULT_CSP_API_SOURCE__|${escaped_csp_api_source}|g" \
  /etc/nginx/conf.d/default.conf.template \
  > /etc/nginx/conf.d/default.conf

escaped_api_url=$(printf '%s' "$api_url" | sed 's/\\/\\\\/g; s/"/\\"/g')
rm -f /usr/share/nginx/html/runtime-config.js
printf 'window.__MAKERSVAULT_CONFIG__ = { apiUrl: "%s" };\n' "$escaped_api_url" > /usr/share/nginx/html/runtime-config.js
