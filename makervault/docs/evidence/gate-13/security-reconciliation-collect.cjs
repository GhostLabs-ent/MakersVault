// Capture the public Debian source feed, bounded and private; no remediation.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const root = path.join(os.homedir(),'.local/state/makersvault/verification');
assert(process.argv.length <= 3 && [undefined,'b'].includes(process.argv[2]));
const output = path.join(root,'containment-reconciliation-vendor'+(process.argv[2] ? '-'+process.argv[2] : ''));
const input = path.join(__dirname,'security-native-verification.json');
const verified = JSON.parse(fs.readFileSync(input,'utf8'));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const families = {'libc6':'glibc','libc-bin':'glibc','gzip':'gzip','perl-base':'perl',
  'libpcre2-8-0':'pcre2','libsqlite3-0':'sqlite3'};
const targets = [...verified.records.filter(row=>row.installed_fix), ...verified.delta_review.new_records];
assert.equal(targets.length,27);
assert.equal(fs.statSync(root).mode & 0o077,0);
assert(!fs.lstatSync(root).isSymbolicLink());
fs.mkdirSync(output,{mode:0o700});
async function main() {
  const started_at = new Date().toISOString();
  const url = 'https://security-tracker.debian.org/tracker/data/json';
  const response = await fetch(url,{redirect:'error',signal:AbortSignal.timeout(60000)});
  assert(response.ok, `HTTP ${response.status}`);
  fs.writeFileSync(path.join(output,'response.json'),JSON.stringify({url,started_at,status:response.status,
    content_length:response.headers.get('content-length'),content_encoding:response.headers.get('content-encoding')},null,2)+'\n',
    {flag:'wx',mode:0o600});
  const parts=[];
  let bytes=0;
  for await (const part of response.body) {
    bytes+=part.length;
    assert(bytes<=128*1024*1024, 'Decompressed feed size exceeds 128 MiB diagnostic bound');
    parts.push(part);
  }
  const body=Buffer.concat(parts);
  fs.writeFileSync(path.join(output,'debian-feed.json'),body,{flag:'wx',mode:0o600});
  const feed=JSON.parse(body);
  const records=targets.map(row=>{
    const family=families[row.matches[0].package];
    assert(family,row.id);
    const source=feed[family]?.[row.id];
    return {id:row.id,family,status:source?'present':'missing',
      data:source || null, installed:row.matches.map(match=>({package:match.package,version:match.version}))};
  });
  const report={schema:1,status:'captured_not_disposition',started_at,finished_at:new Date().toISOString(),
    url,http_status:response.status,headers:{date:response.headers.get('date'),last_modified:response.headers.get('last-modified'),
      etag:response.headers.get('etag')},raw:{file:'debian-feed.json',bytes:body.length,sha256:sha(body)},
    input_sha256:sha(fs.readFileSync(input)),records};
  fs.writeFileSync(path.join(output,'summary.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});
  console.log(JSON.stringify({output,...report,records:records.map(row=>({id:row.id,family:row.family,
    status:row.status,trixie:row.data?.releases?.trixie}))}));
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
