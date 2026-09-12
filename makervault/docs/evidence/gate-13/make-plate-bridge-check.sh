#!/bin/sh
# Container-only; source is mounted read-only and its normal home is disposable.
set -eu
test -f /.dockerenv
test "$(pwd)" = /src
export GOTOOLCHAIN=local GOPROXY=off
go version
if [ "${1:-}" = red ]; then
  go test -count=1 -run 'TestManualInstallersRegisterEverySupportedProtocol|TestPairingBrowserCommandPlatforms' ./...
  exit 0
fi
revision="${1:?exact source revision required}"
go test -count=1 -race -json ./...
for platform in linux windows darwin; do
  for architecture in amd64 arm64; do
    CGO_ENABLED=0 GOOS="$platform" GOARCH="$architecture" go build \
      -ldflags "-X main.version=development-mp0 -X main.revision=$revision" \
      -o "/tmp/makersvault-mp0-$platform-$architecture" ./cmd/slicer-bridge
    printf 'crossbuild=%s/%s status=passed execution=not-tested\n' "$platform" "$architecture"
  done
done
bridge=/tmp/makersvault-mp0-linux-amd64
test "$("$bridge" --version)" = "MakersVault Bridge development-mp0 ($revision)"
"$bridge" doctor
# Exercise the manual installer against the generated binary, in container home only.
sh scripts/install-linux.sh "$bridge"
cmp "$bridge" /root/.local/bin/makersvault-slicer
grep -Fx 'MimeType=x-scheme-handler/makersvault-slicer;x-scheme-handler/makersvault-engrave;x-scheme-handler/makersvault-open;' \
  /root/.local/share/applications/makersvault-slicer.desktop
/root/.local/bin/makersvault-slicer doctor
printf 'linux-manual-container-install=passed desktop-launch=not-tested\n'
