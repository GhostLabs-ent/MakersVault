#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
env_file=${1:-$app_dir/.env}

if [ -e "$env_file" ]; then
  echo "Refusing to overwrite existing file: $env_file" >&2
  echo "Update AUTH_PASSWORD and AUTH_SECRET manually if this is an upgrade." >&2
  exit 1
fi

random_hex() {
  byte_count=$1
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$byte_count"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import secrets; print(secrets.token_hex($byte_count))"
    return
  fi
  echo "OpenSSL or Python 3 is required to generate secure credentials." >&2
  exit 1
}

admin_password=$(random_hex 20)
auth_secret=$(random_hex 32)
tmp_file=$(mktemp "${env_file}.tmp.XXXXXX")
trap 'rm -f "$tmp_file"' EXIT HUP INT TERM
umask 077

sed \
  -e "s/^AUTH_PASSWORD=.*/AUTH_PASSWORD=$admin_password/" \
  -e "s/^AUTH_SECRET=.*/AUTH_SECRET=$auth_secret/" \
  "$app_dir/.env.example" > "$tmp_file"
chmod 600 "$tmp_file"
mv "$tmp_file" "$env_file"
trap - EXIT HUP INT TERM

echo "Created $env_file with permissions 600."
echo "Administrator username: admin"
echo "Generated password: $admin_password"
echo "Store the password securely; MakersVault cannot display it again."
