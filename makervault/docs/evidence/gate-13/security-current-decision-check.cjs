// Join immutable qualification with a new pending owner proposal; never accept risk.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const app = path.resolve(__dirname,'../../..');
const root = path.join(os.homedir(),'.local/state/makersvault/verification');
const revision = '7349f93f2223fce325eaa14131bfdcc262a20fec';
const read = file => JSON.parse(fs.readFileSync(file,'utf8'));
const local = name => read(path.join(__dirname,name));
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const dataHash = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const unique = values => [...new Set(values)].sort();
assert(process.argv.length<=3 && [undefined,'--write'].includes(process.argv[2]));
const priorCheck = JSON.parse(execFileSync(process.execPath,[path.join(__dirname,'security-reconciliation-check.cjs')],{encoding:'utf8'}));
assert.equal(priorCheck.status,'passed');
const current = local('security-reconciliation.json');
const native = local('security-native-verification.json');
const oldProposal = local('security-disposition-proposal.json');
const inventory = local('security-closeout-inventory.json');
const review = local('security-current-decision-review.json');
assert.equal(review.status,'human_readable_engineering_review_not_owner_acceptance');
assert.deepEqual(Object.keys(review.notes).sort(),current.pending_exception_ids.slice().sort());
let checkedHashes=0;
const privateHash = file => {
  assert(!fs.lstatSync(file).isSymbolicLink());
  assert.equal(fs.statSync(file).mode & 0o077,0);
  checkedHashes++;
  return hash(file);
};
const runs = {};
for(const name of ['vendor-run','components','components-b']) {
  const directory = path.join(root,'containment-current-decision-'+name);
  assert.equal(fs.statSync(directory).mode & 0o077,0);
  const run = read(path.join(directory,'result.json'));
  assert.equal(run.exit_code,name==='components'?1:0);
  assert.equal(run.source_revision,revision);assert.equal(run.end_source_revision,revision);
  assert.equal(run.verification_source_status,'');assert.equal(run.end_verification_source_status,'');
  const raw_sha256=Object.fromEntries(['started.json','result.json','stdout.log','stderr.log']
    .map(file=>[file,privateHash(path.join(directory,file))]));
  for(const row of run.artifacts) assert.equal(raw_sha256[row.file],row.sha256);
  runs[name]={run,raw_sha256};
}
const failure=fs.readFileSync(path.join(root,'containment-current-decision-components/stderr.log'),'utf8');
assert(failure.includes('assert(report.web_packages.split'));
const directory=path.join(root,'containment-current-decision-vendor');
const vendor=read(path.join(directory,'summary.json'));
const vendorSummaryHash=privateHash(path.join(directory,'summary.json'));
assert.equal(vendor.status,'captured_not_accepted');
assert.equal(vendor.input_sha256,hash(path.join(__dirname,'security-reconciliation.json')));
assert.equal(vendor.script_sha256,hash(path.join(__dirname,'security-current-decision-collect.cjs')));
for(const row of Object.values(vendor.captures)) {
  assert.equal(row.status,'captured');assert.equal(row.http_status,200);
  assert.equal(privateHash(path.join(directory,row.file)),row.sha256);
  assert.equal(fs.statSync(path.join(directory,row.file)).size,row.bytes);
}
const feed=read(path.join(directory,'debian-feed.json'));
const previousFeed=read(path.join(root,'containment-reconciliation-vendor-b/debian-feed.json'));
assert.equal(vendor.records.length,86);
for(const row of vendor.records) {
  assert.deepEqual(row.data,feed[row.family][row.id]);
  assert.deepEqual(row.data,previousFeed[row.family][row.id]);
  assert.equal(row.previous_data_sha256,dataHash(previousFeed[row.family][row.id]));
  assert.equal(row.changed_since_reconciliation,false);
}
const cna=read(path.join(directory,'busybox-cna.json'));
assert.deepEqual(vendor.busybox_cna,cna);
assert.equal(cna.cveMetadata.cveId,'CVE-2025-60876');
assert.equal(vendor.captures['busybox-cna'].sha256,inventory.advisory_review.find(row=>row.id==='CVE-2025-60876').cna.sha256);
const probe=read(path.join(root,'containment-current-decision-components-b/stdout.log'));
assert.equal(probe.status,'passed');
assert.equal(probe.script_sha256,hash(path.join(__dirname,'security-current-decision-probe.cjs')));
for(const [name,sha] of Object.entries(probe.probe_sha256)) assert.equal(hash(path.join(__dirname,name)),sha);
for(const [name,id] of Object.entries(current.images)) {
  assert.deepEqual(probe.images[name],{id,os:'linux',architecture:'amd64',revision:current.application_revision});
}
assert.deepEqual(probe.components,native.components);
assert.deepEqual(probe.delta,native.delta_probe);
assert.equal(probe.components.perl.modules_loadable['Archive::Tar'],false);
assert.equal(probe.delta.nscd.which,null);assert.equal(probe.delta.nscd.package_search_exit,1);
assert.deepEqual(probe.delta.nscd.present_paths,[]);
assert.deepEqual(probe.web_packages,{'busybox':'1.37.0-r31','busybox-binsh':'1.37.0-r31','ssl_client':'1.37.0-r31'});
for(const row of probe.commands) {
  for(const flag of ['--network','none','--read-only','--cap-drop','ALL','no-new-privileges']) assert(row.command.includes(flag));
  assert(row.command.includes(current.images.api)||row.command.includes(current.images.web));
}
for(const row of current.fixed) {
  assert.equal(feed[row.family][row.id].releases.trixie.status,'resolved');
  assert.equal(feed[row.family][row.id].releases.trixie.fixed_version,row.fixed_version);
}
const conditions={...current.owner_boundary.conditions,
  C6:'No later than October 12, 2026 00:00 America/New_York, or 30 days after actual acceptance, or candidate freeze/13D, whichever is earliest. Reopen immediately for a relevant vendor fix, changed advisory/caller/input/image/platform, missing evidence or weaker controls. No automatic renewal or extension.'};
