// Validate source/build observations and pending exclusions, not new owner waivers.
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const read=file=>JSON.parse(fs.readFileSync(file,'utf8'));
const sha=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const textHash=text=>crypto.createHash('sha256').update(text).digest('hex');
const local=name=>read(path.join(__dirname,name));
const root=path.join(os.homedir(),'.local/state/makersvault/verification');
const app=path.resolve(__dirname,'../../..');
const revision='4af19f77b8acffd6db4361eb68834e3657d82045';
assert(process.argv.length<=3 && [undefined,'--write'].includes(process.argv[2]));
const approvalCheck=JSON.parse(execFileSync(process.execPath,[path.join(__dirname,'security-current-approval-check.cjs')],{encoding:'utf8'}));
assert.equal(approvalCheck.status,'passed');
const event=local('security-current-owner-acceptance-2026-09-12.json');
const proposal=local('security-current-decision-proposal.json');
const primary=local('security-hold-primary-review.json');
assert.deepEqual(primary.debian_pages.map(row=>row.id).sort(),event.unaccepted_holds.slice().sort());
let checkedHashes=0;
const privateHash=file=>{
  assert(!fs.lstatSync(file).isSymbolicLink());assert.equal(fs.statSync(file).mode&0o077,0);
  checkedHashes++;return sha(file);
};
const runs={};
for(const name of ['containment-held-source','containment-held-source-b']) {
  const directory=path.join(root,name);
  assert.equal(fs.statSync(directory).mode&0o077,0);
  const run=read(path.join(directory,'result.json'));
  assert.equal(run.exit_code,name.endsWith('-b')?0:1);
  assert.equal(run.source_revision,revision);assert.equal(run.end_source_revision,revision);
  assert.equal(run.verification_source_status,'');assert.equal(run.end_verification_source_status,'');
  assert(run.command.includes(event.images.api));
  const hashes=Object.fromEntries(['started.json','result.json','stdout.log','stderr.log']
    .map(file=>[file,privateHash(path.join(directory,file))]));
  for(const row of run.artifacts) assert.equal(hashes[row.file],row.sha256);
  runs[name]={run,raw_sha256:hashes};
}
const first=read(path.join(root,'containment-held-source/stdout.log'));
assert.equal(first.status,'failed');assert.equal(first.error,'AssertionError()');
assert.equal(first.packages.zlib.installed,'zlib1g\t1:1.3.dfsg+really1.3.1-1+b1\tzlib\t1:1.3.dfsg+really1.3.1-1');
const probe=read(path.join(root,'containment-held-source-b/stdout.log'));
assert.equal(probe.status,'passed_not_disposition');
assert.equal(probe.script_sha256,sha(path.join(__dirname,'security-hold-source.py')));
assert.equal(probe.sources,fs.readFileSync(path.join(__dirname,'security-hold-source.sources'),'utf8'));
for(const command of probe.commands) assert.equal(command.exit_code,0);
const update=probe.commands.find(row=>row.command[0]==='apt-get'&&row.command.includes('update'));
for(const flag of ['APT::Update::Error-Mode=any','Acquire::AllowInsecureRepositories=false','APT::Get::AllowUnauthenticated=false']) assert(update.command.includes(flag));
assert(probe.sources.includes('Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp'));
const sourceProof={};
for(const [name,row] of Object.entries(probe.packages)) {
  assert.equal(row.source_metadata.Package,name);assert.equal(row.source_metadata.Version,row.version);
  const expected=Object.fromEntries(row.source_metadata['Checksums-Sha256'].trim().split('\n').map(line=>{
    const [hash,,file]=line.trim().split(/\s+/);return [file,hash];
  }));
  assert.deepEqual(row.source_archive_sha256,expected);
  assert.equal(row.binary_metadata.Package,row.binary);assert.equal(row.binary_metadata.Version,row.binary_version);
  assert.equal(row.binary_metadata.Architecture,'amd64');assert.equal(row.binary_archive_sha256,row.binary_metadata.SHA256);
  assert.deepEqual(row.installed.split('\t'),[row.binary,row.binary_version,name,row.version]);
  for(const file of Object.values(row.selected_text)) assert.equal(textHash(file.text),file.sha256);
  const active=row.series.split('\n').map(line=>line.split('#')[0].trim()).filter(Boolean).map(line=>line.split(/\s+/)[0]);
  for(const patch of Object.values(row.patches)) assert.equal(textHash(patch.text),patch.sha256);
  for(const name of active) assert(row.patches['debian/patches/'+name],name);
  const changedPaths=active.flatMap(name=>row.patches['debian/patches/'+name].changed_paths);
  assert(!changedPaths.some(file=>/(^|\/)(sqlar\.c|sqlite3session\.c|gzwrite\.c|gzguts\.h)$/.test(file)));
  assert.equal(row.installed_file_checks.length,1);
  sourceProof[name]={source_version:row.version,binary:row.binary,binary_version:row.binary_version,
    source_archive_sha256:row.source_archive_sha256,binary_archive_sha256:row.binary_archive_sha256,
    source_directory:row.source_metadata.Directory,installed_file_checks:row.installed_file_checks,
    selected_file_sha256:Object.fromEntries(Object.entries(row.selected_text).map(([file,value])=>[file,value.sha256])),
    active_patches:active,active_patch_target_paths:changedPaths,
    active_patch_sha256:Object.fromEntries(active.map(name=>[name,row.patches['debian/patches/'+name].sha256]))};
}
assert.equal(sourceProof.sqlite3.active_patches.length,15);assert.equal(sourceProof.zlib.active_patches.length,0);
const sqlar=probe.packages.sqlite3.selected_text['sqlite3-3.46.1/ext/misc/sqlar.c'].text;
assert(sqlar.includes('sz = sqlite3_value_int(argv[1]);'));
assert(!sqlar.includes('sqlite3_value_int64'));
const session=probe.packages.sqlite3.selected_text['sqlite3-3.46.1/ext/session/sqlite3session.c'].text;
assert(session.includes('int sqlite3changeset_apply_v2('));assert(!session.includes('sqlite3changeset_apply_v3'));
assert(session.includes('sqlite3_value_type(pVal)'));
assert(probe.packages.sqlite3.selected_text['debian/rules'].text.includes('-DSQLITE_ENABLE_SESSION'));
const gzip=probe.packages.zlib.selected_text['zlib-1.3.1/gzwrite.c'].text;
assert(!/gz_vacate|EAGAIN|EWOULDBLOCK/.test(gzip));
assert(/if \(writ < 0\) \{\s+gz_error\(state, Z_ERRNO, zstrerror\(\)\);\s+return -1;/.test(gzip));
assert(gzip.includes('state->mode != GZ_WRITE || state->err != Z_OK'));
const candidates=[
  {id:'CVE-2026-39113',source:'sqlite3',rationale:'The authenticated source uses sqlite3_value_int, not the later int64 size read identified by the CVE and upstream introduction commit; none of 15 active Debian patches changes sqlar.c. Matched installed library and absent default SQLar functions corroborate the bounded source-precondition exclusion.'},
  {id:'CVE-2026-85091',source:'zlib',rationale:'Authenticated 1.3.1 source has no gz_vacate/EAGAIN/EWOULDBLOCK handling; write failure sets Z_ERRNO and returns, and printf checks the error state. No Debian patches introduce the later nonblocking implementation; installed libz bytes match the authenticated binary archive.'},
].map(row=>({...row,status:'proposed_exact_image_source_precondition_exclusion',owner_decision:'pending',accepted_by:null,
  matches:proposal.records.find(item=>item.id===row.id).matches,conditions:Object.keys(event.conditions),
  review_due_if_accepted:event.review_deadline.not_after,
  limitation:'Debian still marks the source affected. This is a narrowly reasoned exact-image exclusion proposal, not a vendor correction, installed fix, whole-library safety proof or independently reproduced build.',
  reopen:'Changed image/source/build/component/advisory or contrary evidence reopens immediately; no transfer to a rebuild or another architecture.'}));
const remaining=proposal.records.filter(row=>row.bucket==='H'&&!candidates.some(item=>item.id===row.id))
  .map(row=>({id:row.id,status:'unresolved_hold_not_accepted',matches:row.matches,exit_criteria:row.exit_criteria,
    current_evidence:row.id==='CVE-2026-50812'?'Exact source also lacks apply_v3, but older SESSION/apply and sqlite3_value_type paths remain; upstream fix page unavailable, so shared-code applicability is unresolved.'
      :row.id==='CVE-2026-19542'?'tdelete defect identified, but referenced fix page unavailable and no exact native caller/source exclusion established.'
      :'Current Debian page has no description; referenced Red Hat and Debian bug pages unavailable. Do not infer safety from missing detail.'}));
assert.equal(remaining.length,5);
const native=local('security-native-verification.json');
assert.deepEqual(native.components.sqlite_archive_functions,[]);
const report={schema:1,status:'bounded_hold_review_complete_two_exclusions_proposed_not_accepted',reviewed_date:'2026-09-12',
  entry_revision:revision,application_revision:event.application_revision,images:event.images,platform:event.platform,
  input_sha256:Object.fromEntries(['security-current-decision-proposal.json','security-current-owner-acceptance-2026-09-12.json','security-hold-primary-review.json']
    .map(name=>[name,sha(path.join(__dirname,name))])),runs,source_proof:sourceProof,primary_review:primary,
  counts:{existing_accepted_exclusions:2,existing_accepted_residuals:52,verified_fixes:26,still_unaccepted_holds:7,
    proposed_additional_exclusions:2,remaining_unresolved:5,new_hold_acceptances:0},candidates,remaining,
  unchanged_scanner:{api_matches:189,web_matches:3,status:'No new image scan, filtering or suppression'},
  limits:['Signed APT metadata authenticates downloaded source and binary hashes; not an independent source-to-binary reproducible rebuild.',
    'Source and binary archives were inspected only in disposable containers, then removed with their temporary directories. Selected source/patch text, metadata/hashes and file comparisons remain in private logs; full archives are not retained.',
    'The first probe failed because zlib binary +b1 differs from its source version. The corrected probe pins both exactly; no package was changed.',
    'APT reported root download fallback inside private disposable scratch directories; authentication remained required. No host APT configuration, image, vault or runtime privilege policy changed.',
    'No patches applied, source built, package installed, hostile input executed, deployed instance inspected or complete native call graph proved.',
    'Owner E2/R52 approval does not accept these additional H exclusions; all seven remain unaccepted until a separate explicit decision.']};
const output=path.join(__dirname,'security-hold-review.json');
if(process.argv[2]==='--write')fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
else assert.deepEqual(read(output),report);
let localLinks=approvalCheck.local_links;
for(const name of ['SECURITY_CURRENT_OWNER_ACCEPTANCE.md','SECURITY_HOLD_REVIEW.md']) {
  const file=path.join(__dirname,name);
  for(const match of fs.readFileSync(file,'utf8').matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if(/^(https?:|#)/.test(match[1]))continue;
    assert(fs.existsSync(path.resolve(__dirname,decodeURIComponent(match[1].split('#')[0]))),match[1]);
    localLinks++;
  }
}
assert(/\| T-074[^\n]+\n\| T-075/.test(fs.readFileSync(path.join(app,'docs/ARCHITECTURE_RUNBOOK.md'),'utf8')),'Split truth table');
console.log(JSON.stringify({status:'passed',private_hash_checks:checkedHashes,prior_private_hash_checks:approvalCheck.prior_private_hash_checks,
  authenticated_source_packages:2,matched_runtime_libraries:2,counts:report.counts,local_links:localLinks}));
