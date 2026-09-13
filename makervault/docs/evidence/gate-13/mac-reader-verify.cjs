// Read-only source/capture verification. No network, SSH, secrets or file writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const repository = path.resolve(__dirname, '../../../..');
const index = JSON.parse(fs.readFileSync(path.join(__dirname, 'mac-reader-verification.json'), 'utf8'));
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
const git = (...args) => execFileSync('git', args, {cwd: repository, encoding: 'utf8'}).trim();
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
assert.equal(index.schema_version, 1);
assert.equal(index.gate, 'MP-1b-3-mac-reader-experiment');
const sources = ['makervault/api', 'makervault/web', 'makervault/slicer-bridge',
  ...['build.sh', 'run.sh', 'transport.cjs', 'flags.pl'].map(name => `makervault/docs/evidence/gate-13/mac-reader-${name}`),
  'makervault/docs/evidence/gate-13/make-plate-worker-check.sh',
  'makervault/docs/evidence/gate-13/security-hardening-run.cjs'];
assert.equal(git('status', '--porcelain', '--', ...sources), '');
git('diff', '--exit-code', index.test_source_revision, '--', ...sources);
// The Linux run belongs to ed97fdc, not a new full rerun at 907cddd.
assert.deepEqual(git('diff', '--name-only', index.prototype_revision, index.test_source_revision).split('\n'), [
  'makervault/docs/evidence/gate-13/mac-reader-flags.pl',
  'makervault/docs/evidence/gate-13/mac-reader-transport.cjs',
  'makervault/slicer-bridge/internal/presetfiles/directory_darwin.go',
  'makervault/slicer-bridge/internal/presetfiles/reader_darwin_test.go']);
