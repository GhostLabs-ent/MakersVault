#!/bin/sh
set -eu
umask 077
native_root="$(pwd -P)"
case "$native_root" in /private/tmp/makersvault-mp1b3.??????) ;; *) exit 91 ;; esac
test "$(uname -s)" = Darwin
test "$(uname -m)" = x86_64
export GOMAXPROCS=2 TMPDIR="$native_root"
uname -sm
sw_vers
printf 'native-uid='
id -u
default_worker='^(TestDarwinWorkerRejectsUnimplementedReader|TestWorkerStopsHungProcessAndBlockedInput|TestWorkerCancellationAndBusySlot|TestWorkerOutputBudgetAndDiagnosticRedaction|TestWorkerMalformedOutputAndStartFailure|TestWorkerCancelledBeforeStart|TestWorkerRejectsAmbiguousOrUnboundedFrames|TestWorkerResponseIdentityAndErrorCodes|TestWorkerRequestAuthorityAndSelectionLimits|FuzzWorkerFrame)$'
for variant in default experiment; do
  for package in printerpreset presetfiles presetworker; do
    cd "$native_root/$variant/internal/$package"
    filter='.'
    if [ "$variant:$package" = default:presetworker ]; then filter="$default_worker"; fi
    "$native_root/test2json" -t -p "$variant/$package" ./native.test -test.v=test2json -test.parallel=1 -test.timeout=90s -test.run "$filter"
  done
done
printf 'experiment-not-release-qualified=1 default-reader=unsupported counterexamples-are-safety-gaps\n'
