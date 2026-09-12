// Validate the explicit five-risk approval and the combined, dated native register.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const read = name => JSON.parse(fs.readFileSync(path.join(__dirname, name), 'utf8'));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const revision = 'acaa4f6a46fedaebb48187c04366e53ee795c2ec';
assert(process.argv.length <= 3 && [undefined, '--print-event', '--self-test'].includes(process.argv[2]));
const evidence = JSON.parse(execFileSync(process.execPath,
  [path.join(__dirname, 'security-remaining-review-check.cjs')], {encoding: 'utf8'}));
assert.equal(evidence.status, 'passed');
const artifacts = ['security-remaining-proposal.json', 'security-hold-owner-acceptance-2026-09-12.json',
  'security-current-owner-acceptance-2026-09-12.json', 'SECURITY_REMAINING_DECISION.md'].map(file => {
  const bytes = execFileSync('git', ['show', revision + ':makervault/docs/evidence/gate-13/' + file]);
  if (file.endsWith('.json')) assert(fs.readFileSync(path.join(__dirname, file)).equals(bytes), file);
  return {file, sha256: hash(bytes)};
});
const proposal = read('security-remaining-proposal.json');
const base = read('security-current-decision-proposal.json');
const earlier = read('security-current-owner-acceptance-2026-09-12.json');
const exclusions = read('security-hold-owner-acceptance-2026-09-12.json');
const ids = ['CVE-2026-19499', 'CVE-2026-19542', 'CVE-2026-50812', 'CVE-2026-77117', 'CVE-2026-80489'];
assert.deepEqual(proposal.records.map(row => row.id), ids);
assert.deepEqual(exclusions.unaccepted_holds, ids);
for (const record of proposal.records) {
  assert.equal(record.current_bucket, 'H'); assert.equal(record.proposed_bucket, 'R');
  assert.equal(record.owner_decision, 'pending'); assert.equal(record.accepted_by, null);
}
const event = {
  schema: 1, kind: 'owner_approval_event', approval_date: '2026-09-12', approval_timezone: 'America/New_York',
  recorded_at: '2026-09-12T22:32:12Z',
  timestamp_basis: 'First observation clock for this approval turn, not an invented message-click timestamp.',
  approved_by: 'VincentCinque', role: 'Repository maintainer',
  authorization: {user_response: 'Yes approved',
    responds_to: 'Do you approve these five temporary local-risk exceptions under those conditions?',
    proposal_commit: revision, artifacts},
  application_revision: proposal.application_revision, images: proposal.images, platform: proposal.platform,
  conditions: proposal.conditions, review_deadline: proposal.review_deadline,
  explicit_acknowledgments: [...proposal.required_acknowledgments,
    'The accepted impacts include potential native code execution, data loss and disclosure; this is not proof of application exploitability or safety.'],
  decisions: proposal.records.map(row => ({id: row.id, previous_bucket: 'H', bucket: 'R',
    decision: 'accepted_temporary_local_qualification_risk', approved_by: 'VincentCinque',
    approval_date: '2026-09-12', review_due: proposal.review_deadline.not_after,
    proposal_entry: row.id, matches: row.matches})),
  aggregate_counts: {accepted_exclusions: 4, accepted_residuals: 57, verified_fixes: 26, unaccepted_holds: 0},
  unaccepted_holds: [], scanner_inventory_retained: proposal.unchanged_scanner,
  limits: ['Only the five named holds move to R, not E or F. Existing exclusion/fix decisions are unchanged.',
    'Local native disposition accounting is complete for these exact development images; vulnerable packages and residual risks remain.',
    'C1-C7, BusyBox and other earlier caveats, and the October 12-or-earlier deadline remain unchanged; no extension or automatic renewal.',
    'No transfer to a rebuild, architecture, desktop or public candidate. Candidate freeze/13D and C6 triggers reopen decisions.',
    'Earlier proposal/approval JSON is immutable. No new vendor fetch, runtime probe, full suite or image scan accompanies this event.',
    'No application, dependency, image, schema, release-pin or model-byte change; no push, publication or deployment.',
    'S04/G13-04 and Gate 13C/13D are still open. Remaining platform/operator and matched release-candidate qualification require their own evidence and decisions.']};
for (const previous of [earlier, exclusions]) {
  assert.deepEqual(previous.images, event.images); assert.deepEqual(previous.conditions, event.conditions);
  assert.deepEqual(previous.review_deadline, event.review_deadline);
  assert.equal(previous.application_revision, event.application_revision); assert.equal(previous.platform, event.platform);
}
const validate = actual => assert.deepEqual(actual, event);
if (process.argv[2] === '--print-event') console.log(JSON.stringify(event, null, 2));
else {
  validate(read('security-remaining-owner-acceptance-2026-09-12.json'));
  const decisions = [...earlier.decisions, ...exclusions.decisions, ...event.decisions];
  const byId = new Map(decisions.map(row => [row.id, row]));
  assert.equal(decisions.length, 61); assert.equal(byId.size, 61);
  const records = base.records.map(row => {
    if (row.bucket === 'F') { assert(!byId.has(row.id)); return row; }
    assert(byId.has(row.id), row.id); return {...row, bucket: byId.get(row.id).bucket};
  });
  assert.equal(new Set(records.map(row => row.id)).size, 87);
  assert.deepEqual(Object.fromEntries(['E', 'R', 'F', 'H'].map(bucket =>
    [bucket, records.filter(row => row.bucket === bucket).length])), {E: 4, R: 57, F: 26, H: 0});
  let negatives = 0;
  if (process.argv[2] === '--self-test') for (const mutate of [
    value => { value.decisions[0].id = exclusions.decisions[0].id; },
    value => { value.decisions[0].bucket = 'F'; },
    value => { value.images.api = value.images.web; },
    value => { value.review_deadline.not_after = '2026-11-12T00:00:00-05:00'; },
    value => { value.conditions.C7 = 'Public release accepted'; },
    value => { value.authorization.artifacts[0].sha256 = '0'.repeat(64); },
  ]) { const copy = structuredClone(event); mutate(copy); assert.throws(() => validate(copy), assert.AssertionError); negatives++; }
  let links = evidence.local_links;
  const doc = fs.readFileSync(path.join(__dirname, 'SECURITY_REMAINING_OWNER_ACCEPTANCE.md'), 'utf8');
  for (const match of doc.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if (/^(https?:|#)/.test(match[1])) continue;
    assert(fs.existsSync(path.resolve(__dirname, decodeURIComponent(match[1].split('#')[0]))), match[1]); links++;
  }
  assert(/\| T-077[^\n]+\n\| T-078/.test(fs.readFileSync(path.resolve(__dirname, '../../ARCHITECTURE_RUNBOOK.md'), 'utf8')));
  console.log(JSON.stringify({status: 'passed', counts: event.aggregate_counts, native_ids: records.length,
    private_hash_checks: evidence.new_private_hash_checks + evidence.prior_private_hash_checks,
    proposal_artifact_hashes: artifacts.length, local_links: links, negative_controls: negatives,
    deadline: event.review_deadline.not_after, security_closeout: 'open',
    validation_scope: 'Recorded decision and retained evidence, not automatic current-time exception validity.'}));
}
