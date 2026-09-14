// Read-only MP-1b-4 source/capture join; prior manifest/Mac records stay historical.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const repository = path.resolve(__dirname, '../../../..');
const index = JSON.parse(fs.readFileSync(path.join(__dirname, 'make-plate-locations-verification.json'), 'utf8'));
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
const git = (...args) => execFileSync('git', args, {cwd:repository, encoding:'utf8'}).trim();
assert.equal(index.schema_version, 1);
assert.equal(index.gate, 'MP-1b-4');
assert.equal(index.private_evidence_root, root);
assert.match(index.implementation_revision, /^[0-9a-f]{40}$/);
const sources = ['makervault/api', 'makervault/web', 'makervault/slicer-bridge',
  'makervault/docs/evidence/gate-13/make-plate-locations-check.sh',
  'makervault/docs/evidence/gate-13/security-hardening-run.cjs'];
assert.equal(git('status', '--porcelain', '--', ...sources), '');
git('diff', '--exit-code', index.implementation_revision, '--', ...sources);
git('diff', '--exit-code', index.entry_revision, '--', 'makervault/api', 'makervault/web',
  'makervault/slicer-bridge/cmd', 'makervault/slicer-bridge/go.mod',
  'makervault/slicer-bridge/internal/printerpreset');
assert.equal(index.captures.length, 2);
assert.deepEqual(index.captures.map(c => c.kind), ['preflight', 'final']);
let hashes = 0;
for (const capture of index.captures) {
  assert.equal(capture.directory, `containment-mp1b4-locations-${capture.kind}-20260913`);
  const directory = path.join(root, capture.directory);
  const result = JSON.parse(fs.readFileSync(path.join(directory, 'result.json'), 'utf8'));
  assert.equal(result.exit_code, 0);
  assert.equal(result.signal, null);
  assert.equal(result.command[0], 'docker');
  assert(result.command.includes(index.go_image));
  assert.equal(result.command[result.command.indexOf('--network')+1], 'none');
  assert.equal(result.command[result.command.indexOf('--user')+1], '1000:1000');
  assert(result.command.includes(path.join(repository, 'makervault/slicer-bridge')+':/src:ro'));
  const fixture = path.join(repository, 'makervault/slicer-bridge/internal/presetfiles/testdata/location');
  assert(result.command.includes(fixture+':/location-mount:ro'));
  assert(result.command.includes(fixture+'/system:/location-mount/system:ro'));
  assert.deepEqual(result.artifacts.map(a => a.file).sort(), ['stderr.log', 'stdout.log']);
  for (const artifact of result.artifacts) {
    const bytes = fs.readFileSync(path.join(directory, artifact.file));
    const hash = crypto.createHash('sha256').update(bytes).digest('hex');
    assert.equal(hash, artifact.sha256);
    assert.equal(bytes.length, artifact.bytes);
    if (artifact.file === 'stdout.log') assert.equal(hash, capture.stdout_sha256);
    else assert.equal(bytes.length, 0);
    hashes++;
  }
  const stdout = fs.readFileSync(path.join(directory, 'stdout.log'), 'utf8');
  const lines = stdout.split('\n');
  const events = lines.filter(line => line.startsWith('{')).map(line => JSON.parse(line));
  assert.equal(events.filter(event => event.Action === 'fail' || event.Action === 'skip').length, 0);
  const passes = events.filter(event => event.Action === 'pass' && event.Test);
  const top = passes.filter(event => !event.Test.includes('/'));
  assert.equal(top.filter(event => event.Test.startsWith('Test')).length, capture.unit_tests_passed);
  assert.equal(top.length, capture.top_level_pass_events);
  assert.equal(passes.length, capture.inclusive_pass_events);
  assert.match(stdout, /uid=1000/);
  assert.match(stdout, /go version go1\.26\.6 linux\/amd64/);
  if (capture.kind === 'final') {
    assert.equal(result.source_revision, index.implementation_revision);
    assert.equal(result.end_source_revision, index.implementation_revision);
    assert.equal(result.verification_source_status, '');
    assert.equal(result.end_verification_source_status, '');
    assert.deepEqual(result.command.slice(-3), ['sh', '/checks/make-plate-locations-check.sh', index.implementation_revision]);
    const builds = lines.filter(line => line.startsWith('crossbuild='));
    assert.equal(builds.length, 6);
    for (const platform of ['linux', 'windows', 'darwin']) for (const arch of ['amd64', 'arm64']) {
      assert(builds.includes(`crossbuild=${platform}/${arch} bridge-and-three-test-binaries=passed native-execution=not-tested`));
    }
    const fuzz = [];
    let progress;
    for (const line of lines) {
      const p = /^fuzz: elapsed: (\d+)s, execs: (\d+) /.exec(line);
      if (p) progress = {reported_elapsed_seconds:Number(p[1]), executions:Number(p[2])};
      const done = /^bounded-fuzz=(\w+) passed requested-duration=5s native-device=not-tested$/.exec(line);
      if (done) {
        assert(progress);
        fuzz.push({target:done[1], requested_seconds:5, ...progress});
        progress = null;
      }
    }
    assert.equal(fuzz.length, 6);
    assert.deepEqual(fuzz, capture.fuzz);
    for (const name of ['TestLocationRejectsSameDeviceDirectoryBind', 'TestLocationSharedEntryBudget',
      'TestLocationChildUsesHeldParent', 'TestLocationPermissionsDoNotFallBack',
      'TestWorkerLocationRoundTripAndAtomicFailure', 'TestWorkerLocationRequestAndResponseFraming']) {
      assert(top.some(event => event.Test === name));
    }
  } else {
    assert.equal(result.source_revision, index.entry_revision);
    assert.equal(result.end_source_revision, index.entry_revision);
    assert(result.verification_source_status.includes('internal/presetfiles/reader.go'));
    assert.deepEqual(result.command.slice(-3), ['sh', '/checks/make-plate-locations-check.sh', 'preflight']);
  }
}
assert.equal(index.native_windows_tests_executed, 0);
assert.equal(index.native_macos_tests_executed, 0);
console.log(JSON.stringify({gate:index.gate, status:'location_substep_verified_profile_discovery_and_mp1b_open', artifact_hashes_checked:hashes}));
