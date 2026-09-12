// Verify the remaining-five evidence and proposal without accepting any risk.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const local = name => read(path.join(__dirname, name));
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
const repo = path.resolve(__dirname, '../../../..');
const revision = '5985cef77a043c361e5775d44f85f5ca4348e6ec';
assert(process.argv.length <= 3 && [undefined, '--print-proposal', '--self-test'].includes(process.argv[2]));
const priorCheck = JSON.parse(execFileSync(process.execPath,
  [path.join(__dirname, 'security-hold-approval-check.cjs')], {encoding: 'utf8'}));
assert.equal(priorCheck.status, 'passed');
const event = local('security-hold-owner-acceptance-2026-09-12.json');
const proposal = local('security-current-decision-proposal.json');
const ids = event.unaccepted_holds;
assert.equal(ids.length, 5);
let privateHashes = 0;
const privateSha = file => {
  assert(!fs.lstatSync(file).isSymbolicLink()); assert.equal(fs.statSync(file).mode & 0o077, 0);
  privateHashes++; return sha(file);
};
const vendorRoot = path.join(root, 'containment-remaining-vendor');
const runtimeRoot = path.join(root, 'containment-remaining-runtime');
for (const directory of [root, vendorRoot, runtimeRoot]) {
  assert(!fs.lstatSync(directory).isSymbolicLink()); assert.equal(fs.statSync(directory).mode & 0o077, 0);
}
const vendor = read(path.join(vendorRoot, 'summary.json'));
const vendorHashes = {'summary.json': privateSha(path.join(vendorRoot, 'summary.json'))};
assert.equal(vendor.entry_revision, revision); assert.equal(vendor.end_revision, revision);
assert.equal(vendor.script_sha256, sha(path.join(__dirname, 'security-remaining-vendor.cjs')));
assert.equal(Object.keys(vendor.captures).length, 12);
const pages = {};
for (const [key, row] of Object.entries(vendor.captures)) {
  assert.equal(row.status, 'captured'); assert.equal(row.http_status, 200);
  assert.equal(path.basename(row.file), row.file);
  const file = path.join(vendorRoot, row.file);
  vendorHashes[row.file] = privateSha(file); assert.equal(vendorHashes[row.file], row.sha256);
  assert.equal(fs.statSync(file).size, row.bytes);
  pages[key] = fs.readFileSync(file, 'utf8').replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/&amp;/g, '&');
}
for (const id of ids) {
  const expected = id.endsWith('50812') ? '3.46.1-7+deb13u2' : '2.41-12+deb13u4';
  assert.deepEqual(vendor.captures['debian-' + id].trixie_rows, ['trixie ' + expected + ' vulnerable']);
}
assert(pages['redhat-CVE-2026-19499'].includes('strfmon'));
assert(pages['redhat-CVE-2026-19542'].includes('tdelete'));
for (const id of ['CVE-2026-77117', 'CVE-2026-80489']) {
  assert(pages['redhat-' + id].includes('SHIFT_JISX0213')); assert(pages['redhat-' + id].includes('E2BIG'));
}
assert(pages['redhat-CVE-2026-80489'].includes('EUC_JISX0213'));
assert(pages['ubuntu-CVE-2026-80489'].includes('euc-jisx0213.c'));
assert(pages['ubuntu-CVE-2026-50812'].includes('3.46.1-9ubuntu0.2'));
assert(pages['sqlite-fix'].includes('e807d4e3798efd532b3d78d1dfe513ed4fbd3cb793dd0ae5c30cae6031422b10'));
const sqliteDiff = pages['sqlite-fix'].replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/<[^>]+>/g, '');
assert(sqliteDiff.includes('pOld && (p->abPK[i] || bPatchset==0)'));
assert(pages['sqlite-fix'].includes('sqlite3changeset_apply_v2'));
const run = read(path.join(runtimeRoot, 'result.json'));
const runtimeHashes = Object.fromEntries(['started.json', 'result.json', 'stdout.log', 'stderr.log']
  .map(file => [file, privateSha(path.join(runtimeRoot, file))]));
assert.equal(run.exit_code, 0); assert.equal(run.source_revision, revision); assert.equal(run.end_source_revision, revision);
assert.equal(run.verification_source_status, ''); assert.equal(run.end_verification_source_status, '');
assert(run.command.includes(event.images.api));
for (const item of run.artifacts) assert.equal(runtimeHashes[item.file], item.sha256);
const runtime = read(path.join(runtimeRoot, 'stdout.log'));
assert.equal(runtime.status, 'passed_observations_not_disposition');
assert.equal(runtime.script_sha256, sha(path.join(__dirname, 'security-remaining-runtime.py')));
assert.deepEqual(runtime.commands.map(row => row.command[0]), ['apt-get', 'dpkg-query', 'apt-cache', 'iconv']);
for (const row of runtime.commands) assert.equal(row.exit_code, 0);
for (const flag of ['APT::Update::Error-Mode=any', 'Acquire::AllowInsecureRepositories=false', 'APT::Get::AllowUnauthenticated=false', 'update'])
  assert(runtime.commands[0].command.includes(flag));
