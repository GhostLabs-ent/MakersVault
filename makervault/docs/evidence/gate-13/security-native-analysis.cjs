// Join the approved native update's retained evidence. Never transfers image waivers.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const app = path.resolve(__dirname, '../../..');
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
const revision = '6306ccff289d475530a6cacf4cb2e28db456ce08';
const priorRevision = '1b83d434688681aeefb4737c67a9e0daf5b8468d';
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const local = name => read(path.join(__dirname, name));
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const unique = rows => [...new Set(rows)].sort();
const jsonLines = text => text.split('\n').flatMap(line => {try {return [JSON.parse(line)];} catch {return [];}});
assert(process.argv.length <= 3 && [undefined, '--write', '--refresh-draft'].includes(process.argv[2]));
let hashes = 0;
const privateHash = file => {
  assert(!fs.lstatSync(file).isSymbolicLink(), file);
  assert.equal(fs.statSync(file).mode & 0o077, 0, file);
  hashes++;
  return digest(file);
};
const names = ['preflight','build','focused','old-negative','installed-test','full-b','language-run',
  'web-tests','image-run','exact-matrix','components','cli','installed-runtime','identities','delta-probe'];
const preflightNames = names.slice(0,5);
const runs = {};
for (const name of names) {
  const directory = path.join(root, 'containment-native-'+name);
  assert.equal(fs.statSync(directory).mode & 0o077, 0);
  const run = read(path.join(directory, 'result.json'));
  assert.equal(run.exit_code, name === 'old-negative' ? 1 : 0, name);
  assert.equal(run.source_revision, preflightNames.includes(name) ? priorRevision : revision, name);
  assert.equal(run.end_source_revision, run.source_revision);
  if (!preflightNames.includes(name)) {
    assert.equal(run.verification_source_status, '', name);
    assert.equal(run.end_verification_source_status, '', name);
  }
  const raw_sha256 = Object.fromEntries(['started.json','result.json','stdout.log','stderr.log']
    .map(file => [file, privateHash(path.join(directory,file))]));
  for (const artifact of run.artifacts) assert.equal(raw_sha256[artifact.file], artifact.sha256);
  runs[name] = {run, raw_sha256};
}
const stdout = name => fs.readFileSync(path.join(root,'containment-native-'+name,'stdout.log'),'utf8');
const incompleteDirectory = path.join(root,'containment-native-full');
assert(!fs.existsSync(path.join(incompleteDirectory,'result.json')));
const incomplete = {status:'interrupted_no_completion_record',
  reason:'lean-ctx outer wrapper hit its 120-second limit; child work ended before capture completion. Not a successful full gate. Orphaned disposable smoke fixture removed before sequential rerun.',
  started:read(path.join(incompleteDirectory,'started.json')),
  raw_sha256:Object.fromEntries(['started.json','stdout.log','stderr.log'].map(file=>[file,privateHash(path.join(incompleteDirectory,file))]))};
