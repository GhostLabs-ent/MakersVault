#!/bin/sh
# Run only in a disposable, network-disabled container with /src mounted read-only.
set -eu
test -f /.dockerenv
test "$(pwd)" = /src
export GOTOOLCHAIN=local GOPROXY=off
go version
go test -count=1 -race -json ./...
for platform in linux windows darwin; do
  for architecture in amd64 arm64; do
    CGO_ENABLED=0 GOOS="$platform" GOARCH="$architecture" go build \
      -ldflags '-X main.version=development-gate13b -X main.revision=6306ccff289d475530a6cacf4cb2e28db456ce08' \
      -o "/tmp/makersvault-bridge-$platform-$architecture" ./cmd/slicer-bridge
    printf 'crossbuild=%s/%s status=passed execution=not-tested\n' "$platform" "$architecture"
  done
done
bridge=/tmp/makersvault-bridge-linux-amd64
test "$("$bridge" --version)" = 'MakersVault Bridge development-gate13b (6306ccff289d475530a6cacf4cb2e28db456ce08)'
for scheme in makersvault-slicer makersvault-engrave makersvault-open; do
  "$bridge" --help | grep -F -- "$scheme://open?"
done
"$bridge" list
"$bridge" doctor
test "$("$bridge" trust list)" = 'No trusted MakersVault origins.'
if "$bridge" trust revoke https://unpaired.invalid; then
  printf 'Unexpected successful revocation of unpaired origin\n' >&2
  exit 1
fi
test "$("$bridge" trust list)" = 'No trusted MakersVault origins.'
"$bridge" --install
cmp "$bridge" /root/.local/bin/makersvault-slicer
grep -Fx 'MimeType=x-scheme-handler/makersvault-slicer;x-scheme-handler/makersvault-engrave;x-scheme-handler/makersvault-open;' \
  /root/.local/share/applications/makersvault-slicer.desktop
test -x /root/.local/bin/makersvault-slicer
/root/.local/bin/makersvault-slicer doctor
printf 'linux-container-cli-and-install=passed native-desktop-launch=not-tested\n'
