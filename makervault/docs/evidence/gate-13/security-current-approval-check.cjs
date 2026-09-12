// Record the explicit September 12 E2/R52 approval, preserving the pending proposal.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const proposalFile = path.join(__dirname,'security-current-decision-proposal.json');
const read = file => JSON.parse(fs.readFileSync(file,'utf8'));
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const revision = '4af19f77b8acffd6db4361eb68834e3657d82045';
assert(process.argv.length<=3 && [undefined,'--record'].includes(process.argv[2]));
const check=JSON.parse(execFileSync(process.execPath,[path.join(__dirname,'security-current-decision-check.cjs')],{encoding:'utf8'}));
assert.equal(check.status,'passed');
const proposal=read(proposalFile);
assert(fs.readFileSync(proposalFile).equals(execFileSync('git',['show',revision+':makervault/docs/evidence/gate-13/security-current-decision-proposal.json'])));
const selected=proposal.records.filter(row=>['E','R'].includes(row.bucket));
assert.equal(selected.filter(row=>row.bucket==='E').length,2);
assert.equal(selected.filter(row=>row.bucket==='R').length,52);
const event={schema:1,kind:'owner_approval_event',approval_date:'2026-09-12',approval_timezone:'America/New_York',
  recorded_at:'2026-09-12T20:04:44Z',
  timestamp_basis:'First observation clock for this approval turn. Original message has no second-resolution timestamp; this is not a fabricated click time.',
  approved_by:'VincentCinque',role:'Repository maintainer',
  authorization:{user_response:'yes approved',
    responds_to:'Do you approve this scoped package under its documented conditions, including the BusyBox caveat?',
    proposal_commit:revision,proposal_file:path.basename(proposalFile),proposal_sha256:sha(proposalFile)},
  application_revision:proposal.application_revision,images:proposal.images,platform:proposal.platform,
  conditions:proposal.owner_policy.conditions,review_deadline:proposal.owner_policy.proposed_deadline,
  explicit_acknowledgments:{
    busybox_cve:'CVE-2025-60876',
    busybox_evidence_gap:'Current Alpine backport/fix status could not be confirmed. The owner explicitly accepts that evidence limitation for this temporary exact-image local-qualification exception; it is not proof that no fix exists.',
    residual_severity_matches:proposal.residual_severity_matches,
    authority:'C1-C7, local qualification only; no publication/deployment/security-gate clearance or acceptance of H7.'},
  decisions:selected.map(row=>({id:row.id,bucket:row.bucket,
    decision:row.bucket==='E'?'accepted_exact_image_precondition_exclusion':'accepted_temporary_local_qualification_risk',
    approved_by:'VincentCinque',approval_date:'2026-09-12',review_due:proposal.owner_policy.proposed_deadline.not_after,
    proposal_entry:row.id})),
  unaccepted_holds:proposal.records.filter(row=>row.bucket==='H').map(row=>row.id),
  verified_fixes_not_waivers:proposal.records.filter(row=>row.bucket==='F').map(row=>row.id),
  scanner_inventory_retained:proposal.unchanged_scanner,
  limits:['New explicit exact-image event, not a transfer or extension of the prior E11/R59 approval.',
    'No automatic renewal; October 12 midnight or earlier C6/candidate-freeze/13D deadline remains.',
    'Continue bounded H review only; further remediation or H risk acceptance requires its own informed decision.',
    'Historical proposal and prior approval JSON remain unchanged. No scanner suppression or S04/G13-04/Gate 13C/13D closure.']};
assert.equal(event.unaccepted_holds.length,7);assert.equal(event.verified_fixes_not_waivers.length,26);
const output=path.join(__dirname,'security-current-owner-acceptance-2026-09-12.json');
if(process.argv[2]==='--record') fs.writeFileSync(output,JSON.stringify(event,null,2)+'\n',{flag:'wx'});
else assert.deepEqual(read(output),event);
console.log(JSON.stringify({status:'passed',accepted_exclusions:2,accepted_residuals:52,unaccepted_holds:7,
  verified_fixes:26,prior_private_hash_checks:check.private_hash_checks+check.prior_private_hash_checks,
  deadline:event.review_deadline.not_after,proposal_sha256:event.authorization.proposal_sha256,local_links:check.local_links}));
