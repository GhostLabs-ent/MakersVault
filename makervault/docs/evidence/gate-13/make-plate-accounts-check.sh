#!/bin/sh
# MP-1b-7: offline, unprivileged, source-bound account/hint verification.
set -eu
test -f /.dockerenv
test "$(pwd)" = /src
test -f /mount-fixture/child.json
test -f /location-mount/system/BBL.json
test -f /accounts-mount/user/fixture-account/README.txt
test -f /account-child-mount/user/fixture-account/README.txt
export GOTOOLCHAIN=local GOPROXY=off GOCACHE=/tmp/mp1b7-go-cache GOPATH=/tmp/mp1b7-go-path
id
go version
test -z "$(gofmt -l internal/printerpreset internal/presetfiles internal/presetworker)"
go test -count=1 -race -json ./...
go vet ./...
if [ "${1:-}" = preflight ]; then exit 0; fi
revision="${1:?exact source revision required}"
for platform in linux windows darwin; do
  for architecture in amd64 arm64; do
    for package in printerpreset presetfiles presetworker; do
      CGO_ENABLED=0 GOOS="$platform" GOARCH="$architecture" go test -c \
        -o "/tmp/makersvault-$package-$platform-$architecture" "./internal/$package"
    done
    CGO_ENABLED=0 GOOS="$platform" GOARCH="$architecture" go build \
      -ldflags "-X main.version=development-mp1b7 -X main.revision=$revision" \
      -o "/tmp/makersvault-bridge-$platform-$architecture" ./cmd/slicer-bridge
    printf 'crossbuild=%s/%s bridge-and-three-test-binaries=passed native-execution=not-tested\n' "$platform" "$architecture"
  done
done
mkdir /tmp/mp1b7-fuzz
cp go.mod /tmp/mp1b7-fuzz/go.mod
cp -R internal /tmp/mp1b7-fuzz/internal
cd /tmp/mp1b7-fuzz
for pair in printerpreset:FuzzBambuProjection presetfiles:FuzzPortableJSONName presetfiles:FuzzWindowsRootSyntax presetworker:FuzzWorkerFrame presetfiles:FuzzBambuManifest presetfiles:FuzzBambuLocations printerpreset:FuzzBambuIndexedSelections printerpreset:FuzzBambuSavedUserMachine presetfiles:FuzzAccountChoices; do
  package="${pair%%:*}"
  target="${pair#*:}"
  if go test -parallel=2 -run '^$' -fuzz "$target" -fuzztime=5s "./internal/$package"; then
    printf 'bounded-fuzz=%s passed requested-duration=5s native-device=not-tested\n' "$target"
  else
    if [ -d "internal/$package/testdata/fuzz" ]; then cp -R "internal/$package/testdata/fuzz" "/evidence/$target-failure-corpus"; fi
    exit 1
  fi
done
