// Verify current evidence and documentation without mutating the vault or artifacts.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const app = path.resolve(__dirname,'../../..');
const read = file=>JSON.parse(fs.readFileSync(path.join(__dirname,file)));
const digest = file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const audit = read('security-hardening-audit.json');
const verification = read('security-hardening-verification.json');
const revision = verification.revision;
assert.equal(audit.source_revision,revision);
assert.equal(audit.risk_acceptance,'not_granted');
assert.equal(verification.results.api_tests,422);
assert.equal(verification.results.lifecycle.dirty,false);
let hashes = 0;
for (const [file,hash] of Object.entries(audit.language_phase.lock_sha256)) {
  assert.equal(digest(path.join(app,file)),hash,file); hashes++;
}
for (const [phase,artifacts] of Object.entries(audit.raw_artifacts)) {
  const directory = '/tmp/makersvault-security-hardening-'+(phase === 'languages' ? 'language-audit' : 'image-audit');
  for (const artifact of artifacts) {
    assert.equal(digest(path.join(directory,artifact.file)),artifact.sha256); hashes++;
  }
}
for (const [name,run] of Object.entries(verification.runs)) {
  const directory = '/tmp/makersvault-security-hardening-'+name;
  assert.equal(digest(path.join(directory,'result.json')),run.record_sha256); hashes++;
  for (const artifact of run.artifacts) {
    assert.equal(digest(path.join(directory,artifact.file)),artifact.sha256); hashes++;
  }
}
for (const name of ['api','web']) {
  assert(audit.reduced_match_comparison[name].equal);
  assert.equal(audit.image_phase.images[name].id,verification.results.lifecycle.images[name]);
}
const unchanged = ['api/http_security.py','api/auth.py','api/passkey_config.py','api/migrations.py',
  'api/requirements.lock','api/requirements-build.lock','api/Dockerfile','web/Dockerfile',
  'docker-compose.yml','docker-compose.deploy.yml','docker-deploy.yml'];
for (const name of unchanged) {
  const old = execFileSync('git',['show','b371ff8:makervault/'+name],{cwd:app});
  assert(fs.readFileSync(path.join(app,name)).equals(old),`Out-of-scope change: ${name}`);
}
const documents = ['docs/ARCHITECTURE_RUNBOOK.md','docs/ROADMAP.md','docs/SECURE_DEPLOYMENT.md',
  'docs/RELEASE_NOTES_v5.1.0.md','docs/security/GATE_13_REVALIDATION.md',
  'docs/evidence/gate-13/TRACEABILITY.md','docs/evidence/gate-13/SUBGATE_13C_RESULTS.md',
  'docs/evidence/gate-13/SECURITY_CLOSEOUT.md','docs/evidence/gate-13/SECURITY_HARDENING_RESULTS.md'];
let links = 0;
for (const name of documents) {
  const file = path.join(app,name);
  const source = fs.readFileSync(file,'utf8');
  for (const match of source.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if (/^(https?:|#)/.test(match[1])) continue;
    assert(fs.existsSync(path.resolve(path.dirname(file),decodeURIComponent(match[1].split('#')[0]))),`${name}: ${match[1]}`);
    links++;
  }
  if (name.endsWith('ARCHITECTURE_RUNBOOK.md')) assert(/\| T-066[^\n]+\n\| T-067/.test(source),'Split truth ledger table');
}
console.log(JSON.stringify({status:'passed',hashes_verified:hashes,local_links:links,
  unchanged_boundary_files:unchanged.length,source_revision:revision,
  scope:'Evidence consistency; not security acceptance or release qualification'}));