const records=current.dispositions.map(row=>{
  const previous=oldProposal.records.find(item=>item.id===row.id);
  const fixed=current.fixed.find(item=>item.id===row.id);
  const held=current.holds.find(item=>item.id===row.id);
  const excluded=current.exclusions.find(item=>item.id===row.id);
  const source=vendor.records.find(item=>item.id===row.id);
  const bucket=fixed?'F':held?'H':excluded?'E':'R';
  if(!fixed && source) {
    assert.equal(source.data.releases.trixie.status,'open',row.id);
    assert(!source.data.releases.trixie.fixed_version,row.id);
  }
  const special=row.id==='CVE-2025-60876';
  const rationale=fixed?'Vendor fix and installed-byte evidence retained; current source status unchanged.'
    :held?held.rationale:excluded?excluded.evidence:review.notes[row.id];
  const recommendation={F:'verified_fix_no_risk_waiver_requested',H:'keep_hold_unaccepted',
    E:'approve_exact_image_precondition_exclusion',R:'approve_time_limited_local_qualification_exception'}[bucket];
  return {id:row.id,bucket,recommendation,matches:row.matches,
    source_families:source?[source.family]:previous.source_families,
    current_review:rationale,prior_rationale:previous?.rationale||null,
    primary_source:source?`https://security-tracker.debian.org/tracker/${row.id}`:vendor.captures['busybox-cna'].url,
    vendor_review:source?{status:'fresh_unchanged_source_record',record_sha256:dataHash(source.data),trixie:source.data.releases.trixie}
      :{status:'fresh_unchanged_CNA_distribution_fix_unverified',sha256:vendor.captures['busybox-cna'].sha256,
        cna_updated:cna.cveMetadata.dateUpdated,limitation:vendor.alpine_current_fix_status},
    exit_criteria:fixed?'Reopen if image, package or vendor evidence changes.'
      :held?held.exit_criteria:excluded?'Reopen if the absent required component is introduced, evidence changes, or the image/platform changes.'
      :previous.exit_criteria,
    conditions:Object.keys(conditions),
    additional_acknowledgment:special?'Explicitly acknowledge unavailable current Alpine backport/fix confirmation; this is only a temporary local-qualification residual exception, not evidence of no available fix.':null,
    owner_decision:fixed?'not_requested_verified_fix':held?'not_requested_hold':'pending',
    accepted_by:null,accepted_at:null,review_due:null};
});
assert.equal(records.length,87);assert.equal(unique(records.map(row=>row.id)).length,87);
const counts=Object.fromEntries(['F','E','R','H'].map(bucket=>{
  const rows=records.filter(row=>row.bucket===bucket);
  return [bucket,{cves:rows.length,matches:rows.reduce((sum,row)=>sum+row.matches.length,0)}];
}));
assert.deepEqual(Object.fromEntries(Object.entries(counts).map(([key,row])=>[key,row.cves])),{F:26,E:2,R:52,H:7});
const severityMatches={};
for(const row of records.filter(row=>row.bucket==='R')) for(const match of row.matches)
  severityMatches[match.severity]=(severityMatches[match.severity]||0)+1;
