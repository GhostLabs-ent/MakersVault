#!/bin/sh
# MP-1b-9b-4a: source-bound isolated preparation, never a real desktop UI pass.
set -eu
test -f /.dockerenv
test "$(pwd)" = /src
export GOTOOLCHAIN=local GOPROXY=off GOCACHE=/tmp/mp1b9b3-go-cache GOPATH=/tmp/mp1b9b3-go-path
mode="${1:?preflight or source revision required}"
# Preserve the complete ordinary regression suite and historical build/fuzz driver.
sh /checks/make-plate-async-picker-check.sh "$mode"
test -z "$(gofmt -l qualification internal/presetconsent/qualification_ui.go internal/presetconsent/qualification_ui_test.go)"
tag=makersvault_native_qualification
go list -f '{{.IgnoredGoFiles}}' ./internal/presetconsent
if go list ./qualification/preset-native > /evidence/qualification-default-build-refused.txt 2>&1; then exit 1; fi
go test -tags "$tag" -count=1 -race -json -run '^(Test(UIQualification|Qualification)|FuzzQualificationConsent)' ./internal/presetconsent ./qualification/preset-native
go vet -tags "$tag" ./internal/presetconsent ./qualification/preset-native
CGO_ENABLED=0 go build -tags "$tag" -trimpath -buildvcs=false \
  -ldflags "-X main.sourceRevision=$mode" -o /evidence/preset-native-linux-amd64 ./qualification/preset-native
/evidence/preset-native-linux-amd64 --inspect > /evidence/qualification-inspect.json
if /evidence/preset-native-linux-amd64 --ui-fixture > /evidence/qualification-noninteractive.txt; then exit 1; else test "$?" = 2; fi
if /evidence/preset-native-linux-amd64 --internal-preset-worker-v1 > /evidence/qualification-worker-refused.txt; then exit 1; else test "$?" = 2; fi
if [ "$mode" = preflight ]; then exit 0; fi
for platform in linux windows; do
  for architecture in amd64 arm64; do
    extension=""; if [ "$platform" = windows ]; then extension=.exe; fi
    if [ "$platform/$architecture" != linux/amd64 ]; then
      CGO_ENABLED=0 GOOS="$platform" GOARCH="$architecture" go build -tags "$tag" -trimpath -buildvcs=false \
        -ldflags "-X main.sourceRevision=$mode" -o "/evidence/preset-native-$platform-$architecture$extension" ./qualification/preset-native
    fi
    for package in internal/presetconsent qualification/preset-native; do
      name="${package##*/}"
      CGO_ENABLED=0 GOOS="$platform" GOARCH="$architecture" go test -tags "$tag" -c -o "/tmp/qualification-$name-$platform-$architecture$extension" "./$package"
    done
    printf 'qualification-crossbuild=%s/%s executable-and-two-test-binaries=passed native-ui=not-tested\n' "$platform" "$architecture"
  done
done
mkdir /tmp/mp1b9b4a-fuzz
cp go.mod /tmp/mp1b9b4a-fuzz/go.mod
cp -R internal qualification /tmp/mp1b9b4a-fuzz/
cd /tmp/mp1b9b4a-fuzz
if go test -tags "$tag" -parallel=2 -run '^$' -fuzz FuzzQualificationConsent -fuzztime=5s ./qualification/preset-native; then
  printf 'bounded-fuzz=FuzzQualificationConsent passed requested-duration=5s native-device=not-tested\n'
else
  if [ -d qualification/preset-native/testdata/fuzz ]; then cp -R qualification/preset-native/testdata/fuzz /evidence/qualification-failure-corpus; fi
  exit 1
fi
