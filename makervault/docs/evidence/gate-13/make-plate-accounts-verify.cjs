// Read-only MP-1b-7 source/capture join; historical slice records stay unchanged.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const repository = path.resolve(__dirname, '../../../..');
const index = JSON.parse(fs.readFileSync(path.join(__dirname, 'make-plate-accounts-verification.json'), 'utf8'));
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
const git = (...args) => execFileSync('git', args, {cwd:repository, encoding:'utf8'}).trim();
assert.equal(index.schema_version, 1);
assert.equal(index.gate, 'MP-1b-7');
assert.equal(index.private_evidence_root, root);
assert.match(index.implementation_revision, /^[0-9a-f]{40}$/);
assert.equal(index.entry_revision, 'c52722c202732ed4f30a03d2164cd6e272a337e3');
const sources = ['makervault/api', 'makervault/web', 'makervault/slicer-bridge',
  'makervault/docs/evidence/gate-13/make-plate-accounts-check.sh',
  'makervault/docs/evidence/gate-13/security-hardening-run.cjs'];
assert.equal(git('status', '--porcelain', '--', ...sources), '');
git('diff', '--exit-code', index.implementation_revision, '--', ...sources);
git('diff', '--exit-code', index.entry_revision, '--', 'makervault/api', 'makervault/web',
  'makervault/slicer-bridge/cmd', 'makervault/slicer-bridge/go.mod',
  'makervault/slicer-bridge/internal/printerpreset',
  'makervault/slicer-bridge/internal/presetfiles/locations.go',
  'makervault/slicer-bridge/internal/presetworker/supervisor.go');
assert.deepEqual(index.captures.map(c => c.kind), ['preflight', 'final']);
let hashes = 0;
for (const capture of index.captures) {
  assert.equal(capture.directory, `containment-mp1b7-accounts-${capture.kind}-20260914`);
  const directory = path.join(root, capture.directory);
  const result = JSON.parse(fs.readFileSync(path.join(directory, 'result.json'), 'utf8'));
  assert.equal(result.exit_code, 0);
  assert.equal(result.signal, null);
  assert.equal(result.command[0], 'docker');
  assert(result.command.includes(index.go_image));
  assert.equal(result.command[result.command.indexOf('--network')+1], 'none');
  assert.equal(result.command[result.command.indexOf('--user')+1], '1000:1000');
  assert.equal(result.command[result.command.indexOf('--pull')+1], 'never');
  const app = path.join(repository, 'makervault');
  const mounts = [
    [app+'/slicer-bridge', '/src'], [app+'/docs/evidence/gate-13', '/checks'],
    [app+'/slicer-bridge/internal/printerpreset/testdata', '/mount-fixture'],
    [app+'/slicer-bridge/internal/printerpreset/testdata/child.json', '/mount-fixture/child.json'],
    [app+'/slicer-bridge/internal/presetfiles/testdata/location', '/location-mount'],
    [app+'/slicer-bridge/internal/presetfiles/testdata/location/system', '/location-mount/system'],
    [app+'/slicer-bridge/internal/presetfiles/testdata/accounts', '/accounts-mount'],
    [app+'/slicer-bridge/internal/presetfiles/testdata/accounts/user', '/accounts-mount/user'],
    [app+'/slicer-bridge/internal/presetfiles/testdata/accounts', '/account-child-mount'],
    [app+'/slicer-bridge/internal/presetfiles/testdata/accounts/user/fixture-account', '/account-child-mount/user/fixture-account'],
  ];
  for (const [source, target] of mounts) assert(result.command.includes(source+':'+target+':ro'));
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
  assert.equal(result.source_revision, result.end_source_revision);
  assert.equal(result.verification_source_status, result.end_verification_source_status);
  for (const name of ['TestAccountsAreNamesOnlyAndNeverSelected', 'TestAccountsEmptyMissingAndInvalidRoot',
    'TestAccountsEntryBudgetIncludesSidecars', 'TestAccountsRejectUnsafeEntriesAtomically',
    'TestAccountsUseHeldParentAndDetectChanges', 'TestAccountsPermissionsAndNoDescent',
    'TestAccountsRejectSameDeviceBind', 'TestNativeHintsRemainUnobservedAndRedacted',
    'TestNativeHintCancellation', 'TestLinuxHintLookupIsNarrow',
    'TestLinuxNativeHintsUseOnlySyntheticEnvironment', 'TestWorkerAccountChoicesRoundTrip',
    'TestWorkerAccountsCannotCarrySelectionAuthority', 'TestWorkerAccountResponseIsStrictAndLocalOnly']) {
    assert(top.some(event => event.Test === name));
  }
  if (capture.kind === 'final') {
    assert.equal(result.source_revision, index.implementation_revision);
    assert.equal(result.verification_source_status, '');
    assert.deepEqual(result.command.slice(-3), ['sh', '/checks/make-plate-accounts-check.sh', index.implementation_revision]);
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
    assert.equal(fuzz.length, 9);
    assert.deepEqual(fuzz, capture.fuzz);
    assert.deepEqual(fuzz.map(f => f.target), ['FuzzBambuProjection', 'FuzzPortableJSONName',
      'FuzzWindowsRootSyntax', 'FuzzWorkerFrame', 'FuzzBambuManifest', 'FuzzBambuLocations',
      'FuzzBambuIndexedSelections', 'FuzzBambuSavedUserMachine', 'FuzzAccountChoices']);
  } else {
    assert.equal(result.source_revision, index.entry_revision);
    assert(result.verification_source_status.includes('internal/presetfiles/accounts.go'));
    assert.deepEqual(result.command.slice(-3), ['sh', '/checks/make-plate-accounts-check.sh', 'preflight']);
  }
}
assert.equal(index.native_windows_tests_executed, 0);
assert.equal(index.native_macos_tests_executed, 0);
console.log(JSON.stringify({gate:index.gate, status:'local_accounts_hints_verified_native_consent_and_mp1b_open', artifact_hashes_checked:hashes}));