assert.deepEqual(severityMatches,{Negligible:44,Low:6,Medium:39,High:44});
const inputs={};
for(const name of ['security-reconciliation.json','security-native-verification.json','security-disposition-proposal.json',
  'security-owner-acceptance-2026-09-12.json','security-closeout-inventory.json']) {
  const file=path.join(__dirname,name);
  assert(fs.readFileSync(file).equals(execFileSync('git',['show',revision+':makervault/docs/evidence/gate-13/'+name],{cwd:app})));
  inputs[name]=hash(file);
}
inputs['security-current-decision-review.json']=hash(path.join(__dirname,'security-current-decision-review.json'));
const report={schema:1,status:'owner_proposal_pending_no_acceptance',prepared_date:'2026-09-12',entry_revision:revision,
  application_revision:current.application_revision,images:current.images,platform:'linux/amd64',input_sha256:inputs,
  owner_policy:{proposed_approver:'VincentCinque, repository maintainer',conditions,
    proposed_deadline:{not_after:'2026-10-12T00:00:00-04:00',earlier_events:['30 days after actual acceptance','candidate freeze','Gate 13D','any C6 reopen trigger']},
    requested_decision:'Approve only enumerated E2/R52 under C1-C7, explicitly acknowledge the BusyBox distribution-fix evidence gap, and leave H7 unaccepted. Record a new exact-image event only after explicit approval.',
    accepted_by:null,accepted_at:null},
  counts,residual_severity_matches:severityMatches,
  unchanged_scanner:{api_matches:189,web_matches:3,total_matches:192,total_cves:104,separate_interpreter_cves:17,
    statement:'Retained dated scans, no rescan/filter/suppression. F26 technical resolution does not remove its 28 historical matches.'},
  vendor:{summary_sha256:vendorSummaryHash,captures:vendor.captures,reviewed_debian_ids:86,changed_scoped_records:0,
    proposed_debian_residuals_open_without_recorded_trixie_fix:51,busybox_current_distribution_fix_status:'unverified'},
  probe:{images:probe.images,components_equal_previous:true,delta_equal_previous:true,web_packages:probe.web_packages,
    script_sha256:probe.script_sha256,probe_sha256:probe.probe_sha256},runs,records,
  limitations:['Preparation is not an owner decision, old-image waiver transfer, S04/G13-04 closure or Gate 13C/13D acceptance.',
    'Fresh feed comparison covers only 86 known Debian IDs; unchanged scoped records do not prove no new advisories elsewhere. BusyBox CNA is refreshed, not an Alpine package-fix confirmation.',
    'The first probe failed an apk info output assertion after the API probes. It is incomplete; final retry reads the installed APK manifest and retains both attempts. No runtime policy or network restriction weakened.',
    'Full qualification and scanner captures are the prior unchanged-image evidence, rechecked through retained hashes; no new full suite, deployed-instance inspection, hostile-input test or exhaustive native call graph.',
    'Known native memory-corruption, writable-vault, denial-of-service, privileged operator recovery and data-loss residuals remain. No end-user upload limits or configuration changed.']};
const output=path.join(__dirname,'security-current-decision-proposal.json');
if(process.argv[2]==='--write') fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
else assert.deepEqual(read(output),report);
let localLinks=priorCheck.local_links;
const doc=path.join(__dirname,'SECURITY_CURRENT_IMAGE_DECISION.md');
assert(fs.existsSync(doc));
assert(/\| T-073[^\n]+\n\| T-074/.test(fs.readFileSync(path.join(app,'docs/ARCHITECTURE_RUNBOOK.md'),'utf8')),'Split truth table');
for(const match of fs.readFileSync(doc,'utf8').matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
  if(/^(https?:|#)/.test(match[1]))continue;
  assert(fs.existsSync(path.resolve(__dirname,decodeURIComponent(match[1].split('#')[0]))),match[1]);localLinks++;
}
console.log(JSON.stringify({status:'passed',counts,private_hash_checks:checkedHashes,
  prior_private_hash_checks:priorCheck.private_hash_checks+priorCheck.prior_hash_checks,
  reviewed_debian_ids:86,changed_scoped_records:0,new_acceptances:0,local_links:localLinks}));