const full = stdout('full-b');
assert(/424 passed in [\d.]+s/.test(full));
assert(/58 passed/.test(stdout('web-tests')));
assert(/# pass 28\b/.test(full));
assert(/Ran 25 tests/.test(fs.readFileSync(path.join(root,'containment-native-full-b/stderr.log'),'utf8')));
const lifecycle = jsonLines(full).find(row => row.raw_restore_contract === 6);
assert(lifecycle && lifecycle.status === 'passed' && lifecycle.revision === revision && !lifecycle.dirty);
assert.equal(lifecycle.upgrade, '4-to-17');
for (const name of ['exact_schema4_rollback','offline_portable_graph_equal','portable_staged_pair_verified',
  'pre_start_revocation','startup_audit','external_availability_normalized','fresh_identity_only']) assert.equal(lifecycle[name], true, name);
assert.equal(lifecycle.portable_members_compared, 18);
assert.equal(lifecycle.portable_import_schema, 12);
assert.equal(lifecycle.portable_startup_schema, 17);
assert.deepEqual(lifecycle.refusals, ['nonempty_raw_target','corrupt_raw_archive','nonempty_portable_target']);
const identities = JSON.parse(stdout('identities')).map(row => ({id:row.Id,os:row.Os,
  architecture:row.Architecture,labels:row.Config.Labels}));
for (const identity of identities) {
  assert(Object.values(lifecycle.images).includes(identity.id));
  assert.equal(identity.os, 'linux');
  assert.equal(identity.architecture, 'amd64');
  assert.equal(identity.labels['org.opencontainers.image.revision'], revision);
  assert.equal(identity.labels['org.opencontainers.image.version'], 'development-gate13b');
}
assert.equal(identities.length, 2);
for (const row of [lifecycle.fresh_smoke.process_privileges.api, lifecycle.fresh_smoke.process_privileges.web,
  ...lifecycle.fresh_smoke.process_privileges.web.workers]) {
  assert(row.uid > 0 && row.no_new_privileges);
  assert.deepEqual(Object.keys(row.capabilities).sort(), ['CapAmb','CapBnd','CapEff','CapInh','CapPrm']);
  assert(Object.values(row.capabilities).every(value => value === 0));
}
assert(lifecycle.fresh_smoke.process_privileges.web.workers.length > 0);
assert(/^[a-f0-9]{64}$/.test(lifecycle.fresh_smoke.generated_preview_restart_sha256));
const matrix = JSON.parse(stdout('exact-matrix'));
assert.equal(matrix.status, 'passed');
assert.equal(matrix.image, lifecycle.images.api);
assert.equal(Object.keys(matrix.cases).length, 8);
assert.deepEqual(Object.keys(matrix.negative_controls).sort(), ['CHOWN','DAC_OVERRIDE','FOWNER','SETGID','SETPCAP','SETUID']);
assert(Object.values(matrix.negative_controls).every(row => row.exit_code !== 0));
for (const name of ['components','cli','installed-runtime','delta-probe']) assert(runs[name].run.command.includes(lifecycle.images.api));
const components = JSON.parse(stdout('components'));
const cli = JSON.parse(stdout('cli'));
const deltaProbe = JSON.parse(stdout('delta-probe'));
assert.equal(deltaProbe.size_t_bytes, 8);
assert.equal(deltaProbe.nscd.which, null);
assert.deepEqual(deltaProbe.nscd.present_paths, []);
assert.equal(deltaProbe.nscd.package_search_exit, 1);
assert.deepEqual(deltaProbe.pcre2_libraries, {'8':'libpcre2-8.so.0','16':null,'32':null});
const prior = local('security-acceptance-review-2026-09-12.json');
const proposal = local('security-disposition-proposal.json');
assert.deepEqual(components, prior.components);
assert.deepEqual(cli, prior.cli);
const inventory = JSON.parse(stdout('installed-runtime'));
const oldInventory = JSON.parse(stdout('old-negative'));
const testInventory = JSON.parse(stdout('installed-test'));
const preflight = JSON.parse(stdout('preflight'));
assert.equal(preflight.index_update.exit_code, 0);
assert.equal(preflight.simulation.exit_code, 0);
assert(preflight.simulation.stdout.includes('6 upgraded, 0 newly installed, 0 to remove'));
assert.deepEqual(preflight.targets, inventory.pins);
assert(preflight.sources['/etc/apt/sources.list.d/debian.sources'].text.includes('Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp'));
assert.equal(inventory.status, 'passed');
assert.equal(testInventory.status, 'passed');
assert.equal(oldInventory.status, 'failed');
assert.equal(Object.keys(oldInventory.mismatches).length, 6);
assert.deepEqual(testInventory.installed, inventory.installed);
assert.equal(inventory.lock_sha256, digest(path.join(app,'api/native-packages.lock')));
assert.deepEqual(oldInventory.pins, inventory.pins);
const packageChanges = unique([...Object.keys(inventory.installed),...Object.keys(oldInventory.installed)])
  .filter(name => inventory.installed[name] !== oldInventory.installed[name])
  .map(name => ({name, before:oldInventory.installed[name] || null, after:inventory.installed[name] || null}));
assert.deepEqual(packageChanges.map(row => row.name), Object.keys(inventory.pins).sort());
assert(packageChanges.every(row => row.before && row.after === inventory.pins[row.name]));
const phases = {};
const auditArtifacts = {};
for (const phase of ['language','image']) {
  const directory = path.join(root,'containment-native-'+phase+'-audit');
  const audit = read(path.join(directory,'summary.json'));
  assert.equal(audit.source_revision, revision);
  assert.equal(audit.verification_sources_dirty, false);
  assert.equal(audit.status, 'audit_completed_not_release_clearance');
  for (const [file, sha] of Object.entries(audit.lock_sha256)) assert.equal(digest(path.join(app,file)), sha);
  assert.deepEqual(audit.lock_sha256, local('security-containment-verification.json').language_phase.lock_sha256);
  phases[phase] = audit;
  auditArtifacts[phase] = fs.readdirSync(directory).sort().map(file => ({file, sha256:privateHash(path.join(directory,file))}));
}
for (const [name, scan] of Object.entries(phases.language.scans)) {
  assert.equal(scan.exit_code, 0, name);
  if (name.startsWith('npm-')) assert.equal(scan.vulnerabilities.total, 0);
  else if (name.startsWith('python-')) {assert.equal(scan.advisories, 0); assert.deepEqual(scan.skipped, []);}
  else assert.deepEqual(scan.findings, []);
}
const baseline = local('security-closeout-inventory.json');
const normalize = rows => rows.map(row => JSON.stringify(row)).sort();
const comparisons = {};
const allMatches = [];
for (const name of ['api','web']) {
  assert.equal(phases.image.images[name].id, lifecycle.images[name]);
  assert.equal(phases.image.images[name].labels['org.opencontainers.image.revision'], revision);
  const raw = read(path.join(root,`containment-native-image-audit/image-${name}.json`));
  assert.equal(raw.descriptor.db.status.valid, true);
  const matches = raw.matches.map(({artifact:a,vulnerability:v,matchDetails}) => ({
    advisory:v.id,severity:v.severity,source:v.dataSource,namespace:v.namespace,
    package:a.name,version:a.version,type:a.type,locations:unique(a.locations.map(row=>row.path)),
    match_types:unique(matchDetails.map(row=>row.type)),fix_state:v.fix?.state || '',fix_versions:unique(v.fix?.versions || [])}));
  const before = normalize(baseline[name].matches), after = normalize(matches);
  comparisons[name] = {before:before.length, after:after.length,
    unique_advisories:unique(matches.map(row=>row.advisory)).length,
    added:after.filter(row=>!before.includes(row)).map(JSON.parse),
    removed:before.filter(row=>!after.includes(row)).map(JSON.parse), matches,
    scanner:{version:raw.descriptor.version,db:raw.descriptor.db}};
  allMatches.push(...matches.map(row=>({image:name,...row})));
}
// Historical proposal/event inputs are immutable. Their old checker intentionally
// binds the pre-update Dockerfile, so it is not invoked against changed source.
const historicalFiles = ['security-owner-acceptance-2026-09-12.json',
  'security-acceptance-review-2026-09-12.json','security-disposition-proposal.json',
  'security-containment-verification.json','security-closeout-inventory.json'];
const inputs = {};
for (const name of historicalFiles) {
  const file = path.join(__dirname,name);
  assert(fs.readFileSync(file).equals(execFileSync('git',['show',priorRevision+':makervault/docs/evidence/gate-13/'+name],{cwd:app})));
  inputs[name] = digest(file);
}
assert.equal(inputs['security-owner-acceptance-2026-09-12.json'], prior.approval_event_sha256);
const approvedChanges = ['makervault/api/Dockerfile','makervault/api/native-packages.lock','makervault/api/tests/test_native_package_contract.py'];
const sourcePaths = ['api','web','scripts','benchmarks','slicer-bridge','docker-compose.yml',
  'docker-compose.deploy.yml','docker-deploy.yml','../Makefile'];
const git = args => execFileSync('git',args,{cwd:app,encoding:'utf8'}).trim();
assert.deepEqual(git(['diff','--name-only',priorRevision,revision,'--',...sourcePaths]).split('\n').sort(), approvedChanges);
assert.equal(git(['diff','--name-only',revision,'--',...sourcePaths]), '');
assert.equal(git(['ls-files','--others','--exclude-standard','--',...sourcePaths]), '');
const vendorDirectory = path.join(root,'containment-acceptance-vendor');
const vendorHashes = {};
const vendorSummary = read(path.join(vendorDirectory,'summary.json'));
assert.equal(privateHash(path.join(vendorDirectory,'summary.json')), prior.vendor.summary_sha256);
for (const row of prior.records.filter(row=>row.raw_sha256)) {
  const source = vendorSummary.records[row.id];
  assert.equal(privateHash(path.join(vendorDirectory,source.raw_file)), row.raw_sha256);
  vendorHashes[row.id] = row.raw_sha256;
}
const records = proposal.records.map(row => {
  const vendor = prior.records.find(record => record.id === row.id);
  const matches = allMatches.filter(match => match.advisory === row.id);
  const installedFix = vendor.supported_fix_identified && row.matches.every(match => inventory.pins[match.package]);
  if (installedFix) assert(row.matches.every(match => vendor.trixie_rows.some(text =>
    text.endsWith(' '+inventory.pins[match.package]+' fixed'))), row.id);
  let status;
  if (installedFix) status = matches.length ? 'vendor_fix_installed_scanner_still_reports' : 'vendor_fix_installed_no_current_match';
  else if (row.bucket === 'H') status = 'held_unresolved_not_accepted';
  else if (row.bucket === 'E') status = 'precondition_revalidated_new_image_exclusion_pending';
  else status = 'boundary_revalidated_new_image_exception_pending';
  return {id:row.id, prior_bucket:row.bucket, status, matches,
    vendor_source:vendor.source, vendor_review_date:prior.reviewed_date, vendor_rows:vendor.trixie_rows,
    installed_fix:!!installedFix, rationale:installedFix
      ? 'Exact signed stable binary pins installed; current raw scanner result retained independently.' : row.rationale,
    exit_criteria:installedFix ? 'Refresh exact image/vendor evidence at candidate freeze; no broad family exclusion.' : row.exit_criteria,
    owner_acceptance:'not_transferred', accepted_by:null,
    prior_owner_event:'security-owner-acceptance-2026-09-12.json#'+row.id};
});
const priorIds = new Set(proposal.records.map(row=>row.id));
const knownOther = new Set(['api','web'].flatMap(name=>baseline[name].matches).filter(row=>!priorIds.has(row.advisory)).map(row=>row.advisory));
const otherMatches = allMatches.filter(row=>!priorIds.has(row.advisory));
const newAdvisories = unique(otherMatches.filter(row=>!knownOther.has(row.advisory)).map(row=>row.advisory));
assert.deepEqual(newAdvisories, ['CVE-2026-89092','CVE-2026-89156','CVE-2026-89157',
  'CVE-2026-89158','CVE-2026-89160','CVE-2026-89161','CVE-2026-89162']);
const newSet = new Set(newAdvisories);
const withoutPackageEvidence = ({version,locations,...row}) => row;
for (const name of ['api','web']) {
  assert.deepEqual(normalize(comparisons[name].matches.filter(row=>!newSet.has(row.advisory)).map(withoutPackageEvidence)),
    normalize(baseline[name].matches.map(withoutPackageEvidence)), 'Unreviewed advisory/metadata delta');
  for (const row of comparisons[name].added.filter(row=>!newSet.has(row.advisory)))
    assert.equal(row.version, inventory.pins[row.package]);
}
assert.equal(comparisons.api.added.length, 71);
assert.equal(comparisons.api.removed.length, 63);
assert.equal(comparisons.web.added.length, 0);
assert.equal(comparisons.web.removed.length, 0);
const gh = 'https://github.com/PCRE2Project/pcre2/';
const deltaReviews = {
  'CVE-2026-89092': {status:'absent_precondition_exclusion_proposed_not_accepted',
    source:'https://security-tracker.debian.org/tracker/CVE-2026-89092',
    rationale:'Vendor requires the nscd service. Exact runtime has no nscd package-manifest match or named executable; no daemon is supplied by the canonical API image. No whole-glibc exclusion.'},
  'CVE-2026-89156': {status:'new_native_caller_and_backport_review_held',
    source:gh+'security/advisories/GHSA-2p8c-ff85-vh9x',
    rationale:'8-bit PCRE2 is present. Upstream describes invalid UTF and specific JIT-to-interpreter fallback. No direct application PCRE2 caller found; indirect/tool callers are not excluded.'},
  'CVE-2026-89157': {status:'absent_precondition_exclusion_proposed_not_accepted',
    source:gh+'security/advisories/GHSA-q8g2-wprr-34m9',
    rationale:'Upstream identifies 32-bit size_t pattern-conversion overflow and says 64-bit size_t builds are believed unaffected. Exact runtime size_t is 8 bytes; retain the qualification and do not confuse code-unit width with process width.'},
  'CVE-2026-89158': {status:'absent_precondition_exclusion_proposed_not_accepted',
    source:gh+'security/advisories/GHSA-fmgr-6ggq-9859',
    rationale:'Upstream identifies compile_32 overflow on 32-bit systems. Runtime size_t is 8 bytes and only pcre2-8 library is found. Narrow architecture/component proposal, not a PCRE2-family exclusion.'},
  'CVE-2026-89160': {status:'new_native_caller_and_backport_review_held',
    source:gh+'security/advisories/GHSA-9qww-pwc4-77qq',
    rationale:'Invalid-UTF matching path exists in the installed native family; no direct application caller found, but indirect/tool reachability and Debian backport status remain unproven.'},
  'CVE-2026-89161': {status:'new_native_caller_and_backport_review_held',
    source:gh+'pull/937',
    rationale:'Upstream fast-path JIT matching can incorrectly free a previously copied subject. Installed 8-bit library is present; absence of a direct application call does not prove native dependency safety.'},
  'CVE-2026-89162': {status:'new_native_caller_and_backport_review_held',
    source:gh+'security/advisories/GHSA-q7rw-r7qq-2hx6',
    rationale:'Upstream describes uninitialized-byte disclosure during serialization. No direct application native serialization caller identified; library presence and indirect/operator uncertainty remain.'},
};
const newRecords = newAdvisories.map(id => ({id,...deltaReviews[id],
  matches:allMatches.filter(row=>row.advisory===id), reviewed_date:'2026-09-12',
  source_evidence:'Primary browser review; fresh page body not separately archived. CVE-to-PCRE2-advisory mapping is the retained scanner related-vulnerability URL, not a claim the upstream page already lists the CVE.',
  debian_page_status:id==='CVE-2026-89092' ? 'browser_read_succeeded' : 'browser_read_unavailable_not_retried',
  exit_criteria:'Reconcile supported distribution fix/build and exact caller/precondition evidence before a new scoped owner decision; no further patch or waiver authorized.',
  owner_acceptance:'not_granted',accepted_by:null}));
const counts = Object.fromEntries(unique(records.map(row=>row.status)).map(status=>[status,records.filter(row=>row.status===status).length]));
const report = {schema:1,status:'native_update_verified_not_owner_acceptance_or_release_clearance',
  revision,previous_revision:priorRevision,approved_scope:'Six existing Debian stable packages only; user approved implementation, not image waiver transfer',
  runs,interrupted_attempt:incomplete,package_changes:packageChanges,installed_inventory:inventory,phases,audit_artifacts:auditArtifacts,
  lifecycle,identities,exact_image_matrix:matrix,components,cli,delta_probe:deltaProbe,comparison:comparisons,
  historical_input_sha256:inputs,vendor_raw_sha256:vendorHashes,
  native_lock_sha256:inventory.lock_sha256,counts,records,
  delta_review:{existing_api_records_with_only_package_version_or_location_change:63,
    added_matches:8,added_cves:7,removed_advisories:0,new_records:newRecords,
    targeted_conflict:'20 vendor-fixed source versions match the installed signed binary pins, while Grype retains unknown version constraints/no fixed versions. Data-source disagreement remains held, not silently suppressed or declared resolved.',
    causality:'Database advanced from September 10 to September 12. No same-database old-image rescan was performed; newly seen findings are not established as introduced by this patch.'},
  other_matches:{scope:'17 unchanged S02/S03 interpreter matches stay separate; seven newly seen native CVEs are explicitly reviewed in delta_review',matches:otherMatches,new_advisories:newAdvisories},
  owner_policy:{conditions:proposal.owner_policy.conditions,new_image_acceptances:0,
    previous_deadline:prior.review_deadline,proposed_renewal_deadline:prior.review_deadline,
    note:'No extension or automatic renewal; remaining E/R recommendations require explicit exact-image owner decision. H entries remain held.'},
  verification:{api_tests:424,web_tests:58,web_reexecuted:true,python_harness_tests:25,node_harness_tests:28,
    expected_negative:'Old exact API fails all six pins; no exploit invoked',
    limits:'Local linux/amd64 only; no public candidate, hostile recovery sandbox, physical passkey, browser performance or multiarchitecture qualification'}};
const output = path.join(__dirname,'security-native-verification.json');
if (process.argv[2] === '--write') fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
else if (process.argv[2] === '--refresh-draft') {
  assert.equal(git(['ls-files','--',output]), '', 'Committed evidence is immutable; append a new checkpoint');
  assert.equal(read(output).revision, revision);
  fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
}
else assert.deepEqual(read(output),report);
let localLinks = 0;
for (const name of ['docs/ARCHITECTURE_RUNBOOK.md','docs/ROADMAP.md','docs/RELEASE_NOTES_v5.1.0.md',
  'docs/security/GATE_13_REVALIDATION.md','docs/evidence/gate-13/SUBGATE_13C_RESULTS.md',
  'docs/evidence/gate-13/TRACEABILITY.md','docs/evidence/gate-13/SECURITY_NATIVE_UPDATE_RESULTS.md',
  'docs/evidence/gate-13/SECURITY_OWNER_ACCEPTANCE.md']) {
  const file = path.join(app,name);
  const text = fs.readFileSync(file,'utf8');
  for (const match of text.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if (/^(https?:|#)/.test(match[1])) continue;
    assert(fs.existsSync(path.resolve(path.dirname(file),decodeURIComponent(match[1].split('#')[0]))), `${name}: ${match[1]}`);
    localLinks++;
  }
  if (name.endsWith('ARCHITECTURE_RUNBOOK.md')) assert(/\| T-071[^\n]+\n\| T-072/.test(text), 'Split truth table');
}
console.log(JSON.stringify({status:'passed',private_hash_checks:hashes,runs:names.length,
  package_changes:packageChanges,images:lifecycle.images,
  api_matches:comparisons.api.after,web_matches:comparisons.web.after,counts,new_advisories:newAdvisories,local_links:localLinks}));
