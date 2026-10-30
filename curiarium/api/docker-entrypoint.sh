#!/bin/sh
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}
APP_USER=appuser
APP_GROUP=appgroup

# Align group with requested PGID (create or update in-place).
if getent group "$PGID" >/dev/null 2>&1; then
  APP_GROUP="$(getent group "$PGID" | cut -d: -f1)"
elif getent group "$APP_GROUP" >/dev/null 2>&1; then
  groupmod -o -g "$PGID" "$APP_GROUP"
else
  groupadd -g "$PGID" "$APP_GROUP"
fi

# Align user with requested PUID.
if id "$APP_USER" >/dev/null 2>&1; then
  usermod -o -u "$PUID" -g "$PGID" "$APP_USER"
else
  useradd -u "$PUID" -g "$PGID" -M -s /usr/sbin/nologin "$APP_USER"
fi

# Make sure mounted data directories are writable by the runtime user.
# Recursive chown can be very slow on large libraries, so keep it opt-in.
CHOWN_MODE=${CHOWN_MODE:-minimal}
mkdir -p /app/storage /app/data
if [ "$CHOWN_MODE" = "recursive" ]; then
  chown -R "$PUID":"$PGID" /app/storage /app/data 2>/dev/null || true
else
  chown "$PUID":"$PGID" /app/storage /app/data 2>/dev/null || true
fi

exec gosu "$APP_USER" "$@"
