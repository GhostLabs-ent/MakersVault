#!/bin/sh
# Disposable container only; source mounted read-only, no actual user profiles.
set -eu
test -f /.dockerenv
test "$(pwd)" = /src
export GOTOOLCHAIN=local GOPROXY=off GOCACHE=/tmp/mp1b1-go-cache GOPATH=/tmp/mp1b1-go-path
test -f /mount-fixture/child.json
id
go version
go test -count=1 -race -json ./...
if [ "${1:-}" = preflight ]; then exit 0; fi
revision="${1:?exact source revision required}"
go vet ./...
for platform in linux windows darwin; do
  for architecture in amd64 arm64; do
    for package in printerpreset presetfiles; do
      CGO_ENABLED=0 GOOS="$platform" GOARCH="$architecture" go test -c \
        -o "/tmp/makersvault-$package-$platform-$architecture" "./internal/$package"
    done
    CGO_ENABLED=0 GOOS="$platform" GOARCH="$architecture" go build \
      -ldflags "-X main.version=development-mp1b1 -X main.revision=$revision" \
      -o "/tmp/makersvault-bridge-$platform-$architecture" ./cmd/slicer-bridge
    printf 'crossbuild=%s/%s bridge-and-two-test-binaries=passed native-execution=not-tested\n' "$platform" "$architecture"
  done
done
mkdir /tmp/mp1b1-fuzz
cp go.mod /tmp/mp1b1-fuzz/go.mod
cp -R internal /tmp/mp1b1-fuzz/internal
cd /tmp/mp1b1-fuzz
for package in printerpreset presetfiles; do
  if go test -parallel=2 -run '^$' -fuzz Fuzz -fuzztime=5s "./internal/$package"; then
    printf 'bounded-fuzz=%s passed requested-duration=5s native-device=not-tested\n' "$package"
  else
    if [ -d "internal/$package/testdata/fuzz" ]; then cp -R "internal/$package/testdata/fuzz" "/evidence/$package-failure-corpus"; fi
    exit 1
  fi
done
