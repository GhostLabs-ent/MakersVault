// Reduce/check durable private evidence; never suppress findings or grant risk acceptance.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const app = path.resolve(__dirname, '../../..');
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
const revision = 'ea17494b610f399b3e9d240748c2aab20e0d8aa5';
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const local = name => read(path.join(__dirname, name));
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const unique = values => [...new Set(values)].sort();
const jsonLines = text => text.split('\n').flatMap(line=>{try{return [JSON.parse(line)];}catch{return [];}});
assert(process.argv.length <= 3 && [undefined,'--write'].includes(process.argv[2]));
let checkedHashes = 0;
const privateHash = file => {
  assert.equal(fs.statSync(file).mode & 0o077, 0, `Private evidence permissions: ${file}`);
  checkedHashes++;
  return digest(file);
};
const names = ['preflight-build','preflight-matrix','preflight-matrix-b','old-image-negative',
  'full','language-run','api-build','web-build','image-run','exact-matrix','web-tests','components',
  'final-image-run','final-exact-matrix','final-components'];
const runs = {};
for (const name of names) {
  const directory = path.join(root, 'containment-'+name);
  const record = read(path.join(directory,'result.json'));
  assert.equal(record.exit_code, ['preflight-matrix','old-image-negative','image-run'].includes(name) ? 1 : 0, name);
  for (const artifact of record.artifacts) assert.equal(privateHash(path.join(directory,artifact.file)), artifact.sha256);
  if (!name.startsWith('preflight') && name !== 'old-image-negative') {
    assert.equal(record.source_revision, revision, name);
    assert.equal(record.end_source_revision, revision, name);
    assert.equal(record.verification_source_status, '', name);
    assert.equal(record.end_verification_source_status, '', name);
  }
  runs[name] = {...record, record_sha256:privateHash(path.join(directory,'result.json'))};
}
const stdout = name => fs.readFileSync(path.join(root, 'containment-'+name, 'stdout.log'),'utf8');
const stderr = name => fs.readFileSync(path.join(root, 'containment-'+name, 'stderr.log'),'utf8');
assert(stderr('preflight-matrix').includes('JSONDecodeError'));
assert(stderr('old-image-negative').includes("'CapBnd': 459"));
assert(stderr('image-run').includes('No such image: sha256:cbc44f2a49fceee9226330ee6d17cdb2b162db3f266a2bc4fde229fd75d41afb'));
const full = stdout('full');
assert(/422 passed in [\d.]+s/.test(full));
assert(/Ran 25 tests/.test(stderr('full')) && /\bOK\b/.test(stderr('full')));
assert(/# pass 28\b/.test(full));
assert(/58 passed/.test(stdout('web-tests')));
const lifecycle = jsonLines(full).find(row=>row.raw_restore_contract === 6);
assert(lifecycle && lifecycle.status === 'passed' && lifecycle.revision === revision && lifecycle.dirty === false);
for (const row of [lifecycle.fresh_smoke.process_privileges.api, lifecycle.fresh_smoke.process_privileges.web,
  ...lifecycle.fresh_smoke.process_privileges.web.workers]) {
  assert(row.uid > 0 && row.no_new_privileges);
  assert.deepEqual(Object.keys(row.capabilities).sort(), ['CapAmb','CapBnd','CapEff','CapInh','CapPrm']);
  assert(Object.values(row.capabilities).every(value=>value===0));
}
assert(lifecycle.fresh_smoke.process_privileges.web.workers.length > 0);
assert(/^[a-f0-9]{64}$/.test(lifecycle.fresh_smoke.generated_preview_restart_sha256));
const matrix = JSON.parse(stdout('final-exact-matrix'));
assert.equal(matrix.status, 'passed');
assert.equal(matrix.image, lifecycle.images.api);
assert.equal(Object.keys(matrix.cases).length,8);
assert.deepEqual(Object.keys(matrix.negative_controls).sort(), ['CHOWN','DAC_OVERRIDE','FOWNER','SETGID','SETPCAP','SETUID']);
assert(Object.values(matrix.negative_controls).every(row=>row.exit_code !== 0));
const components = JSON.parse(stdout('final-components'));
assert.deepEqual(components, local('security-hardening-verification.json').runtime.components);
const languages = read(path.join(root,'containment-language-audit/summary.json'));
const images = read(path.join(root,'containment-final-image-audit/summary.json'));
for (const phase of [languages,images]) {
  assert.equal(phase.source_revision, revision);
  assert.equal(phase.verification_sources_dirty, false);
  assert.equal(phase.status, 'audit_completed_not_release_clearance');
  for (const [file, sha] of Object.entries(phase.lock_sha256)) {assert.equal(digest(path.join(app,file)),sha); checkedHashes++;}
}
assert.deepEqual(languages.lock_sha256, local('security-hardening-audit.json').language_phase.lock_sha256);
for (const [name, scan] of Object.entries(languages.scans)) {
  assert.equal(scan.exit_code, 0, name);
  if (name.startsWith('npm-')) assert.equal(scan.vulnerabilities.total,0);
  else if (name.startsWith('python-')) {assert.equal(scan.advisories,0); assert.deepEqual(scan.skipped,[]);}
  else assert.deepEqual(scan.findings,[]);
}
const baseline = local('security-closeout-inventory.json');
const comparisons = {};
const normalize = rows => rows.map(row=>JSON.stringify(row)).sort();
for (const name of ['api','web']) {
  assert.equal(images.images[name].id, lifecycle.images[name]);
  const raw = read(path.join(root,`containment-final-image-audit/image-${name}.json`));
  assert.equal(raw.descriptor.db.status.valid,true);
  const rows = raw.matches.map(({artifact:a,vulnerability:v,matchDetails})=>({
    advisory:v.id,severity:v.severity,source:v.dataSource,namespace:v.namespace,
    package:a.name,version:a.version,type:a.type,locations:unique(a.locations.map(loc=>loc.path)),
    match_types:unique(matchDetails.map(match=>match.type)),fix_state:v.fix?.state || '',fix_versions:unique(v.fix?.versions || [])}));
  const before = normalize(baseline[name].matches), after = normalize(rows);
  const added = after.filter(value=>!before.includes(value)).map(JSON.parse);
  const removed = before.filter(value=>!after.includes(value)).map(JSON.parse);
  comparisons[name] = {baseline:`security-closeout-inventory.json#${name}.matches`,count:rows.length,
    unique_advisories:unique(rows.map(row=>row.advisory)).length,equal:!added.length&&!removed.length,added,removed};
  assert(comparisons[name].equal, 'New image findings require explicit review, not inherited dispositions');
}
const artifacts = {};
for (const phase of ['language','image','final-image']) {
  const directory = path.join(root,`containment-${phase}-audit`);
  artifacts[phase] = fs.readdirSync(directory).sort().map(file=>({file,sha256:privateHash(path.join(directory,file))}));
}
const unchanged = ['api/requirements.txt','api/requirements.lock','api/requirements-dev.lock','api/requirements-build.lock',
  'api/Dockerfile','api/main.py','api/auth.py','api/http_security.py','api/migrations.py','api/url_utils.py','api/safe_http.py',
  'web/Dockerfile','web/package-lock.json','scripts/backup.sh','scripts/restore.sh','docker-deploy.yml'];
const boundaryHashes = {};
for (const file of unchanged) {
  const before = execFileSync('git',['show','65348c8:makervault/'+file],{cwd:app});
  assert(fs.readFileSync(path.join(app,file)).equals(before), `Unapproved boundary change: ${file}`);
  boundaryHashes[file] = digest(path.join(app,file));
}
assert.equal(execFileSync('git',['diff','--name-only',revision,'--','api','web','scripts','benchmarks',
  'slicer-bridge','docker-compose.yml','docker-compose.deploy.yml','docker-deploy.yml','../Makefile'],{cwd:app,encoding:'utf8'}).trim(),'');
const oldDecisions = local('security-residual-decisions.json');
assert.equal(oldDecisions.records.length,80);
assert.equal(unique(oldDecisions.records.map(row=>row.id)).length,80);
assert(oldDecisions.records.every(row=>row.owner_decision === 'pending' && row.accepted_by === null));
const evidence = {schema:1,revision,status:'verified_not_security_acceptance',
  durable_private_root:root,runs,language_phase:languages,image_phase:images,raw_audit_artifacts:artifacts,
  image_match_comparison:comparisons,lifecycle,exact_image_matrix:matrix,components,
  verification:{api_tests:422,web_tests:58,web_reexecuted:true,python_harness_tests:25,node_harness_tests:28,
    first_matrix_attempt:'Harness JSON parser rejected informational usermod output on restart; corrected, failure retained',
    old_image_negative:'Expected failure: nonempty application bounding set (459), not an exploit demonstration',
    first_image_attempt:'API scan completed; earlier web image unavailable after lifecycle rebuild produced different IDs. Incomplete attempt retained; final matrix, component probe and both-image audit repeated against exact successful lifecycle IDs. No reproducibility claim.',
    frozen_boundary_sha256:boundaryHashes},
  residuals:{source:'security-residual-decisions.json',source_sha256:digest(path.join(__dirname,'security-residual-decisions.json')),
    scope:'Same 80 S04 CVEs now attached to the exact lifecycle/audit images above; stronger verified deployment boundary, no installed native fixes',
    images:lifecycle.images,platform:'linux/amd64',
    counts:oldDecisions.counts,all_owner_decisions:'pending',risk_acceptance:'not_granted',
    reopen:'Any changed advisory, caller, platform/image or weaker deployment requires renewed review'}};
const output = path.join(__dirname,'security-containment-verification.json');
if (process.argv[2] === '--write') fs.writeFileSync(output,JSON.stringify(evidence,null,2)+'\n',{flag:'wx'});
else assert.deepEqual(read(output),evidence);
let links = 0;
for (const name of ['docs/ARCHITECTURE_RUNBOOK.md','docs/ROADMAP.md','docs/SECURE_DEPLOYMENT.md','docs/RELEASE_NOTES_v5.1.0.md',
  'docs/security/GATE_13_REVALIDATION.md','docs/evidence/gate-13/SECURITY_CONTAINMENT_RESULTS.md',
  'docs/evidence/gate-13/SECURITY_RESIDUAL_DECISIONS.md','docs/evidence/gate-13/SUBGATE_13C_RESULTS.md',
  'docs/evidence/gate-13/TRACEABILITY.md']) {
  const file = path.join(app,name);
  const text = fs.readFileSync(file,'utf8');
  for (const match of text.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if (/^(https?:|#)/.test(match[1])) continue;
    assert(fs.existsSync(path.resolve(path.dirname(file),decodeURIComponent(match[1].split('#')[0]))),`${name}: ${match[1]}`);
    links++;
  }
  if (name.endsWith('ARCHITECTURE_RUNBOOK.md')) assert(/\| T-068[^\n]+\n\| T-069/.test(text),'Split truth table');
}
console.log(JSON.stringify({status:'passed',checked_hashes:checkedHashes,run_records:names.length,
  api_matches:comparisons.api.count,web_matches:comparisons.web.count,native_decisions:80,accepted:0,local_links:links}));
