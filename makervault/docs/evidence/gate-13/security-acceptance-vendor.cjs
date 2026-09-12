// Bounded public vendor-page refresh. No scanner, dependency update or acceptance.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const read = name => JSON.parse(fs.readFileSync(path.join(__dirname, name), 'utf8'));
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const proposal = read('security-disposition-proposal.json');
const inventory = read('security-closeout-inventory.json');
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
const output = path.join(root, 'containment-acceptance-vendor');
assert.equal(process.argv.length, 2);
assert(!fs.lstatSync(root).isSymbolicLink());
assert.equal(fs.statSync(root).mode & 0o077, 0);
fs.mkdirSync(output, {mode:0o700}); // Refuse an existing capture.
const clean = html => html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
  .replace(/<\/(tr|h1|h2|p|pre)>/gi, '\n').replace(/<\/?[^>]+>/g, ' ')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
  .replace(/&#39;/g, "'").replace(/&amp;/g, '&').replace(/[ \t]+/g, ' ').trim();
const results = {};
const started = new Date().toISOString();
let index = 0;
async function worker() {
  while (index < proposal.records.length) {
    const row = proposal.records[index++];
    const debian = row.matches.every(match=>match.image==='api');
    const url = debian ? `https://security-tracker.debian.org/tracker/${row.id}`
      : `https://security.alpinelinux.org/vuln/${row.id}`;
    const record = {id:row.id,bucket:row.bucket,url,started_at:new Date().toISOString()};
    try {
      const response = await fetch(url,{redirect:'error',signal:AbortSignal.timeout(15000)});
      record.http_status = response.status;
      assert(response.ok, `HTTP ${response.status}`);
      const parts = [];
      let count = 0;
      for await (const part of response.body) {
        count += part.length;
        assert(count <= 512*1024, 'Vendor page exceeds bound');
        parts.push(part);
      }
      const bytes = Buffer.concat(parts);
      record.raw_file = `${row.id}.html`;
      fs.writeFileSync(path.join(output,record.raw_file),bytes,{flag:'wx',mode:0o600});
      record.sha256 = digest(bytes);
      const text = clean(bytes.toString('utf8'));
      assert(text.includes(row.id), 'Unexpected response page');
      if (debian) {
        assert(text.includes('Vulnerable and fixed packages'), 'Missing Debian package table');
        const before = inventory.advisory_review.find(old=>old.id===row.id).debian;
        record.trixie_rows = text.split('\n').map(line=>line.trim())
          .filter(line=>/\btrixie\b/.test(line) && /\b(vulnerable|fixed|source)\b/.test(line));
        record.prior_trixie_rows = before.trixie_rows;
      } else {
        assert(text.includes('CVE-2025-60876'), 'Unexpected Alpine record');
        record.scope = 'Alpine page retained for review; no automatic fix/applicability inference';
      }
      record.status = 'captured';
    } catch(error) { record.status = 'unavailable'; record.error = error.message; }
    record.finished_at = new Date().toISOString();
    results[row.id] = record;
  }
}
async function main() {
  await Promise.all(Array.from({length:4},worker));
  const report = {schema:1,started_at:started,finished_at:new Date().toISOString(),
    proposal_sha256:digest(fs.readFileSync(path.join(__dirname,'security-disposition-proposal.json'))),
    scope:'80 exact S04 IDs: vendor pages only, no language/image scanner or installed-package update',
    records:Object.fromEntries(Object.entries(results).sort())};
  fs.writeFileSync(path.join(output,'summary.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});
  console.log(JSON.stringify({output,records:Object.keys(results).length,
    unavailable:Object.values(results).filter(row=>row.status!=='captured').map(row=>({id:row.id,error:row.error})),
    fixed_trixie:Object.values(results).filter(row=>row.trixie_rows?.some(line=>/\bfixed\b/.test(line)))
      .map(row=>({id:row.id,bucket:row.bucket,rows:row.trixie_rows,prior:row.prior_trixie_rows}))}));
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
