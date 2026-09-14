#!/bin/sh
# Reproduce the old public reader's missing-header rejection, using the new test.
set -eu
test -f /.dockerenv
export GOTOOLCHAIN=local GOPROXY=off GOCACHE=/tmp/mp1b6-red-cache GOPATH=/tmp/mp1b6-red-path
taskdir=$(mktemp -d /tmp/makersvault-saved-user-red-XXXXXX)
id
go version
git -C /repository archive 535a0a106197e202036a551e6e83f61fafbe155d makervault/slicer-bridge | tar -x -C "$taskdir"
cp /src/internal/presetfiles/saved_user_io_test.go "$taskdir/makervault/slicer-bridge/internal/presetfiles/saved_user_io_test.go"
cd "$taskdir/makervault/slicer-bridge"
set +e
go test -count=1 -run '^TestSavedUserDirectoryProjection$' -v ./internal/presetfiles > "$taskdir/red.log" 2>&1
status=$?
set -e
cat "$taskdir/red.log"
test "$status" -eq 1
if command -v rg >/dev/null 2>&1; then
  rg -Fq 'saved-user discovery rejected: invalid_machine_identity' "$taskdir/red.log"
else
  grep -Fq 'saved-user discovery rejected: invalid_machine_identity' "$taskdir/red.log"
fi
printf 'negative-control=old-saved-user-header-rejection reproduced old-revision=535a0a106197e202036a551e6e83f61fafbe155d\n'
