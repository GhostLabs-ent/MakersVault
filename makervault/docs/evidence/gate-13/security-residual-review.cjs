// Documentation-only S04 register. No suppressions, waivers, network or vault access.
// --capture uses the exact existing development images for a benign component probe.
// --write creates a deterministic register; default checks committed evidence offline.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const app = path.resolve(__dirname, '../../..');
const read = name => JSON.parse(fs.readFileSync(path.join(__dirname, name), 'utf8'));
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const output = 'security-residual-decisions.json';
const observationFile = 'security-residual-observations.json';
const inventory = read('security-closeout-inventory.json');
const audit = read('security-hardening-audit.json');
const verification = read('security-hardening-verification.json');
const sources = ['api', 'web', 'scripts', 'benchmarks', 'slicer-bridge'];
const git = (...args) => execFileSync('git', args, {cwd: app, encoding:'utf8'}).trim();
const unique = values => [...new Set(values)].sort();
const writeNew = (name, value) => fs.writeFileSync(path.join(__dirname, name), JSON.stringify(value, null, 2)+'\n', {flag:'wx'});
assert(['--capture', '--write', undefined].includes(process.argv[2]) && process.argv.length <= 3);
const boundary = ['docker-compose.yml', 'docker-compose.deploy.yml', 'docker-deploy.yml',
  'api/Dockerfile', 'web/Dockerfile', 'api/docker-entrypoint.sh', 'scripts/restore.sh'];
if (process.argv[2] === '--capture') {
  assert(!fs.existsSync(path.join(__dirname, observationFile)), 'Never overwrite observations');
  assert.equal(git('status', '--porcelain', '--', ...sources), '');
  assert.equal(git('diff', '--name-only', verification.revision, '--', ...sources), '');
  const started = new Date().toISOString();
  const images = {};
  for (const name of ['api', 'web']) {
    const id = audit.image_phase.images[name].id;
    const [image] = JSON.parse(execFileSync('docker', ['image', 'inspect', id], {encoding:'utf8', timeout:15000}));
    assert.equal(image.Id, id);
    assert.equal(image.Config.Labels['org.opencontainers.image.revision'], verification.revision);
    assert.equal(image.Os+'/'+image.Architecture, 'linux/amd64');
    images[name] = {id, platform:image.Os+'/'+image.Architecture};
  }
  const probe = path.join(__dirname, 'security-closeout-runtime.py');
  const command = ['run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
    '--security-opt', 'no-new-privileges', '--user', '65534:65534', '--memory', '256m', '--cpus', '1',
    '--env', 'PYTHONDONTWRITEBYTECODE=1', '--mount', 'type=bind,src='+probe+',dst=/probe.py,readonly',
    '--entrypoint', 'python', images.api.id, '/probe.py'];
  const stdout = execFileSync('docker', command, {encoding:'utf8', timeout:45000});
  const components = JSON.parse(stdout);
  assert.deepEqual(components, verification.runtime.components);
  assert.equal(git('status', '--porcelain', '--', ...sources), '');
  const privatePaths = ['/tmp/makersvault-security-hardening-language-audit',
    '/tmp/makersvault-security-hardening-image-audit', '/tmp/makersvault-security-hardening-full'];
  writeNew(observationFile, {schema:1, started_at:started, finished_at:new Date().toISOString(),
    documentation_revision:git('rev-parse','HEAD'), application_revision:verification.revision,
    images, probe_command:['docker', ...command], probe_sha256:hash(probe),
    stdout_sha256:crypto.createHash('sha256').update(stdout).digest('hex'), components,
    boundary_sha256:Object.fromEntries(boundary.map(file=>[file,hash(path.join(app,file))])),
    historical_private_artifact_presence:Object.fromEntries(privatePaths.map(file=>[file,fs.existsSync(file)])),
    scope:'Benign offline component recheck; probe isolation is NOT shipped Compose policy. No new advisory scan or full gate run.'});
  console.log(JSON.stringify({status:'captured', images, components_equal:true}));
  process.exit(0);
}
const observations = read(observationFile);
assert.equal(observations.application_revision, verification.revision);
assert.deepEqual(observations.components, verification.runtime.components);
assert.equal(hash(path.join(__dirname, 'security-closeout-runtime.py')), observations.probe_sha256);
for (const [file, digest] of Object.entries(observations.boundary_sha256)) assert.equal(hash(path.join(app,file)), digest, file);
for (const name of ['api','web']) {
  assert.equal(observations.images[name].id, audit.image_phase.images[name].id);
  assert.equal(observations.images[name].platform, 'linux/amd64');
  assert.equal(audit.reduced_match_comparison[name].equal, true);
  assert.equal(audit.reduced_match_comparison[name].count, inventory[name].matches.length);
  for (const key of ['added','removed','changed']) assert.equal(audit.reduced_match_comparison[name][key].length, 0);
}
const priority = new Set(['CVE-2026-5450','CVE-2026-19499','CVE-2026-19542','CVE-2026-77117',
  'CVE-2026-80489','CVE-2026-11822','CVE-2026-11824','CVE-2026-39113','CVE-2026-50812','CVE-2026-85091']);