assert.equal(runtime.installed, 'libc-bin\t2.41-12+deb13u4\tglibc\t2.41-12+deb13u4\nlibc6\t2.41-12+deb13u4\tglibc\t2.41-12+deb13u4\nlibsqlite3-0\t3.46.1-7+deb13u2\tsqlite3\t3.46.1-7+deb13u2\n');
for (const [name, version] of [['libc6', '2.41-12+deb13u4'], ['libc-bin', '2.41-12+deb13u4'], ['libsqlite3-0', '3.46.1-7+deb13u2']])
  assert(runtime.apt_policy.includes(name + ':\n  Installed: ' + version + '\n  Candidate: ' + version + '\n'));
assert.deepEqual(runtime.libc_symbols, {iconv: true, iconv_open: true, strfmon: true, strfmon_l: true, tdelete: true});
for (const row of Object.values(runtime.gconv_modules)) { assert(row.exists); assert.match(row.sha256, /^[0-9a-f]{64}$/); }
assert.deepEqual(Object.keys(runtime.gconv_modules).sort(), ['EUC-JISX0213.so', 'SHIFT_JISX0213.so']);
assert(runtime.iconv_aliases.includes('EUC-JISX0213//')); assert(runtime.iconv_aliases.includes('SHIFT_JISX0213//'));
assert(runtime.sqlite_compile_options.includes('ENABLE_SESSION'));
assert.deepEqual(runtime.python_connection_changeset_members, []);
const sourceReview = local('security-hold-review.json');
const source = read(path.join(root, 'containment-held-source-b/stdout.log'));
const session = source.packages.sqlite3.selected_text['sqlite3-3.46.1/ext/session/sqlite3session.c'];
assert(session.text.includes('if( p->abPK[i] || (bPatchset==0 && pOld) ){'));
assert(!session.text.includes('if( pOld && (p->abPK[i] || bPatchset==0) ){'));
assert(session.text.includes('int eType = sqlite3_value_type(pVal);'));
assert.equal(runtime.library_sha256['/usr/lib/x86_64-linux-gnu/libsqlite3.so.0.8.6'],
  sourceReview.source_proof.sqlite3.installed_file_checks[0].sha256);
const exactPattern = /\b(?:strfmon(?:_l)?|tdelete|iconv(?:_open)?|sqlite3changeset\w*|enable_load_extension|load_extension|ctypes|cffi)\b/i;
assert.equal(vendor.direct_api_source_review.files.length, 51);
let broadHits = 0;
for (const row of vendor.direct_api_source_review.files) {
  const file = path.join(repo, row.file); assert.equal(sha(file), row.sha256);
  assert(!exactPattern.test(fs.readFileSync(file, 'utf8')));
  for (const hit of row.hits) { assert(hit.text.includes('PermanentDelete')); broadHits++; }
}
assert.equal(broadHits, 18);
const rationales = {
  'CVE-2026-19499': {path: 'glibc strfmon/strfmon_l right-justified monetary formatting',
    impact: 'Buffer overwrite; potential native memory corruption, data loss or code execution if a susceptible formatting path receives the required input.',
    finding: 'CNA details now identify the function and formatting preconditions. Both symbols are present; no exact-image exclusion is established.'},
  'CVE-2026-19542': {path: 'glibc tdelete tree removal and stack array management',
    impact: 'Out-of-bounds stack write; native memory corruption, denial of service or information disclosure.',
    finding: 'CNA details identify the tree-deletion defect. tdelete is present; direct API token search does not resolve native internal callers.'},
  'CVE-2026-50812': {path: 'SQLite Session Extension corrupt changeset application',
    impact: 'NULL pointer dereference and process denial of service when a malformed changeset reaches the affected shared apply code.',
    finding: 'Authenticated 3.46.1 source contains the exact pre-fix guard and unchecked value-type call. Upstream regression uses apply_v2; absent apply_v3 is not an exclusion. Python connection lacks a changeset API, not the native library.'},
  'CVE-2026-77117': {path: 'glibc SHIFT_JISX0213 conversion retry state',
    impact: 'Non-progress loop/resource consumption when untrusted text reaches the converter and its caller repeatedly retries E2BIG with insufficient output space.',
    finding: 'SHIFT_JISX0213 converter and alias are installed. No complete native retry-path exclusion is proved.'},
  'CVE-2026-80489': {path: 'glibc JISX0213 conversion retry state; retain SHIFT/EUC mapping disagreement',
    impact: 'Non-progress loop and process/resource denial of service under the described limited-output conversion/retry conditions.',
    finding: 'Red Hat prose names SHIFT_JISX0213 while its bug title and Ubuntu identify EUC_JISX0213. Both converters are installed; neither interpretation supports a missing-component exclusion.'},
};
const rows = ids.map(id => ({id, ...rationales[id], matches: proposal.records.find(row => row.id === id).matches,
  current_bucket: 'H', proposed_bucket: 'R', owner_decision: 'pending', accepted_by: null,
  rationale: 'Temporary local qualification only under unchanged C1-C7; no direct named API call identified in the bounded Python review, with native/dependency and operator-recovery uncertainty explicitly retained. Latest configured signed APT candidate equals installed, and Debian still marks it vulnerable.',
  not_claimed: 'Not fixed, excluded, unreachable, vendor-mitigated or safe for public deployment. Authentication and empty capabilities do not remove native or denial-of-service risk.',
  review_due_if_accepted: event.review_deadline.not_after}));
