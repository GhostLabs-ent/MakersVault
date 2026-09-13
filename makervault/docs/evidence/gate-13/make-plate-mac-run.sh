#!/bin/sh
# Runs only inside the newly created owner-approved temporary Mac fixture root.
set -eu
umask 077
native_root="$(pwd -P)"
case "$native_root" in /private/tmp/makersvault-mp1b2.??????) ;; *) exit 91 ;; esac
test "$(uname -s)" = Darwin
test "$(uname -m)" = x86_64
export GOMAXPROCS=2 TMPDIR="$native_root"
printf 'native-system='
uname -s
printf 'native-architecture='
uname -m
sw_vers
printf 'native-uid='
id -u
for package in printerpreset presetfiles; do
  cd "$native_root/internal/$package"
  "$native_root/test2json" -t -p "makersvault/slicer-bridge/internal/$package" ./native.test -test.v=test2json -test.parallel=1 -test.timeout=90s
done
cd "$native_root/internal/presetworker"
# Explicitly exclude the two successful-file-reader tests: Darwin has no reader
# yet. The native fail-closed regression replaces neither of those requirements.
worker_tests='^(TestDarwinWorkerRejectsUnimplementedReader|TestWorkerStopsHungProcessAndBlockedInput|TestWorkerCancellationAndBusySlot|TestWorkerOutputBudgetAndDiagnosticRedaction|TestWorkerMalformedOutputAndStartFailure|TestWorkerCancelledBeforeStart|TestWorkerRejectsAmbiguousOrUnboundedFrames|TestWorkerResponseIdentityAndErrorCodes|TestWorkerRequestAuthorityAndSelectionLimits|FuzzWorkerFrame)$'
"$native_root/test2json" -t -p makersvault/slicer-bridge/internal/presetworker ./native.test -test.v=test2json -test.parallel=1 -test.timeout=90s -test.run "$worker_tests"
printf 'native-scope=parser-portable-policy-worker-only reader-success-tests=2-not-run race-detector=not-run\n'
