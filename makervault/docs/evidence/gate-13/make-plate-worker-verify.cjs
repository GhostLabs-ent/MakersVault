// Read-only join of the exact MP-1b-2 sources, private captures and public index.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const repository = path.resolve(__dirname, '../../../..');
const index = JSON.parse(fs.readFileSync(path.join(__dirname, 'make-plate-worker-verification.json'), 'utf8'));
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
assert.equal(index.schema_version, 1);
assert.equal(index.gate, 'MP-1b-2');
assert.equal(index.private_evidence_root, root);
assert.equal(index.captures.length, 2);
assert.match(index.implementation_revision, /^[0-9a-f]{40}$/);
const sources = ['makervault/api', 'makervault/web', 'makervault/slicer-bridge',
  'makervault/docs/evidence/gate-13/make-plate-worker-check.sh'];
assert.equal(execFileSync('git', ['status', '--porcelain', '--', ...sources],
  {cwd: repository, encoding: 'utf8'}).trim(), '');
execFileSync('git', ['diff', '--exit-code', index.implementation_revision, '--', ...sources],
  {cwd: repository, stdio: 'pipe'});
let hashes = 0;
const summaries = [];
for (const capture of index.captures) {
  assert.match(capture.directory, /^containment-mp1b2-worker-(preflight|final)$/);
  const directory = path.join(root, capture.directory);
  const result = JSON.parse(fs.readFileSync(path.join(directory, 'result.json'), 'utf8'));
  assert.equal(result.exit_code, 0);
  assert.equal(result.signal, null);
  assert.equal(result.command[0], 'docker');
  assert(result.command.includes(index.go_image));
  assert.equal(result.command[result.command.indexOf('--network') + 1], 'none');
  assert.equal(result.command[result.command.indexOf('--user') + 1], '1000:1000');
  assert.equal(result.artifacts.length, 2);
  for (const name of ['stdout.log', 'stderr.log']) {
    const artifact = result.artifacts.find(item => item.file === name);
    assert(artifact);
    const bytes = fs.readFileSync(path.join(directory, name));
    const hash = crypto.createHash('sha256').update(bytes).digest('hex');
    assert.equal(bytes.length, artifact.bytes);
    assert.equal(hash, artifact.sha256);
    if (name === capture.log) assert.equal(hash, capture.sha256);
    if (name === 'stderr.log') assert.equal(bytes.length, 0);
    hashes++;
  }
  const stdout = fs.readFileSync(path.join(directory, 'stdout.log'), 'utf8');
  const lines = stdout.split('\n');
  const events = lines.filter(line => line.startsWith('{')).map(line => JSON.parse(line));
  assert.equal(events.filter(event => event.Action === 'fail' || event.Action === 'skip').length, 0);
  const passes = events.filter(event => event.Action === 'pass' && event.Test);
  const top = passes.filter(event => !event.Test.includes('/'));
  assert.equal(top.filter(event => event.Test.startsWith('Test')).length, capture.unit_tests_passed);
  assert.match(stdout, /uid=1000/);
  if (capture.directory.endsWith('-final')) {
    assert.equal(result.source_revision, index.implementation_revision);
    assert.equal(result.end_source_revision, index.implementation_revision);
    assert.equal(result.verification_source_status, '');
    assert.equal(result.end_verification_source_status, '');
    assert.equal(passes.length, capture.inclusive_pass_events);
    assert.equal(top.length, capture.top_level_test_and_seeded_fuzz_pass_events);
    const builds = lines.filter(line => line.startsWith('crossbuild='));
    assert.equal(builds.length, capture.cross_build_target_combinations);
    for (const platform of ['linux', 'windows', 'darwin']) for (const arch of ['amd64', 'arm64']) {
      assert(builds.includes(`crossbuild=${platform}/${arch} bridge-and-three-test-binaries=passed native-execution=not-tested`));
    }
    assert.equal(capture.cross_build_artifacts, builds.length * 4);
    const completedFuzz = [];
    let lastFuzz = null;
    for (const line of lines) {
      const progress = /^fuzz: elapsed: (\d+)s, execs: (\d+) /.exec(line);
      if (progress) lastFuzz = {reported_elapsed_seconds: Number(progress[1]), executions: Number(progress[2])};
      const completion = /^bounded-fuzz=(\w+) passed requested-duration=(\d+)s native-device=not-tested$/.exec(line);
      if (completion) {
        assert(lastFuzz);
        completedFuzz.push({target: completion[1], requested_seconds: Number(completion[2]), ...lastFuzz});
        lastFuzz = null;
      }
    }
    assert.deepEqual(completedFuzz, capture.fuzz);
    for (const test of ['TestWorkerListAndProjectRoundTrip', 'TestWorkerStopsHungProcessAndBlockedInput',
      'TestWorkerCancellationAndBusySlot', 'TestWorkerOutputBudgetAndDiagnosticRedaction', 'TestWindowsRootSyntax']) {
      assert(top.some(event => event.Test === test));
    }
    assert.equal(capture.native_windows_tests_executed, 0);
  } else {
    assert.equal(result.source_revision, index.entry_revision);
    assert.equal(result.end_source_revision, index.entry_revision);
    assert(result.verification_source_status.includes('internal/presetworker/'));
  }
  summaries.push({capture: capture.directory, unit_tests: capture.unit_tests_passed, exit_code: result.exit_code});
}
console.log(JSON.stringify({gate: index.gate, status: 'evidence_verified_native_windows_and_mp1b_open', log_hashes_checked: hashes, captures: summaries}));
