#!/bin/sh
set -eu

# Only this disposable container's trust stores change. No private key is mounted.
test -f /fixture/server.crt
install -m 644 /fixture/server.crt /usr/local/share/ca-certificates/makersvault-fixture.crt
update-ca-certificates >/dev/null
mkdir -p /root/.local/share/pki/nssdb
if [ ! -f /root/.local/share/pki/nssdb/cert9.db ]; then
  certutil -N -d sql:/root/.local/share/pki/nssdb --empty-password
fi
certutil -A -d sql:/root/.local/share/pki/nssdb -t 'P,,' \
  -n makersvault-fixture -i /fixture/server.crt
export NODE_EXTRA_CA_CERTS=/fixture/server.crt
exec "$@"
