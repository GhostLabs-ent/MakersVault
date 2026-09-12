// Reconcile signed package bytes with vendor data; never changes scanner policy or grants waivers.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const app = path.resolve(__dirname,'../../..');
const root = path.join(os.homedir(),'.local/state/makersvault/verification');
const revision = 'a62bc11bf08742026cd469aec364fc043c1fb277';
const read = file => JSON.parse(fs.readFileSync(file,'utf8'));
const local = name => read(path.join(__dirname,name));
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const unique = values => [...new Set(values)].sort();
assert(process.argv.length <= 3 && [undefined,'--write'].includes(process.argv[2]));
const oldCheck = JSON.parse(execFileSync(process.execPath,[path.join(__dirname,'security-native-analysis.cjs')],{encoding:'utf8'}));
assert.equal(oldCheck.status,'passed');
const native = local('security-native-verification.json');
const proposal = local('security-disposition-proposal.json');
const event = local('security-owner-acceptance-2026-09-12.json');
let checkedHashes = 0;
const privateHash = file => {
  assert(!fs.lstatSync(file).isSymbolicLink(), file);
  assert.equal(fs.statSync(file).mode & 0o077, 0, file);
  checkedHashes++;
  return hash(file);
};
const runs = {};
for (const suffix of ['vendor-run','vendor-b-run','packages']) {
  const directory = path.join(root,'containment-reconciliation-'+suffix);
  assert.equal(fs.statSync(directory).mode & 0o077,0);
  const run = read(path.join(directory,'result.json'));
  assert.equal(run.exit_code,suffix==='vendor-run'?1:0);
  assert.equal(run.source_revision,revision);
  assert.equal(run.end_source_revision,revision);
  assert.equal(run.verification_source_status,'');
  assert.equal(run.end_verification_source_status,'');
  const raw_sha256 = Object.fromEntries(['started.json','result.json','stdout.log','stderr.log']
    .map(file=>[file,privateHash(path.join(directory,file))]));
  for (const row of run.artifacts) assert.equal(raw_sha256[row.file],row.sha256);
  runs[suffix] = {run,raw_sha256};
}
assert(fs.readFileSync(path.join(root,'containment-reconciliation-vendor-run/stderr.log'),'utf8')
  .includes('Feed size exceeds 32 MiB diagnostic bound'));
const vendorDirectory = path.join(root,'containment-reconciliation-vendor-b');
const vendor = read(path.join(vendorDirectory,'summary.json'));
const vendorHash = privateHash(path.join(vendorDirectory,'summary.json'));
const responseHash = privateHash(path.join(vendorDirectory,'response.json'));
assert.equal(vendor.status,'captured_not_disposition');
assert.equal(vendor.http_status,200);
assert.equal(vendor.input_sha256,hash(path.join(__dirname,'security-native-verification.json')));
assert.equal(privateHash(path.join(vendorDirectory,vendor.raw.file)),vendor.raw.sha256);
assert(vendor.raw.bytes > 32*1024*1024 && vendor.raw.bytes <= 128*1024*1024);
const feed = read(path.join(vendorDirectory,vendor.raw.file));
const packages = read(path.join(root,'containment-reconciliation-packages/stdout.log'));
assert(runs.packages.run.command.includes(native.lifecycle.images.api));
assert.equal(packages.status,'passed');
assert.equal(packages.index_update.exit_code,0);
for (const flag of ['APT::Update::Error-Mode=any','Acquire::AllowInsecureRepositories=false','APT::Get::AllowUnauthenticated=false'])
  assert(packages.index_update.command.includes(flag));
assert(packages.sources.includes('Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp'));
assert.deepEqual(packages.pins,native.installed_inventory.pins);
assert.deepEqual(Object.keys(packages.packages).sort(),Object.keys(packages.pins).sort());
const families = {'gzip':'gzip','libc-bin':'glibc','libc6':'glibc','libpcre2-8-0':'pcre2',
  'libsqlite3-0':'sqlite3','perl-base':'perl'};
