// Reconcile bounded local observations without promoting cross-builds to device passes.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const repository = path.resolve(__dirname, '../../../..');
const app = path.join(repository, 'makervault');
const entry = '8a7fa35271d1d9d00ac0f5c36e208e83f0a6ef02';
const application = '6306ccff289d475530a6cacf4cb2e28db456ce08';
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const read = file => fs.readFileSync(file, 'utf8');
const boundary = ['Makefile', 'makervault/api', 'makervault/web', 'makervault/scripts',
  'makervault/benchmarks', 'makervault/slicer-bridge', 'makervault/docker-compose.yml',
  'makervault/docker-compose.deploy.yml', 'makervault/docker-deploy.yml'];
assert.equal(execFileSync('git', ['diff', '--name-only', application, '--', ...boundary],
  {cwd: repository, encoding: 'utf8'}).trim(), '', 'Application baseline changed; requalify explicitly');
assert([undefined, '--write', '--self-test'].includes(process.argv[2]));
assert(process.argv.length <= 3);
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
let privateChecks = 0;
const runs = {};
const logs = {};
for (const name of ['https', 'bridge', 'operator', 'harness']) {
  const directory = path.join(root, 'containment-platform-' + name);
  assert(!fs.lstatSync(directory).isSymbolicLink());
  assert.equal(fs.statSync(directory).mode & 0o077, 0);
  const resultBytes = fs.readFileSync(path.join(directory, 'result.json'));
  const result = JSON.parse(resultBytes);
  assert.equal(result.exit_code, 0); assert.equal(result.signal, null);
  assert.equal(result.source_revision, entry); assert.equal(result.end_source_revision, entry);
  assert.equal(result.verification_source_status, ''); assert.equal(result.end_verification_source_status, '');
  logs[name] = {};
  for (const artifact of result.artifacts) {
    assert(['stdout.log', 'stderr.log'].includes(artifact.file));
    const file = path.join(directory, artifact.file);
    assert.equal(fs.statSync(file).mode & 0o077, 0);
    const bytes = fs.readFileSync(file);
    assert.equal(bytes.length, artifact.bytes); assert.equal(hash(bytes), artifact.sha256);
    privateChecks++;
    logs[name][artifact.file] = bytes.toString();
  }
  runs[name] = {...result, private_directory: path.basename(directory), result_sha256: hash(resultBytes)};
}
const https = JSON.parse(logs.https['stdout.log']);
assert.equal(https.status, 'passed'); assert.equal(https.revision, application);
assert.equal(https.schema, 17);
assert.deepEqual(https.images, {
  api: 'sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96',
  web: 'sha256:0fcaf5a3e77873767b1359f468568eee514e6341267a17a32db339f3cc281c67',
});
for (const field of ['https_secure_cookie_csrf', 'logout_revocation', 'non_root_api_web']) assert(https[field]);
for (const service of Object.values(https.process_privileges)) {
  for (const process of [service, ...(service.workers || [])]) {
    assert(process.uid > 0); assert(process.no_new_privileges);
    assert(Object.values(process.capabilities).every(value => value === 0));
  }
}
const operator = JSON.parse(logs.operator['stdout.log']);
assert.equal(operator.status, 'passed'); assert.equal(operator.overwrite_refusals, 2);
assert.equal(operator.compose_configs, 3); assert(operator.missing_secrets_rejected);
assert.equal(operator.started_services, false); assert.equal(operator.real_env_or_vault_changed, false);
assert(/Ran 25 tests in [\d.]+s\s+OK\s*$/.test(logs.harness['stderr.log']));
const bridgeLog = logs.bridge['stdout.log'];
const events = bridgeLog.split('\n').filter(line => line.startsWith('{')).map(line => JSON.parse(line));
assert(!events.some(event => ['fail', 'skip'].includes(event.Action)));
const passed = events.filter(event => event.Action === 'pass' && event.Test);
assert(passed.length > 0);
const platforms = ['linux/amd64', 'linux/arm64', 'windows/amd64', 'windows/arm64', 'darwin/amd64', 'darwin/arm64'];
for (const platform of platforms) assert(bridgeLog.includes(`crossbuild=${platform} status=passed execution=not-tested`));
assert(bridgeLog.includes('linux-container-cli-and-install=passed native-desktop-launch=not-tested'));
assert.equal(logs.bridge['stderr.log'].trim(), 'Trusted origin was not found.');
const linuxScript = read(path.join(app, 'slicer-bridge/scripts/install-linux.sh'));
const windowsScript = read(path.join(app, 'slicer-bridge/scripts/install-windows.ps1'));
const pairing = read(path.join(app, 'slicer-bridge/cmd/slicer-bridge/pairing.go'));
const scheme = 'makersvault-open';
assert(!linuxScript.includes(scheme) && !windowsScript.includes(scheme), 'Manual-installer observation changed');
const opener = pairing.slice(pairing.indexOf('func openBrowserURL('));
assert(opener.includes('case "windows":') && opener.includes('case "linux":'));
assert(!opener.includes('case "darwin":') && opener.includes('unsupported OS for pairing'));
const sourceFiles = ['slicer-bridge/README.md', 'slicer-bridge/scripts/install-linux.sh',
  'slicer-bridge/scripts/install-windows.ps1', 'slicer-bridge/cmd/slicer-bridge/pairing.go',
  'slicer-bridge/cmd/slicer-bridge/install_common.go', 'slicer-bridge/cmd/slicer-bridge/install_linux.go',
  'slicer-bridge/cmd/slicer-bridge/install_windows.go'];
