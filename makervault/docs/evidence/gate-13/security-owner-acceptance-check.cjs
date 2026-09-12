// Verify the dated owner event and subsequent C6 review; never grant new acceptance.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const read = file => JSON.parse(fs.readFileSync(file,'utf8'));
const local = name => read(path.join(__dirname,name));
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const root = path.join(os.homedir(),'.local/state/makersvault/verification');
const app = path.resolve(__dirname,'../../..');
const eventFile = 'security-owner-acceptance-2026-09-12.json';
const output = path.join(__dirname,'security-acceptance-review-2026-09-12.json');
assert(process.argv.length <= 3 && [undefined,'--write'].includes(process.argv[2]));
const baseline = JSON.parse(execFileSync(process.execPath,[path.join(__dirname,'security-disposition-check.cjs')],{encoding:'utf8'}));
assert.equal(baseline.status,'passed'); // Its accepted:0 is the immutable proposal, not this event.
const proposal = local('security-disposition-proposal.json');
const event = local(eventFile);
const verified = local('security-containment-verification.json');
assert.equal(event.kind,'owner_approval_event');
assert.equal(event.approved_by,'VincentCinque');
assert.equal(event.approval_date,'2026-09-12');
assert.equal(event.approval_timezone,'America/New_York');
assert.equal(event.recorded_at,'2026-09-12T16:20:40Z');
assert.equal(event.authorization.user_response,'yes approved');
assert.equal(event.authorization.proposal_commit,'f93109f38134e2d492400660566db88386887e1c');
assert.equal(event.authorization.proposal_sha256,hash(path.join(__dirname,'security-disposition-proposal.json')));
assert.deepEqual(event.images,proposal.images);
assert.equal(event.application_revision,proposal.application_revision);
assert.deepEqual(event.conditions,proposal.owner_policy.conditions);
assert.equal(event.release_authority,'none');
assert.equal(event.gate_closure,'none');
assert.equal(event.review_deadline.not_after,'2026-10-12T00:00:00-04:00');
assert(Date.parse(event.review_deadline.not_after) <= Date.parse('2026-09-12T00:00:00-04:00')+30*86400000);
assert.deepEqual(event.review_deadline.earlier_events,['candidate freeze','Gate 13D','any C6 reopen condition']);
assert.deepEqual(event.explicit_critical_risk_acceptances,['CVE-2026-12087','CVE-2026-13221']);
assert.deepEqual(event.retained_scanner_matches,{api:181,web:3});
assert.deepEqual(event.decisions,proposal.records.map(row=>({id:row.id,bucket:row.bucket,
  decision:{E:'approved_exact_image_exclusion',R:'accepted_temporary_local_qualification_risk',H:'hold_not_accepted'}[row.bucket],
  approved_by:row.bucket==='H'?null:'VincentCinque',approval_date:row.bucket==='H'?null:'2026-09-12',
  review_due:row.bucket==='H'?null:event.review_deadline.not_after,proposal_entry:row.id})));
let hashes = 0;
const privateHash = file => {
  assert(!fs.lstatSync(file).isSymbolicLink(),file);
  assert.equal(fs.statSync(file).mode & 0o077,0,file);
  hashes++;
  return hash(file);
};
const runs = {};
for (const suffix of ['vendor-run','components','cli']) {
  const directory = path.join(root,'containment-acceptance-'+suffix);
  assert.equal(fs.statSync(directory).mode & 0o077,0);
  const run = read(path.join(directory,'result.json'));
  assert.equal(run.exit_code,0);
  assert.equal(run.source_revision,event.authorization.proposal_commit);
  assert.equal(run.end_source_revision,run.source_revision);
  assert.equal(run.verification_source_status,'');
  assert.equal(run.end_verification_source_status,'');
  const digests = Object.fromEntries(['started.json','result.json','stdout.log','stderr.log']
    .map(file=>[file,privateHash(path.join(directory,file))]));
  for (const artifact of run.artifacts) assert.equal(digests[artifact.file],artifact.sha256);
  if (suffix !== 'vendor-run') assert(run.command.includes(event.images.api.id));
  runs[suffix] = {run,raw_sha256:digests};
}
const components = read(path.join(root,'containment-acceptance-components/stdout.log'));
const cli = read(path.join(root,'containment-acceptance-cli/stdout.log'));
assert.deepEqual(components,verified.components);
assert.deepEqual(cli,proposal.probe.observations);
const vendorDirectory = path.join(root,'containment-acceptance-vendor');
const vendor = read(path.join(vendorDirectory,'summary.json'));
const vendorHash = privateHash(path.join(vendorDirectory,'summary.json'));
assert.equal(vendor.proposal_sha256,event.authorization.proposal_sha256);
assert.deepEqual(Object.keys(vendor.records).sort(),proposal.records.map(row=>row.id).sort());
// Exact table rows only: prose such as "Will be fixed ..." is never a fixed package.
const trixieRows = html => [...html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)]
  .map(match=>[...match[1].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/gi)]
    .map(cell=>cell[1].replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim()))
  .filter(cells=>cells.length===4 && /\btrixie\b/.test(cells[1]) && /^(?:fixed|vulnerable)$/.test(cells[3]))
  .map(cells=>cells.slice(1).join(' '));