const report = {schema: 1, status: 'five_temporary_local_risk_exceptions_proposed_none_accepted', reviewed_date: '2026-09-12',
  entry_revision: revision, application_revision: event.application_revision, images: event.images, platform: event.platform,
  input_sha256: Object.fromEntries(['security-hold-owner-acceptance-2026-09-12.json', 'security-hold-review.json', 'security-current-decision-proposal.json']
    .map(file => [file, sha(path.join(__dirname, file))])),
  vendor: {started_at: vendor.started_at, finished_at: vendor.finished_at, captures: vendor.captures, private_sha256: vendorHashes},
  runtime: {run, private_sha256: runtimeHashes, observations: runtime},
  source: {sqlite_session_file_sha256: session.sha256, vulnerable_shared_guard_present: true,
    direct_api_source_review: vendor.direct_api_source_review, broad_identifier_hits: broadHits, exact_named_call_hits: 0},
  counts: {accepted_exclusions: 4, accepted_residuals: 52, verified_fixes: 26, unaccepted_holds: 5, proposed_additional_residuals: 5, new_acceptances: 0},
  conditions: event.conditions, review_deadline: event.review_deadline, records: rows,
  proposed_if_approved: {E: 4, R: 57, F: 26, H: 0},
  required_acknowledgments: ['All five remain potentially applicable; this accepts risk, not a source-precondition exclusion.',
    'Memory corruption, writable-vault/data-loss, information disclosure and process/resource denial of service remain possible; no exploitability or whole-call-graph proof was performed.',
    'The converter naming disagreement and direct-source-review limitation remain explicit.',
    'Exact development images/local qualification only; unchanged October 12-or-earlier deadline. Freeze/rebuild/advisory changes reopen; public release requires its own qualification and decisions.'],
  alternatives: ['Keep H5 open while waiting for applicable supported Debian backports.',
    'Separately approve and qualify a supported patched base or maintained backport plan; no foreign-distribution package mixing, ad-hoc patching or silent migration.'],
  unchanged_scanner: event.scanner_inventory_retained,
  limits: ['The go-ahead authorized investigation, not these newly proposed five risk exceptions.',
    'Previously unavailable endpoints were not retried; new readable CNA/Ubuntu/upstream endpoints supplied additional evidence.',
    'No package/image/schema/model-byte change, full-suite repeat, new scanner run, exploit execution, source build, push, publication or deployment.',
    'The disposable root/resource probe settings are not product defaults; there was no host-vault mount or application startup.',
    'Earlier E/R events and proposal JSON remain unchanged. This bounded review is not a fresh review of every accepted CVE.',
    'Even approval would only complete local native dispositions, not close S04/G13-04 or Gate 13C/13D or grant public-release clearance.']};
if (process.argv[2] === '--print-proposal') console.log(JSON.stringify(report, null, 2));
else {
  const validate = actual => assert.deepEqual(actual, report);
  validate(local('security-remaining-proposal.json'));
  let negatives = 0;
  if (process.argv[2] === '--self-test') for (const mutate of [
    row => { row.records[0].accepted_by = 'VincentCinque'; },
    row => { row.records[0].proposed_bucket = 'E'; },
    row => { row.proposed_if_approved.H = 1; },
    row => { row.review_deadline.not_after = '2026-11-12T00:00:00-05:00'; },
    row => { row.source.vulnerable_shared_guard_present = false; },
  ]) { const copy = structuredClone(report); mutate(copy); assert.throws(() => validate(copy), assert.AssertionError); negatives++; }
  let links = priorCheck.local_links;
  const document = fs.readFileSync(path.join(__dirname, 'SECURITY_REMAINING_DECISION.md'), 'utf8');
  for (const match of document.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if (/^(https?:|#)/.test(match[1])) continue;
    assert(fs.existsSync(path.resolve(__dirname, decodeURIComponent(match[1].split('#')[0]))), match[1]); links++;
  }
  assert(/\| T-076[^\n]+\n\| T-077/.test(fs.readFileSync(path.join(repo, 'makervault/docs/ARCHITECTURE_RUNBOOK.md'), 'utf8')));
  console.log(JSON.stringify({status: 'passed', new_private_hash_checks: privateHashes, prior_private_hash_checks: priorCheck.private_hash_checks,
    captured_primary_pages: 12, direct_source_files: 51, broad_identifier_hits: broadHits, exact_named_call_hits: 0,
    counts: report.counts, negative_controls: negatives, local_links: links, security_closeout: 'open'}));
}
