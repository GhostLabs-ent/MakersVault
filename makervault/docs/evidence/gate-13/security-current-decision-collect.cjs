// Read-only C6 refresh for the already enumerated native CVEs; no scan or waiver.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const read = file => JSON.parse(fs.readFileSync(file,'utf8'));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const root = path.join(os.homedir(),'.local/state/makersvault/verification');
const output = path.join(root,'containment-current-decision-vendor');
assert.equal(process.argv.length,2);
assert(!fs.lstatSync(root).isSymbolicLink());
assert.equal(fs.statSync(root).mode & 0o077,0);
fs.mkdirSync(output,{mode:0o700});
const current = read(path.join(__dirname,'security-reconciliation.json'));
const proposal = read(path.join(__dirname,'security-disposition-proposal.json'));
const previous = read(path.join(root,'containment-reconciliation-vendor-b/debian-feed.json'));
const captures = {};
async function capture(name,url,maxBytes) {
  const row = captures[name] = {url,started_at:new Date().toISOString()};
  try {
    const response = await fetch(url,{redirect:'error',signal:AbortSignal.timeout(60000)});
    row.http_status = response.status;
    row.last_modified = response.headers.get('last-modified');
    assert(response.ok,`HTTP ${response.status}`);
    const parts = [];
    let size = 0;
    for await (const part of response.body) {
      size += part.length;
      assert(size <= maxBytes,'Decoded response exceeds diagnostic bound');
      parts.push(part);
    }
    const bytes = Buffer.concat(parts);
    row.file = name+'.json'; row.bytes = bytes.length; row.sha256 = sha(bytes);
    fs.writeFileSync(path.join(output,row.file),bytes,{flag:'wx',mode:0o600});
    row.status = 'captured';
    return JSON.parse(bytes);
  } catch(error) {row.status='unavailable';row.error=error.message;return null;}
  finally {row.finished_at=new Date().toISOString();}
}
async function main() {
  const [feed,cna] = await Promise.all([
    capture('debian-feed','https://security-tracker.debian.org/tracker/data/json',128*1024*1024),
    capture('busybox-cna','https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/2025/60xxx/CVE-2025-60876.json',1024*1024),
  ]);
  const records = current.dispositions.filter(row=>row.matches.every(match=>match.image==='api')).map(row=>{
    const family = proposal.records.find(old=>old.id===row.id)?.source_families[0]
      || (row.id==='CVE-2026-89092'?'glibc':'pcre2');
    const data = feed?.[family]?.[row.id] || null;
    const before = previous[family]?.[row.id] || null;
    return {id:row.id,family,data,previous_data_sha256:sha(JSON.stringify(before)),
      changed_since_reconciliation:JSON.stringify(data)!==JSON.stringify(before)};
  });
  assert.equal(records.length,86);
  const report = {schema:1,status:feed&&cna&&records.every(row=>row.data)?'captured_not_accepted':'incomplete',
    input_sha256:sha(fs.readFileSync(path.join(__dirname,'security-reconciliation.json'))),
    script_sha256:sha(fs.readFileSync(__filename)),captures,records,
    busybox_cna:cna,alpine_current_fix_status:'Unverified: prior advisory collector HTTP 406 and current v3.24 secdb browser non-retryable error. No blocked endpoint retried; CNA is not Alpine backport evidence.'};
  fs.writeFileSync(path.join(output,'summary.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});
  console.log(JSON.stringify({status:report.status,captures,records:records.length,
    changed:records.filter(row=>row.changed_since_reconciliation).map(row=>row.id),
    pending_trixie:records.filter(row=>current.pending_exception_ids.includes(row.id))
      .map(row=>({id:row.id,family:row.family,description:row.data?.description,trixie:row.data?.releases?.trixie}))}));
  if(report.status==='incomplete') process.exitCode=1;
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
