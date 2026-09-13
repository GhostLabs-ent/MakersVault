#!/bin/sh
set -eu
test -f /.dockerenv
test "$(pwd)" = /src
export GOTOOLCHAIN=local GOPROXY=off GOCACHE=/tmp/mac-reader-cache GOPATH=/tmp/mac-reader-path
export CGO_ENABLED=0 GOOS=darwin GOARCH=amd64
id
go version
test -z "$(gofmt -l internal/presetfiles/directory_darwin.go internal/presetfiles/reader_darwin_test.go)"
for variant in default experiment; do
  tag=""
  if [ "$variant" = experiment ]; then tag=makersvault_darwin_reader_experiment; fi
  for package in printerpreset presetfiles presetworker; do
    mkdir -p "/tmp/mac-reader-payload/$variant/internal/$package"
    go test -c -tags "$tag" -o "/tmp/mac-reader-payload/$variant/internal/$package/native.test" "./internal/$package"
  done
  mkdir -p "/tmp/mac-reader-payload/$variant/internal/printerpreset/testdata"
  cp internal/printerpreset/testdata/base.json internal/printerpreset/testdata/common.json internal/printerpreset/testdata/child.json "/tmp/mac-reader-payload/$variant/internal/printerpreset/testdata/"
done
for package in presetfiles presetworker; do
  GOARCH=arm64 go test -c -tags makersvault_darwin_reader_experiment -o "/tmp/mac-reader-$package-arm64" "./internal/$package"
done
go vet -tags makersvault_darwin_reader_experiment ./internal/...
go build -o /tmp/mac-reader-payload/test2json cmd/test2json
cp /native-run.sh /tmp/mac-reader-payload/run.sh
tar -czf /evidence/native-tests.tar.gz -C /tmp/mac-reader-payload .
printf 'mac-reader-build=passed default-and-experiment=amd64 arm64-experiment=compile-only native-race=not-built\n'
