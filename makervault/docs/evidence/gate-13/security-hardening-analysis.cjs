// Assemble the new verification/audit records without rewriting historical evidence.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');
const root = '/tmp/makersvault-security-hardening-';
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const unique = values => [...new Set(values)].sort();
const files = directory => fs.readdirSync(directory).sort().map(file=>({file,
  bytes:fs.statSync(path.join(directory,file)).size,sha256:digest(path.join(directory,file))}));
const runs = {};
for (const name of ['api-build','focused','web','api-build-b','negative-control','focused-b','full','languages','images','runtime','components']) {
  const directory = root+name;
  const result = read(path.join(directory,'result.json'));
  for (const record of result.artifacts) assert.equal(digest(path.join(directory,record.file)),record.sha256);
  assert.equal(result.exit_code, ['focused','negative-control'].includes(name) ? 1 : 0, name);
  runs[name] = {...result,record_sha256:digest(path.join(directory,'result.json'))};
}
const revision = runs.full.source_revision;
assert.equal(revision,'ac4a051302d49838ef676c760cdfd95ab2127408');
for (const name of ['full','languages','images','runtime','components']) {
  assert.equal(runs[name].source_revision,revision);
  assert.equal(runs[name].end_source_revision,revision);
  assert.equal(runs[name].verification_source_status,'');
  assert.equal(runs[name].end_verification_source_status,'');
}
const fullLog = fs.readFileSync(root+'full/stdout.log','utf8');
const lifecycle = fullLog.split('\n').filter(line=>line.startsWith('{')).map(line=>{
  try { return JSON.parse(line); } catch { return {}; }
}).find(row=>row.raw_restore_contract === 6 && row.status === 'passed');
assert(lifecycle && !lifecycle.dirty);
assert.equal(lifecycle.revision,revision);
const apiResult = fullLog.match(/(\d+) passed in ([\d.]+)s/);
assert(apiResult);
assert.equal(Number(apiResult[1]),422);
const language = read(root+'language-audit/summary.json');
const imageAudit = read(root+'image-audit/summary.json');
for (const report of [language,imageAudit]) {
  assert.equal(report.source_revision,revision);
  assert.equal(report.verification_sources_dirty,false);
  assert.equal(report.status,'audit_completed_not_release_clearance');
}
assert.deepEqual(language.lock_sha256,imageAudit.lock_sha256);
const app = path.resolve(__dirname,'../../..');
for (const [file,hash] of Object.entries(language.lock_sha256)) assert.equal(digest(path.join(app,file)),hash);
const previousAudit = read(path.join(__dirname,'security-closeout-audit.json'));
const changedLocks = Object.keys(language.lock_sha256).filter(file=>language.lock_sha256[file] !== previousAudit.lock_sha256[file]).sort();
assert.deepEqual(changedLocks,['api/requirements-dev.lock','web/package-lock.json']);
const oldWeb = JSON.parse(execFileSync('git',['show','b371ff8:makervault/web/package-lock.json'],{cwd:app,encoding:'utf8'}));
const newWeb = read(path.join(app,'web/package-lock.json'));
assert.deepEqual(Object.keys(oldWeb.packages).sort(),Object.keys(newWeb.packages).sort());
const changedWebPackages = Object.keys(newWeb.packages).filter(key=>key && JSON.stringify(oldWeb.packages[key]) !== JSON.stringify(newWeb.packages[key]));
assert.equal(changedWebPackages.length,8);
assert(changedWebPackages.every(key=>/^node_modules\/(?:@vitest\/|vitest$)/.test(key)));
for (const [name,scan] of Object.entries(language.scans)) {
  assert.equal(scan.exit_code,0,name);
  if (name.startsWith('npm-')) assert.equal(scan.vulnerabilities.total,0,name);
  if (name.startsWith('python-')) {assert.equal(scan.advisories,0,name); assert.deepEqual(scan.skipped,[],name);}
  if (name === 'go') assert.deepEqual(scan.findings,[]);
}
const prior = read(path.join(__dirname,'security-closeout-inventory.json'));
const comparisons = {};
for (const name of ['api','web']) {
  assert.equal(imageAudit.images[name].id,lifecycle.images[name]);
  const raw = read(root+`image-audit/image-${name}.json`);
  const rows = raw.matches.map(({artifact:a,vulnerability:v,matchDetails})=>({
    advisory:v.id,severity:v.severity,source:v.dataSource,namespace:v.namespace,
    package:a.name,version:a.version,type:a.type,locations:unique(a.locations.map(row=>row.path)),
    match_types:unique(matchDetails.map(row=>row.type)),fix_state:v.fix?.state || '',fix_versions:unique(v.fix?.versions || [])}));
  const key = row=>JSON.stringify([row.advisory,row.namespace,row.package,row.version,row.type]);
  const old = new Map(prior[name].matches.map(row=>[key(row),row]));
  const current = new Map(rows.map(row=>[key(row),row]));
  const added = rows.filter(row=>!old.has(key(row)));
  const removed = prior[name].matches.filter(row=>!current.has(key(row)));
  const changed = rows.filter(row=>old.has(key(row)) && JSON.stringify(old.get(key(row))) !== JSON.stringify(row))
    .map(row=>({before:old.get(key(row)),after:row}));
  assert.equal(rows.length,imageAudit.scans[`image-${name}`].matches);
  comparisons[name] = {count:rows.length,unique_advisories:unique(rows.map(row=>row.advisory)).length,
    baseline:'security-closeout-inventory.json#'+name+'.matches',
    equal:!added.length&&!removed.length&&!changed.length,added,removed,changed};
}
const runtime = read(root+'runtime/stdout.log');
const components = read(root+'components/stdout.log');
assert.equal(runtime.status,'passed');
assert.equal(runtime.packages.idna,'3.18');
assert.equal(runtime.packages.httpx2,null);
assert.equal(components.machine,'x86_64');
assert.equal(components.pointer_bits,64);
const verification = {schema:1,revision,scope:'Owner-approved S01/S02; not release clearance or S04 risk acceptance',
  dependency_delta:{changed_locks:changedLocks,changed_web_packages:changedWebPackages,
    python_development:['httpx2:2.9.0->2.12.0','httpcore2:2.9.0->2.12.0'],
    runtime:'idna 3.18 now direct; all runtime lock versions unchanged'},
  runs,results:{api_tests:Number(apiResult[1]),api_seconds:Number(apiResult[2]),
    new_hostname_cases:68,focused_tests:138,focused_seconds:13.56,web_tests:58,
    first_focused_attempt:'2 failed / 135 passed: repeated root dot and incomplete TLS test double; both corrected before commit',
    negative_control:'1 expected assertion failure / 67 deselected against old image: Unicode domain incorrectly mapped to fass.example',
    dependency_resolution:'Initial HTTPX2 2.12.0/httpcore2 2.10.0 dry run refused; exact upstream dependency requires matching 2.12.0',
    lifecycle},runtime:{image:imageAudit.images.api.id,policy:runtime,components}};
const audit = {schema:1,source_revision:revision,status:'audit_completed_not_release_clearance',
  language_phase:language,image_phase:imageAudit,
  raw_artifacts:{languages:files(root+'language-audit'),images:files(root+'image-audit')},
  reduced_match_comparison:comparisons,
  disposition_delta:{id:'CVE-2026-17084',previous:'reachable_normalization_requires_decision',
    current:'reviewed_outbound_application_path_mitigated_with_strict_idna2008; CPython remains unpatched and matched',
    evidence:'SECURITY_HARDENING_RESULTS.md',other_dispositions:'Retained from SECURITY_CLOSEOUT.md, not new vendor review or owner risk acceptance'},
  risk_acceptance:'not_granted'};
const outputs = {'security-hardening-verification.json':verification,'security-hardening-audit.json':audit};
for (const file of Object.keys(outputs)) assert(!fs.existsSync(path.join(__dirname,file)),`Refusing to overwrite ${file}`);
for (const [file,data] of Object.entries(outputs)) fs.writeFileSync(path.join(__dirname,file),JSON.stringify(data,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({written:Object.keys(outputs),api_tests:verification.results.api_tests,
  language_advisories:0,images:comparisons,policy_probe:runtime.status,risk_acceptance:'not_granted'}));