const binaryProof = {};
for (const [name,row] of Object.entries(packages.packages)) {
  assert.equal(row.status,'verified_archive_and_installed_binaries');
  assert.equal(row.installed.exit_code,0);
  assert.equal(row.metadata.exit_code,0);
  assert.equal(row.download.exit_code,0);
  assert.equal(row.archive_sha256,row.archive_metadata.SHA256);
  assert.equal(row.archive_metadata.Package,name);
  assert.equal(row.archive_metadata.Version,packages.pins[name]);
  assert.equal(row.archive_metadata.Architecture,'amd64');
  assert.equal(row.archive_metadata.Source || name,families[name]);
  assert.deepEqual(row.installed.stdout.trim().split('\t'),[name,packages.pins[name],families[name],packages.pins[name]]);
  assert(row.installed_binary_checks.length > 0);
  assert.equal(unique(row.installed_binary_checks.map(item=>item.path)).length,row.installed_binary_checks.length);
  for (const item of row.installed_binary_checks) {
    assert(/^(usr\/)?(lib|bin|sbin)\//.test(item.path));
    assert(/^[a-f0-9]{64}$/.test(item.sha256));
  }
  assert(Object.keys(row.changelogs).length > 0);
  const entries = Object.values(row.changelogs).map(value=>value.first_entry).join('\n');
  assert(entries.startsWith(`${families[name]} (${packages.pins[name]}) trixie;`));
  binaryProof[name] = {version:packages.pins[name],source:families[name],archive:row.archive_metadata.Filename,
    archive_sha256:row.archive_sha256,archive_bytes:Number(row.archive_metadata.Size),
    regular_files_compared:row.installed_binary_checks.length,
    changelog_sha256:Object.fromEntries(Object.entries(row.changelogs).map(([file,value])=>[file,value.decompressed_sha256]))};
}
assert.equal(Object.values(binaryProof).reduce((n,row)=>n+row.regular_files_compared,0),931);
const allRows = [...native.records,...native.delta_review.new_records];
const targetRows = [...native.records.filter(row=>row.installed_fix),...native.delta_review.new_records];
assert.equal(targetRows.length,27);
const fixed = [];
for (const row of targetRows) {
  const family = families[row.matches[0].package];
  const data = feed[family]?.[row.id];
  assert(data?.releases?.trixie,row.id);
  const release = data.releases.trixie;
  const current = vendor.records.find(item=>item.id===row.id);
  assert.deepEqual(current.data,data);
  if (row.id==='CVE-2026-89092') {assert.equal(release.status,'open');continue;}
  assert.equal(release.status,'resolved',row.id);
  assert(row.matches.every(match=>release.fixed_version===packages.pins[match.package]));
  for (const match of row.matches) {
    const text = Object.values(packages.packages[match.package].changelogs).map(value=>value.first_entry).join('\n');
    assert(family==='pcre2' ? text.includes('upstream backports of security fixes from 10.48') : text.includes(row.id));
  }
  fixed.push({id:row.id,family,status:'vendor_fixed_and_installed_bytes_verified',
    fixed_version:release.fixed_version,source:`https://security-tracker.debian.org/tracker/${row.id}`,
    packages:unique(row.matches.map(match=>match.package)),retained_scanner_matches:row.matches.length,
    prior_status:row.status,owner_risk_waiver:'not_required_for_verified_fix',
    proof:'Current Debian per-release fixed version + authenticated APT archive hash + exact runtime regular-file byte comparison + packaged changelog. Not a source-level exploit test.'});
}
assert.equal(fixed.length,26);
assert.equal(fixed.reduce((n,row)=>n+row.retained_scanner_matches,0),28);
const fixedIds = new Set(fixed.map(row=>row.id));
const rawApi = read(path.join(root,'containment-native-image-audit/image-api.json'));
const retainedConflicts = rawApi.matches.filter(row=>fixedIds.has(row.vulnerability.id)).map(row=>({
  id:row.vulnerability.id,package:row.artifact.name,version:row.artifact.version,
  fix:row.vulnerability.fix,constraints:unique(row.matchDetails.map(detail=>detail.found.versionConstraint))}));
assert.equal(retainedConflicts.length,28);
assert(retainedConflicts.every(row=>row.fix.versions.length===0 && row.constraints.includes('none (unknown)')));
const holds = native.records.filter(row=>row.status==='held_unresolved_not_accepted').map(row=>{
  const prior = proposal.records.find(item=>item.id===row.id);
  assert.equal(prior.source_families.length,1);
  const family = prior.source_families[0];
  const release = feed[family]?.[row.id]?.releases?.trixie;
  assert.equal(release?.status,'open');
  return {id:row.id,status:'held_unresolved_not_accepted',family,trixie:release,
    rationale:prior.rationale,exit_criteria:prior.exit_criteria};
});
assert.equal(holds.length,7);
assert.equal(feed.perl['CVE-2026-9538'].releases.trixie.status,'open');
assert.equal(native.components.perl.modules_loadable['Archive::Tar'],false);
assert.equal(native.delta_probe.nscd.which,null);
assert.equal(native.delta_probe.nscd.package_search_exit,1);
assert.deepEqual(native.delta_probe.nscd.present_paths,[]);
const exclusions = [
  {id:'CVE-2026-9538',component:'Archive::Tar',evidence:'Required module not loadable in exact runtime; source remains open.'},
  {id:'CVE-2026-89092',component:'nscd',evidence:'Required service has no package-manifest or named executable in exact runtime; source remains open.'},
].map(row=>({...row,status:'proposed_exact_image_exclusion_not_accepted',accepted_by:null}));
const pending = native.records.filter(row=>row.status==='boundary_revalidated_new_image_exception_pending');
assert.equal(pending.length,52);
const dispositions = allRows.map(row=>({id:row.id,
  status:fixedIds.has(row.id)?'vendor_fixed_and_installed_bytes_verified'
    : exclusions.some(item=>item.id===row.id)?'proposed_exact_image_exclusion_not_accepted'
    : holds.some(item=>item.id===row.id)?'held_unresolved_not_accepted'
    : 'new_image_owner_exception_pending',
  matches:row.matches.map(match=>({image:match.image,package:match.package,version:match.version,severity:match.severity})),
  owner_acceptance:'none_granted_by_this_review'}));
assert.equal(dispositions.length,87);
assert.equal(unique(dispositions.map(row=>row.id)).length,87);
const inputNames = ['security-native-verification.json','security-disposition-proposal.json','security-owner-acceptance-2026-09-12.json'];
const inputs = {};
for (const name of inputNames) {
  const file = path.join(__dirname,name);
  assert(fs.readFileSync(file).equals(execFileSync('git',['show',revision+':makervault/docs/evidence/gate-13/'+name],{cwd:app})));
  inputs[name] = hash(file);
}
const report = {schema:1,status:'reconciled_vendor_fixes_not_risk_acceptance_or_security_closeout',
  reviewed_date:'2026-09-12',entry_revision:revision,application_revision:native.revision,
  images:native.lifecycle.images,platform:'linux/amd64',input_sha256:inputs,runs,
  vendor:{url:vendor.url,started_at:vendor.started_at,finished_at:vendor.finished_at,headers:vendor.headers,
    raw:vendor.raw,summary_sha256:vendorHash,response_sha256:responseHash},
  package_proof:binaryProof,fixed,retained_scanner_disagreements:retainedConflicts,
  scanner:{baseline:'security-native-verification.json',api_matches:189,web_matches:3,
    status:'Historical raw scan retained unchanged; not rerun or filtered',
    debian_capture:rawApi.descriptor.db.providers.debian.captured,db_built:rawApi.descriptor.db.status.built,
    explanation:'The retained scanner snapshot lacks vendor fixed-version ranges now supplied by the primary feed and authenticated binaries. Package applicability is reconciled; the precise upstream ingestion/refresh cause is not independently proven.'},
  counts:{native_cves:87,vendor_fixed:26,fixed_scanner_matches_retained:28,
    proposed_exclusions:2,pending_owner_exceptions:52,unresolved_holds:7,new_owner_acceptances:0},
  exclusions,pending_exception_ids:pending.map(row=>row.id),holds,dispositions,
  owner_boundary:{conditions:event.conditions,previous_deadline:event.review_deadline,
    statement:'No waiver transfer/renewal, release authority or gate acceptance. Original E/R event remains tied to its original image IDs.'},
  limitations:['Initial 32 MiB feed capture refused oversized decompressed content; failure retained, diagnostic bound increased to 128 MiB for one fresh capture.',
    'Signed binary archives and indexes were fetched only in a disposable exact-image container. No package was installed; downloads disappeared with it. Raw archive hashes, metadata, changelog extracts and 931 file comparisons are retained, not full .deb bodies.',
    'Only the 27 targeted/new CVEs and seven old holds plus the remaining Perl exclusion are refreshed from the captured feed. The 52 pending exception rationales are historical, not a newly granted or wholesale renewed review.',
    'No application tests, image scan, hostile-input exercise, patch-level source audit, full native call graph or new deployment qualification repeated in this diagnostic slice.',
    'The seven original holds remain; minor/no-dsa designations are not fixed versions or accepted risk.']};
const output=path.join(__dirname,'security-reconciliation.json');
if (process.argv[2]==='--write') fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
else assert.deepEqual(read(output),report);
const document = path.join(__dirname,'SECURITY_RECONCILIATION_RESULTS.md');
const documentText = fs.readFileSync(document,'utf8');
let localLinks = oldCheck.local_links;
for (const match of documentText.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
  if (/^(https?:|#)/.test(match[1])) continue;
  assert(fs.existsSync(path.resolve(path.dirname(document),decodeURIComponent(match[1].split('#')[0]))),match[1]);
  localLinks++;
}
assert(/\| T-072[^\n]+\n\| T-073/.test(fs.readFileSync(path.join(app,'docs/ARCHITECTURE_RUNBOOK.md'),'utf8')),'Split truth table');
console.log(JSON.stringify({status:'passed',private_hash_checks:checkedHashes,prior_hash_checks:oldCheck.private_hash_checks,
  signed_archives:6,regular_files_compared:931,counts:report.counts,local_links:localLinks}));
