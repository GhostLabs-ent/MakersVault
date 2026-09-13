// Read-only exact-source/capture join. Does not connect to the Mac or use secrets.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const repository = path.resolve(__dirname, '../../../..');
const index = JSON.parse(fs.readFileSync(path.join(__dirname, 'make-plate-mac-verification.json'), 'utf8'));
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
const git = (...args) => execFileSync('git', args, {cwd: repository, encoding: 'utf8'}).trim();
assert.equal(index.schema_version, 1);
assert.equal(index.gate, 'MP-1b-2-mac-native');
const sources = ['makervault/api', 'makervault/web', 'makervault/slicer-bridge',
  ...['build.sh', 'run.sh', 'transport.cjs'].map(name => `makervault/docs/evidence/gate-13/make-plate-mac-${name}`)];
assert.equal(git('status', '--porcelain', '--', ...sources), '');
git('diff', '--exit-code', index.test_source_revision, '--', ...sources);
assert.equal(git('diff', '--name-only', index.runtime_implementation_revision, '--', 'makervault/api', 'makervault/web', 'makervault/slicer-bridge'),
  'makervault/slicer-bridge/internal/presetworker/worker_darwin_test.go');
assert.equal(index.captures.length, 4);
const logs = new Map();
let hashes = 0;
for (const capture of index.captures) {
  assert.match(capture.directory, /^containment-mac-native-(build|build-final|run|cleanup)$/);
  const directory = path.join(root, capture.directory);
  const result = JSON.parse(fs.readFileSync(path.join(directory, 'result.json'), 'utf8'));
  assert.equal(result.exit_code, capture.exit_code);
  assert.equal(result.exit_code, 0);
  assert.equal(result.signal, null);
  assert.equal(result.end_source_revision, result.source_revision);
  assert.equal(result.end_verification_source_status, result.verification_source_status);
  if (capture.final_source) {
    assert.equal(result.source_revision, index.test_source_revision);
    assert.equal(result.verification_source_status, '');
  } else {
    assert.equal(result.source_revision, index.entry_revision);
    assert.equal(result.verification_source_status, '?? makervault/slicer-bridge/internal/presetworker/worker_darwin_test.go');
  }
  if (capture.directory.includes('-build')) {
    assert.equal(result.command[0], 'docker');
    assert(result.command.includes(index.go_image));
    assert.equal(result.command[result.command.indexOf('--network') + 1], 'none');
    assert.equal(result.command[result.command.indexOf('--user') + 1], '1000:1000');
  }
  assert.equal(result.artifacts.length, 2);
  for (const name of ['stdout.log', 'stderr.log']) {
    const bytes = fs.readFileSync(path.join(directory, name));
    const artifact = result.artifacts.find(item => item.file === name);
    const digest = crypto.createHash('sha256').update(bytes).digest('hex');
    assert.equal(bytes.length, artifact.bytes);
    assert.equal(digest, artifact.sha256);
    if (name === 'stdout.log') {
      assert.equal(bytes.length, capture.stdout_bytes);
      assert.equal(digest, capture.stdout_sha256);
      logs.set(capture.directory, bytes.toString('utf8'));
    } else assert.equal(bytes.length, 0);
    hashes++;
  }
}
const payload = fs.readFileSync(path.join(root, index.payload.directory, index.payload.file));
assert.equal(payload.length, index.payload.bytes);
assert.equal(crypto.createHash('sha256').update(payload).digest('hex'), index.payload.sha256);
hashes++;
const stdout = logs.get('containment-mac-native-run');
assert.match(stdout, /native-system=Darwin\nnative-architecture=x86_64\n/);
assert.match(stdout, /ProductVersion:\s+15\.7\.9\nBuildVersion:\s+24G830\nnative-uid=501\n/);
const events = stdout.split('\n').filter(line => line.startsWith('{')).map(line => JSON.parse(line));
const transfer = events.find(event => event.payload_sha256);
assert.equal(transfer.payload_sha256, index.payload.sha256);
assert.equal(transfer.payload_bytes, index.payload.bytes);
assert(events.some(event => event.native_transport_exit === 0 && event.signal === null));
assert.equal(events.filter(event => event.Action === 'fail' || event.Action === 'skip').length, 0);
const passes = events.filter(event => event.Action === 'pass' && event.Test);
const top = passes.filter(event => !event.Test.includes('/'));
assert.equal(passes.length, index.native.inclusive_pass_events);
assert.equal(top.length, index.native.top_level_pass_events);
assert.equal(top.filter(event => event.Test.startsWith('Test')).length, index.native.unit_tests_passed);
assert.equal(top.filter(event => event.Test.startsWith('Fuzz')).length, index.native.seeded_fuzz_targets);
for (const [name, count] of Object.entries(index.native.packages)) {
  const package = `makersvault/slicer-bridge/internal/${name}`;
  assert.equal(top.filter(event => event.Package === package && event.Test.startsWith('Test')).length, count);
  assert(events.some(event => event.Package === package && event.Action === 'pass' && !event.Test));
}
for (const name of index.native.explicitly_not_run) assert(!events.some(event => event.Test === name));
for (const name of ['TestDarwinWorkerRejectsUnimplementedReader', 'TestNativeBackendFailsClosed',
  'TestWorkerStopsHungProcessAndBlockedInput', 'TestWorkerCancellationAndBusySlot', 'TestWorkerOutputBudgetAndDiagnosticRedaction']) {
  assert(top.some(event => event.Test === name));
}
assert.match(stdout, /reader-success-tests=2-not-run race-detector=not-run/);
assert.equal(logs.get('containment-mac-native-cleanup'), 'native-fixture-cleanup=passed');
assert.equal(index.native.macos_file_reader_implemented, false);
console.log(JSON.stringify({gate: index.gate, status: index.status, hashes_checked: hashes,
  native_unit_tests: index.native.unit_tests_passed, successful_reader_tests_not_run: 2, remote_fixture_cleanup: 'passed'}));
