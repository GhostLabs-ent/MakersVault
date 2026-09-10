// Read-only consistency checks; private raw artifacts are needed for hash checks.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const auditDirectory = process.argv[2];
const vendorFile = process.argv[3];
assert.equal(process.argv.length, 4, 'Supply private audit directory and vendor JSON');
const app = path.resolve(__dirname, '../../..');
const read = name => JSON.parse(fs.readFileSync(path.join(__dirname, name)));
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const audit = read('security-closeout-audit.json');
const inventory = read('security-closeout-inventory.json');
const runtime = read('security-closeout-runtime.json');
for (const [file, hash] of Object.entries(audit.lock_sha256)) assert.equal(digest(path.join(app,file)),hash,file);
for (const record of audit.raw_artifacts) {
  const file = path.join(auditDirectory,record.file);
  assert.equal(digest(file),record.sha256,record.file);
  assert.equal(fs.statSync(file).size,record.bytes);
}
assert.equal(digest(vendorFile),audit.vendor_snapshot.sha256);
assert.equal(audit.vendor_snapshot.cna_success,93);
assert.equal(audit.vendor_snapshot.debian_success,79);
assert.equal(inventory.api.matches.length,181);
assert.equal(inventory.web.matches.length,3);
assert.equal(inventory.advisory_review.length,97);
const ids = [...new Set([...inventory.api.matches,...inventory.web.matches].map(row=>row.advisory))].sort();
assert.deepEqual(ids,inventory.advisory_review.map(row=>row.id));
for (const row of inventory.advisory_review) {
  assert.equal(row.risk_acceptance,'not_granted');
  if (row.debian) assert(row.debian.trixie_rows.length > 0, `Missing Trixie evidence ${row.id}`);
}
assert(audit.reduced_match_comparison.api_equal);
assert(audit.reduced_match_comparison.web_equal);
assert.equal(runtime.api_image,inventory.images.api.id);
assert.equal(runtime.observation.pointer_bits,64);
assert.equal(runtime.observation.expat,'expat_2.8.3');
assert.equal(runtime.observation.packages.httpx2,null);
assert.equal(runtime.observation.perl.modules_loadable['Archive::Tar'],false);
assert.equal(runtime.observation.perl.modules_loadable.Socket,true);
const documents = ['docs/ARCHITECTURE_RUNBOOK.md','docs/BACKUP_AND_RECOVERY.md',
  'docs/ROADMAP.md','docs/security/GATE_13_REVALIDATION.md',
  'docs/evidence/gate-13/TRACEABILITY.md','docs/evidence/gate-13/SUBGATE_13C_RESULTS.md',
  'docs/evidence/gate-13/SECURITY_CLOSEOUT.md'];
let links = 0;
for (const name of documents) {
  const file = path.join(app,name);
  const source = fs.readFileSync(file,'utf8');
  for (const match of source.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    const target = match[1];
    if (/^(https?:|#)/.test(target)) continue;
    assert(fs.existsSync(path.resolve(path.dirname(file),decodeURIComponent(target.split('#')[0]))),`${name}: ${target}`);
    links++;
  }
  if (name.endsWith('ARCHITECTURE_RUNBOOK.md')) assert(/\| T-065[^\n]+\n\| T-066/.test(source),'Truth ledger table split');
}
console.log(JSON.stringify({result:'pass',unchanged_locks:Object.keys(audit.lock_sha256).length,
  raw_artifact_hashes:audit.raw_artifacts.length,vendor_snapshot_hash:true,
  image_matches:184,unique_image_advisories:97,local_document_links:links,
  risk_acceptances:0,scope:'Evidence consistency and links, not application or release qualification'}));
