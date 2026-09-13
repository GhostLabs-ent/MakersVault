#!/bin/sh
# Cross-compile disposable native tests. No Go/toolchain install on the Mac.
set -eu
test -f /.dockerenv
test "$(pwd)" = /src
export GOTOOLCHAIN=local GOPROXY=off GOCACHE=/tmp/mp-mac-cache GOPATH=/tmp/mp-mac-path
export CGO_ENABLED=0 GOOS=darwin GOARCH=amd64
id
go version
mkdir -p /tmp/mp-mac-payload/internal/printerpreset/testdata /tmp/mp-mac-payload/internal/presetfiles /tmp/mp-mac-payload/internal/presetworker
for package in printerpreset presetfiles presetworker; do
  go test -c -o "/tmp/mp-mac-payload/internal/$package/native.test" "./internal/$package"
done
go build -o /tmp/mp-mac-payload/test2json cmd/test2json
cp internal/printerpreset/testdata/base.json internal/printerpreset/testdata/common.json internal/printerpreset/testdata/child.json /tmp/mp-mac-payload/internal/printerpreset/testdata/
cp /native-run.sh /tmp/mp-mac-payload/run.sh
tar -czf /evidence/native-tests.tar.gz -C /tmp/mp-mac-payload .
printf 'native-payload=darwin/amd64 three-test-binaries-and-test2json compiled race-detector=not-built\n'