const records = inventory.advisory_review.filter(row=>row.review_section === 'S04').map(row=>{
  const absent = ['required_perl_module_not_loadable_in_inspected_runtime',
    '32_bit_precondition_absent_in_inspected_64_bit_runtime'].includes(row.disposition);
  const matches = ['api','web'].flatMap(image=>inventory[image].matches.filter(match=>match.advisory === row.id)
    .map(match=>({image,package:match.package,version:match.version,severity:match.severity})));
  return {id:row.id, source_families:row.source_families, matches,
    review_basis:row.disposition, proposed_action:absent ? 'E_exact_image_precondition_exclusion' :
      priority.has(row.id) ? 'H_priority_unresolved_review' : 'R_scoped_residual_decision',
    evidence:'SECURITY_CLOSEOUT.md#s04--native-image-residuals-and-recovery-boundary',
    source:row.debian?.url || row.cna.url,
    owner_decision:'pending', accepted_by:null, accepted_at:null, review_due:null};
});
const counts = Object.fromEntries(unique(records.map(row=>row.proposed_action)).map(action=>[action,records.filter(row=>row.proposed_action===action).length]));
assert.equal(records.length,80);
assert.equal(unique(records.map(row=>row.id)).length,80);
assert.deepEqual(Object.values(counts),[11,10,59]);
assert.equal(records.reduce((sum,row)=>sum+row.matches.length,0),167);
const report = {schema:1, status:'proposed_not_accepted', application_revision:verification.revision,
  images:observations.images, input_sha256:Object.fromEntries(['security-closeout-inventory.json',
    'security-hardening-audit.json','security-hardening-verification.json',observationFile]
    .map(file=>[file,hash(path.join(__dirname,file))])),
  scope:'80 S04 CVEs / 167 matches; 17 interpreter CVEs remain in S02/S03; all 184 scanner matches retained',
  decision_policy:{risk_acceptance:'not_granted', proposed_owner:'MakersVault maintainer; confirm named approver',
    proposed_review_deadline:'Before candidate freeze/13D and within 30 days of acceptance, whichever comes first',
    reopen_on:['relevant vendor fix','new reachable path','changed image or architecture','weaker deployment or raw-backup trust boundary'],
    containment:'SECURITY_RESIDUAL_DECISIONS.md#proposed-next-slice--containment-before-acceptance'},
  counts, records};
if (process.argv[2] === '--write') writeNew(output, report);
else assert.deepEqual(read(output), report, 'Decision register drift; never manufacture owner acceptance');
assert.equal(git('diff', '--name-only', verification.revision, '--', ...sources), '');
let links = 0;
for (const name of ['docs/ARCHITECTURE_RUNBOOK.md','docs/ROADMAP.md','docs/security/GATE_13_REVALIDATION.md',
  'docs/evidence/gate-13/SECURITY_RESIDUAL_DECISIONS.md','docs/evidence/gate-13/TRACEABILITY.md',
  'docs/evidence/gate-13/SUBGATE_13C_RESULTS.md','docs/evidence/gate-13/SECURITY_CLOSEOUT.md']) {
  const file = path.join(app,name);
  const text = fs.readFileSync(file,'utf8');
  for (const match of text.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if (/^(https?:|#)/.test(match[1])) continue;
    assert(fs.existsSync(path.resolve(path.dirname(file),decodeURIComponent(match[1].split('#')[0]))), `${name}: ${match[1]}`);
    links++;
  }
  if (name.endsWith('ARCHITECTURE_RUNBOOK.md')) assert(/\| T-067[^\n]+\n\| T-068/.test(text), 'Split truth table');
}
console.log(JSON.stringify({status:'passed', mode:process.argv[2] || 'offline-check', counts,
  unique_cves:80, package_matches:167, retained_scanner_matches:184, accepted:0, local_links:links,
  scope:'Committed evidence consistency; not revalidation of unavailable private logs or release clearance'}));