assert.deepEqual(trixieRows('<tr><td>pkg</td><td>trixie</td><td>1.0</td><td>fixed</td></tr><pre>[trixie] Will be fixed first in unstable</pre>'),['trixie 1.0 fixed']);
assert.deepEqual(trixieRows('<tr><td></td><td>trixie (security), trixie</td><td>2.0</td><td>vulnerable</td></tr>'),['trixie (security), trixie 2.0 vulnerable']);
const reviews = proposal.records.map(row=>{
  const source = vendor.records[row.id];
  let rows = [];
  if (source.status === 'captured') {
    const file = path.join(vendorDirectory,source.raw_file);
    assert.equal(privateHash(file),source.sha256);
    rows = trixieRows(fs.readFileSync(file,'utf8'));
    assert(rows.length>0,row.id);
  } else {
    assert.equal(row.id,'CVE-2025-60876');
    assert.equal(source.http_status,406);
  }
  const fixed = rows.some(line=>/ fixed$/.test(line));
  const currentStatus = row.bucket==='H' ? (fixed ? 'held_supported_fix_identified_not_installed' : 'held_unresolved')
    : row.bucket==='E' ? (fixed ? 'approved_exclusion_revalidated_after_vendor_fix_review' : 'approved_exact_image_exclusion')
    : fixed ? 'reopened_vendor_fix_no_active_exception' : 'accepted_temporary_local_qualification_risk';
  return {id:row.id,bucket:row.bucket,current_status:currentStatus,
    supported_fix_identified:fixed,source:source.url,raw_sha256:source.sha256 || null,
    source_status:source.status,prior_trixie_rows:source.prior_trixie_rows || [],trixie_rows:rows,
    vendor_note:source.status==='captured' ? 'Strict package table extraction; distro fix availability is not an installed fix'
      : 'Collector HTTP 406 retained. Separate browser reread succeeded; no archived fresh Alpine body. Prior dated disposition retained, not cleared.',
    acceptance_event_id:row.id,
    rationale:row.bucket==='E' ? 'Owner-approved exact-image precondition still absent in fresh component/CLI observations; vendor fix review completed without expanding exclusion or altering bytes.'
      : fixed ? 'C6 requires renewed disposition when a relevant supported fix exists; old images remain unpatched.'
      : row.bucket==='H' ? row.exit_criteria : 'Unchanged image/call boundary and approved C1-C7; no new fixed Trixie table row identified in this bounded refresh.'};
});
const fixedIds = reviews.filter(row=>row.supported_fix_identified).map(row=>row.id).sort();
const reopened = reviews.filter(row=>row.current_status==='reopened_vendor_fix_no_active_exception').map(row=>row.id).sort();
assert.deepEqual(reopened,['CVE-2026-12087','CVE-2026-13221','CVE-2026-41991','CVE-2026-41992','CVE-2026-57432','CVE-2026-5928','CVE-2026-86145']);
assert.equal(fixedIds.length,20);
assert.equal(reviews.filter(row=>row.bucket==='E' && row.supported_fix_identified).length,10);
assert.equal(reviews.filter(row=>row.bucket==='H' && row.supported_fix_identified).length,3);
const counts = {approved_exclusions:11,approved_exception_events:59,active_local_exceptions:52,
  reopened_exceptions:7,original_holds:10,open_residual_cves:17,retained_api_matches:181,retained_web_matches:3};
assert.equal(reviews.filter(row=>row.current_status==='accepted_temporary_local_qualification_risk').length,counts.active_local_exceptions);
const reviewedFiles = ['api/Dockerfile','api/db.py','api/recovery.py','api/recovery_mutation.py'];
const report = {schema:1,status:'approval_recorded_c6_reopen_applied_not_security_closeout',
  reviewed_date:'2026-09-12',approval_event:eventFile,approval_event_sha256:hash(path.join(__dirname,eventFile)),
  proposal_sha256:event.authorization.proposal_sha256,images:event.images,
  review_deadline:event.review_deadline,counts,runs,components,cli,
  vendor:{directory:vendorDirectory,summary_sha256:vendorHash,started_at:vendor.started_at,
    finished_at:vendor.finished_at,captured_pages:79,unavailable_pages:1,
    extraction_note:'Collector diagnostic shortlist also contained acl/attr prose about future fixes. Strict table-row reducer rejects those three; not new fixed packages, suppressions or discarded raw evidence.'},
  checked_application_sha256:Object.fromEntries(reviewedFiles.map(file=>[file,hash(path.join(app,file))])),
  fixed_ids:fixedIds,reopened_exception_ids:reopened,records:reviews,
  limitations:['No new full application suite, image/language scan, installed fix or release clearance',
    'Sourceware was not retried; Debian bug/SQLite source endpoints unavailable through browser review remain evidence gaps',
    'Existing source evidence is not an exhaustive native call graph; raw SQLite remains trusted operator input',
    'No scheduled monitor installed; recheck vendor/conditions at the next checkpoint or deadline']};
if (process.argv[2]==='--write') fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
else assert.deepEqual(read(output),report);
let links=0;
for (const name of ['SECURITY_OWNER_ACCEPTANCE.md']) {
  const text=fs.readFileSync(path.join(__dirname,name),'utf8');
  for (const match of text.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if (/^(https?:|#)/.test(match[1])) continue;
    assert(fs.existsSync(path.resolve(__dirname,decodeURIComponent(match[1].split('#')[0]))),match[1]);
    links++;
  }
}
console.log(JSON.stringify({status:'passed',counts,new_private_hash_checks:hashes,
  prior_containment_hash_checks:baseline.containment_hash_checks,prior_probe_hash_checks:baseline.probe_hash_checks,local_links:links}));