assert.equal(index.captures.length, 10);
assert.equal(new Set(index.captures.map(item => item.directory)).size, 10);
const logs = new Map();
let hashes = 0;
for (const capture of index.captures) {
  assert.match(capture.directory, /^containment-mac-reader-(build-(preflight|debug|final|corrected)|native-(preflight|debug|final|corrected)|linux-final|cleanup)$/);
  const directory = path.join(root, capture.directory);
  const result = JSON.parse(fs.readFileSync(path.join(directory, 'result.json'), 'utf8'));
  assert.equal(result.exit_code, capture.exit_code);
  assert.equal(result.signal, null);
  assert.equal(result.source_revision, index[capture.source]);
  assert.equal(result.end_source_revision, result.source_revision);
  assert.equal(result.verification_source_status !== '', capture.dirty_source);
  assert.equal(result.end_verification_source_status, result.verification_source_status);
  if (/-(build-|linux-final)/.test(capture.directory)) {
    assert.equal(result.command[0], 'docker');
    assert(result.command.includes(index.go_image));
    assert.equal(result.command[result.command.indexOf('--network') + 1], 'none');
    assert.equal(result.command[result.command.indexOf('--user') + 1], '1000:1000');
  }
  assert.equal(result.artifacts.length, 2);
  for (const name of ['stdout.log', 'stderr.log']) {
    const bytes = fs.readFileSync(path.join(directory, name));
    const artifact = result.artifacts.find(item => item.file === name);
    assert.equal(bytes.length, artifact.bytes);
    assert.equal(digest(bytes), artifact.sha256);
    if (name === 'stdout.log') {
      assert.equal(bytes.length, capture.stdout_bytes);
      assert.equal(digest(bytes), capture.stdout_sha256);
      logs.set(capture.directory, bytes.toString('utf8'));
    } else assert.equal(bytes.length, 0);
    hashes++;
  }
}
const payload = fs.readFileSync(path.join(root, index.payload.directory, index.payload.file));
assert.equal(payload.length, index.payload.bytes);
assert.equal(digest(payload), index.payload.sha256);
hashes++;
const eventsIn = stdout => stdout.split('\n').filter(line => line.startsWith('{')).map(line => JSON.parse(line));
const passed = events => events.filter(event => event.Action === 'pass' && event.Test);
const topLevel = events => passed(events).filter(event => !event.Test.includes('/'));
for (const label of ['preflight', 'debug', 'final']) {
  const events = eventsIn(logs.get(`containment-mac-reader-native-${label}`));
  assert(events.some(event => event.Action === 'fail' && event.Package === 'experiment/presetfiles'));
  assert(!events.some(event => event.Package === 'experiment/presetworker'));
  assert.equal(topLevel(events).filter(event => event.Package.startsWith('default/') && event.Test.startsWith('Test')).length, 34);
}
const stdout = logs.get('containment-mac-reader-native-corrected');
assert.match(stdout, /Darwin x86_64\n/);
assert.match(stdout, /ProductVersion:\s+15\.7\.9\nBuildVersion:\s+24G830\nnative-uid=501\n/);
const events = eventsIn(stdout);
const transfer = events.find(event => event.payload_sha256);
assert.equal(transfer.payload_sha256, index.payload.sha256);
assert.equal(transfer.payload_bytes, index.payload.bytes);
assert(events.some(event => event.native_transport_exit === 0 && event.signal === null));
assert.equal(events.filter(event => event.Action === 'fail' || event.Action === 'skip').length, 0);
const top = topLevel(events);
assert.equal(passed(events).length, index.native.inclusive_pass_events);
assert.equal(top.length, index.native.top_level_pass_events);
assert.equal(top.filter(event => event.Test.startsWith('Fuzz')).length, index.native.seeded_fuzz_targets);
for (const [package, count] of Object.entries(index.native.packages)) {
  assert.equal(top.filter(event => event.Package === package && event.Test.startsWith('Test')).length, count);
  assert(events.some(event => event.Package === package && event.Action === 'pass' && !event.Test));
}
assert.equal(top.filter(event => event.Package.startsWith('default/') && event.Test.startsWith('Test')).length, index.native.unit_tests_default);
assert.equal(top.filter(event => event.Package.startsWith('experiment/') && event.Test.startsWith('Test')).length, index.native.unit_tests_experiment);
for (const name of ['TestWorkerListAndProjectRoundTrip', 'TestWorkerProjectionIsAtomic']) {
  assert(top.some(event => event.Package === 'experiment/presetworker' && event.Test === name));
  assert(!events.some(event => event.Package === 'default/presetworker' && event.Test === name));
}
assert(top.some(event => event.Package === 'default/presetworker' && event.Test === 'TestDarwinWorkerRejectsUnimplementedReader'));
assert.match(stdout, /safety-property=metadata-only-event-handle FAILED counterexample=FIFO-reader-endpoint-opened/);
assert.match(stdout, /safety-property=no-special-file-open-before-kind-validation FAILED counterexample=postcheck-detects-too-late/);
assert.equal(top.filter(event => event.Test.startsWith('TestDarwinCounterexample')).length, 2);
assert.equal(index.native.counterexamples_of_failed_safety_properties, 2);
assert.equal(index.native.experimental_ordinary_checks, index.native.unit_tests_experiment - 2);
assert.match(stdout, /experiment-not-release-qualified=1 default-reader=unsupported counterexamples-are-safety-gaps/);
const linux = logs.get('containment-mac-reader-linux-final');
const linuxEvents = eventsIn(linux);
assert.equal(linuxEvents.filter(event => event.Action === 'fail' || event.Action === 'skip').length, 0);
assert.equal(passed(linuxEvents).length, index.linux.inclusive_pass_events);
assert.equal(topLevel(linuxEvents).length, index.linux.top_level_pass_events);
assert.equal(topLevel(linuxEvents).filter(event => event.Test.startsWith('Test')).length, index.linux.unit_tests_with_race);
assert.equal((linux.match(/^crossbuild=.+ bridge-and-three-test-binaries=passed/gm) || []).length, 6);
for (const [target, executions] of Object.entries(index.linux.fuzz_executions)) {
  const before = linux.split(`bounded-fuzz=${target} passed requested-duration=5s`);
  assert.equal(before.length, 2);
  const matches = [...before[0].matchAll(/fuzz: elapsed: .* execs: (\d+)/g)];
  assert.equal(Number(matches.at(-1)[1]), executions);
}
assert.equal(logs.get('containment-mac-reader-cleanup'), 'native-reader-cleanup=4-passed');
assert.equal(index.remote_fixture_directories_removed, 4);
assert.equal(index.ssh_master_closed, true);
assert(!fs.existsSync(path.join(root, 'containment-mac-reader/ssh')));
assert.equal(index.native.default_reader_supported, false);
assert.equal(index.native.release_qualified, false);
console.log(JSON.stringify({gate: index.gate, status: index.status, hashes_checked: hashes,
  default_unit_tests: 34, experimental_ordinary_checks: 42, reproduced_safety_gaps: 2,
  remote_fixture_cleanup: 'four directories removed; local artifacts retained'}));
