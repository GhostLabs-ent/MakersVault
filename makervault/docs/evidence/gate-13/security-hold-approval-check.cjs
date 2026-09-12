// Read-only validation of the explicit two-exclusion decision and combined register.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const read = name => JSON.parse(fs.readFileSync(path.join(__dirname, name), 'utf8'));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const revision = '00f707d8b3adddae9c33b7a659dd04d6737ddc1d';
const prefix = 'makervault/docs/evidence/gate-13/';
assert(process.argv.length <= 3 && [undefined, '--print-event', '--self-test'].includes(process.argv[2]));
const evidence = JSON.parse(execFileSync(process.execPath,
  [path.join(__dirname, 'security-hold-review-check.cjs')], {encoding: 'utf8'}));
assert.equal(evidence.status, 'passed');
const artifacts = [
  'security-hold-review.json', 'security-current-owner-acceptance-2026-09-12.json',
  'security-current-decision-proposal.json', 'SECURITY_HOLD_REVIEW.md',
].map(file => {
  const original = execFileSync('git', ['show', revision + ':' + prefix + file]);
  // The dated human proposal may gain a clearly labeled subsequent-decision link.
  if (file.endsWith('.json')) assert(fs.readFileSync(path.join(__dirname, file)).equals(original), file);
  return {file, sha256: hash(original)};
});
const prior = read('security-current-owner-acceptance-2026-09-12.json');
const review = read('security-hold-review.json');
const proposal = read('security-current-decision-proposal.json');
const ids = ['CVE-2026-39113', 'CVE-2026-85091'];
assert.deepEqual(review.candidates.map(row => row.id), ids);
assert.deepEqual(review.images, prior.images);
assert.equal(review.application_revision, prior.application_revision);
assert.equal(review.platform, prior.platform);
assert.deepEqual(review.remaining.map(row => row.id).sort(), prior.unaccepted_holds.filter(id => !ids.includes(id)).sort());
const event = {
  schema: 1, kind: 'owner_approval_event', approval_date: '2026-09-12', approval_timezone: 'America/New_York',
  recorded_at: '2026-09-12T20:27:22Z',
  timestamp_basis: 'First observation clock for this approval turn, not an invented message-click timestamp.',
  approved_by: 'VincentCinque', role: 'Repository maintainer',
  authorization: {
    user_response: 'approved',
    responds_to: 'Approve these two exclusions under the existing conditions and unchanged October 12-or-earlier deadline?',
    proposal_commit: revision, artifacts,
  },
  application_revision: prior.application_revision, images: prior.images, platform: prior.platform,
  conditions: prior.conditions, review_deadline: prior.review_deadline,
  decisions: review.candidates.map(row => ({
    id: row.id, source: row.source, previous_bucket: 'H', bucket: 'E',
    decision: 'accepted_exact_image_source_precondition_exclusion',
    approved_by: 'VincentCinque', approval_date: '2026-09-12',
    review_due: prior.review_deadline.not_after, matches: row.matches,
    rationale: row.rationale, limitation: row.limitation.replace('exclusion proposal', 'exclusion'), reopen: row.reopen,
  })),
  unaccepted_holds: review.remaining.map(row => row.id),
  aggregate_counts: {accepted_exclusions: 4, accepted_residuals: 52, verified_fixes: 26, unaccepted_holds: 5},
  scanner_inventory_retained: prior.scanner_inventory_retained,
  limits: [
    'Only the two named H entries move to E. The five remaining holds are unresolved and unaccepted.',
    'No installed fix, vendor affected-row correction, scanner suppression or whole-library safety claim.',
    'C1-C7 and the October 12-or-earlier deadline remain unchanged; no automatic renewal or transfer.',
    'Earlier approval events and technical proposals remain immutable. Interpreter dispositions are unchanged.',
    'No new advisory fetch, source/runtime probe, full-suite run or image scan is claimed by this recording.',
    'No application, dependency, image, schema, release-pin or model-byte change. No push, publication or deployment.',
    'S04/G13-04 and Gate 13C/13D remain open; no acceptance of the remaining five holds or release clearance.',
  ],
};
const validate = actual => assert.deepEqual(actual, event);
if (process.argv[2] === '--print-event') {
  console.log(JSON.stringify(event, null, 2));
} else {
  validate(read('security-hold-owner-acceptance-2026-09-12.json'));
  const priorIds = new Set(prior.decisions.map(row => row.id));
  const records = proposal.records.map(row => {
    if (ids.includes(row.id)) { assert.equal(row.bucket, 'H'); assert(!priorIds.has(row.id)); return {...row, bucket: 'E'}; }
    if (['E', 'R'].includes(row.bucket)) assert(priorIds.has(row.id));
    return row;
  });
  assert.equal(new Set(records.map(row => row.id)).size, 87);
  const totals = Object.fromEntries(['E', 'R', 'F', 'H'].map(bucket =>
    [bucket, records.filter(row => row.bucket === bucket).length]));
  assert.deepEqual(totals, {E: 4, R: 52, F: 26, H: 5});
  assert.deepEqual(records.filter(row => row.bucket === 'H').map(row => row.id).sort(), event.unaccepted_holds.slice().sort());
  let negativeControls = 0;
  if (process.argv[2] === '--self-test') {
    for (const mutate of [
      value => value.decisions.push({...value.decisions[0], id: value.unaccepted_holds[0]}),
      value => { value.images.api = value.images.web; },
      value => { value.review_deadline.not_after = '2026-11-12T00:00:00-05:00'; },
      value => { value.conditions.C7 = 'Release approved'; },
      value => { value.authorization.artifacts[0].sha256 = '0'.repeat(64); },
      value => value.unaccepted_holds.pop(),
    ]) {
      const changed = structuredClone(event); mutate(changed);
      assert.throws(() => validate(changed), assert.AssertionError); negativeControls++;
    }
  }
  let localLinks = evidence.local_links;
  const document = fs.readFileSync(path.join(__dirname, 'SECURITY_HOLD_OWNER_ACCEPTANCE.md'), 'utf8');
  for (const match of document.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if (/^(https?:|#)/.test(match[1])) continue;
    assert(fs.existsSync(path.resolve(__dirname, decodeURIComponent(match[1].split('#')[0]))), match[1]); localLinks++;
  }
  const runbook = fs.readFileSync(path.resolve(__dirname, '../../ARCHITECTURE_RUNBOOK.md'), 'utf8');
  assert(/\| T-075[^\n]+\n\| T-076/.test(runbook), 'Split truth table');
  console.log(JSON.stringify({status: 'passed', counts: event.aggregate_counts, native_ids: records.length,
    private_hash_checks: evidence.private_hash_checks + evidence.prior_private_hash_checks,
    proposal_artifact_hashes: artifacts.length, local_links: localLinks, negative_controls: negativeControls,
    deadline: event.review_deadline.not_after, security_closeout: 'open'}));
}
