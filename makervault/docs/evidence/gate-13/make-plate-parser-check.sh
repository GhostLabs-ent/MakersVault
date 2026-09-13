#!/bin/sh
# Run only in a disposable network-disabled container, source mounted read-only.
set -eu
test -f /.dockerenv
test "$(pwd)" = /src
export GOTOOLCHAIN=local GOPROXY=off
go version
go test -count=1 -race -json ./...
if [ "${1:-}" = preflight ]; then exit 0; fi
revision="${1:?exact source revision required}"
go vet ./...
for platform in linux windows darwin; do
  for architecture in amd64 arm64; do
    CGO_ENABLED=0 GOOS="$platform" GOARCH="$architecture" go test -c \
      -o "/tmp/makersvault-parser-$platform-$architecture" ./internal/printerpreset
    CGO_ENABLED=0 GOOS="$platform" GOARCH="$architecture" go build \
      -ldflags "-X main.version=development-mp1a -X main.revision=$revision" \
      -o "/tmp/makersvault-bridge-$platform-$architecture" ./cmd/slicer-bridge
    printf 'crossbuild=%s/%s bridge-and-parser=passed native-execution=not-tested\n' "$platform" "$architecture"
  done
done
# Fuzz only the new package in a generated, writable copy; never mutate /src.
mkdir /tmp/mp1a-fuzz
cp go.mod /tmp/mp1a-fuzz/go.mod
cp -R internal/printerpreset /tmp/mp1a-fuzz/printerpreset
cd /tmp/mp1a-fuzz
if go test -parallel=2 -run '^$' -fuzz FuzzBambuProjection -fuzztime=5s ./printerpreset; then
  printf 'bounded-fuzz=passed duration=5s native-device=not-tested\n'
else
  # /evidence is the fresh private capture directory, not the repository.
  if [ -d printerpreset/testdata/fuzz ]; then cp -R printerpreset/testdata/fuzz /evidence/fuzz-failure-corpus; fi
  exit 1
fi