const report = {
  schema: 1, date: '2026-09-12', entry_revision: entry, application_revision: application,
  status: 'bounded_checks_passed_platform_qualification_open', runs,
  driver_sha256: Object.fromEntries(['platform-bridge-check.sh', 'platform-operator-check.py'].map(file =>
    [file, hash(fs.readFileSync(path.join(__dirname, file)))])),
  reviewed_source_sha256: Object.fromEntries(sourceFiles.map(file => [file, hash(fs.readFileSync(path.join(app, file)))])),
  https, operator, python_harness_tests: 25,
  bridge: {toolchain: 'go1.26.6 linux/amd64', race_enabled: true,
    top_level_tests: passed.filter(event => !event.Test.includes('/')).length,
    test_and_subtest_pass_events: passed.length, crossbuilds: platforms,
    linux_container_cli_and_descriptor: 'passed', native_desktop_launch: 'not_tested',
    crossbuilt_files_retained_or_distributed: false},
  owner_device: {reported: ['Windows Dell tablet', 'Bambu slicer installed', 'YubiKey available'],
    windows_hello_used: false, windows_version: null, architecture: null, browser_version: null,
    slicer_version: null, key_model: null, user_verification_capability: 'unverified',
    device_results: 'not_tested'},
  findings: [
    {id: 'P01', status: 'source_confirmed_unfixed', issue: 'Linux and Windows manual scripts omit makersvault-open registration; compiled installers include it.'},
    {id: 'P02', status: 'source_confirmed_unfixed', issue: 'macOS first pairing reaches unsupported-OS error in openBrowserURL; Linux tests replace the browser opener.'},
    {id: 'P03', status: 'documentation_drift_unfixed', issue: 'Bridge README implies current binary is published and permits trusted-network HTTP; current production UI requires HTTPS.'},
  ],
  limits: ['No new full API/web suite, browser benchmark, advisory fetch, image rebuild or scan.',
    'Current exact-image native decisions and deadline are unchanged; no release or rebuilt-image waiver.',
    'No physical passkey, Windows/macOS runtime, signing/notarization or real application launch verified.',
    'Disposable generated fixtures only; no user vault, host protocol handlers or existing deployment modified.',
    'No public candidate selected, retained crossbuilt distribution, push, tag, publication or deployment.',
    'Gate 13C/13D and S04/G13-04 remain open; Gate 12 desktop deferral and G13-01 performance deferral unchanged.'],
};
const output = path.join(__dirname, 'platform-qualification.json');
if (process.argv[2] === '--write') fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n', {flag: 'wx'});
else assert.deepEqual(JSON.parse(read(output)), report);
let negatives = 0;
if (process.argv[2] === '--self-test') for (const mutate of [
  value => { value.owner_device.device_results = 'passed'; },
  value => { value.bridge.native_desktop_launch = 'passed'; },
  value => { value.https.images.api = value.https.images.web; },
  value => { value.findings[1].status = 'fixed'; },
]) { const copy = structuredClone(report); mutate(copy); assert.throws(() => assert.deepEqual(copy, report)); negatives++; }
let links = 0;
for (const file of ['PLATFORM_OPERATOR_RESULTS.md', 'WINDOWS_TABLET_CHECKLIST.md']) {
  for (const match of read(path.join(__dirname, file)).matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if (/^(https?:|#)/.test(match[1])) continue;
    assert(fs.existsSync(path.resolve(__dirname, decodeURIComponent(match[1].split('#')[0]))), match[1]); links++;
  }
}
assert(/\| T-078[^\n]+\n\| T-079/.test(read(path.join(app, 'docs/ARCHITECTURE_RUNBOOK.md'))));
console.log(JSON.stringify({status: 'passed', qualification: report.status, private_log_hash_checks: privateChecks,
  result_hashes: Object.keys(runs).length, bridge_tests: report.bridge.top_level_tests,
  bridge_subtests_inclusive: passed.length, crossbuilds: platforms.length, python_tests: 25, local_links: links, negative_controls: negatives}));
