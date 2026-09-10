// Read-only reducer for this slice's synthetic reports. No fixture keys or log bodies.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

function regular(file) {
  assert(fs.lstatSync(file).isFile(), `Not a regular file: ${file}`);
  return fs.readFileSync(file);
}
function json(file) { return JSON.parse(regular(file)); }
function hash(file) {
  return { path: file, sha256: crypto.createHash('sha256').update(regular(file)).digest('hex') };
}
function directory(dir) {
  assert(fs.lstatSync(dir).isDirectory(), `Not a real directory: ${dir}`);
}
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])]));
  }
  return value;
}
function records(rows) { return rows.map(row => JSON.stringify(stable(row))).sort(); }

const dispositions = {
  a: 'Development Chromium picker pass on 744886b; translucent surface corrected later. Not final-image qualification.',
  b: 'Unqualified mixed-source attempt: lean-ctx wrapper hit its 120-second limit, parent ended and raw summary remains in_progress. Source changed during execution; no result counts toward qualification. Exact abandoned fixture was subsequently cleaned.',
  'debug-a': 'Diagnostic WebKit assertion-location probe on 744886b images with later harness; Tab focus-wrap assertion failed. Not final-image qualification.',
  c: 'Final 76b526d application and harness: Chromium ordering plus Chromium/Firefox/WebKit folder-picker regression matrix.',
  d: 'Final 76b526d application / 53142f9 harness: unprofiled 600-Artifact/104-folder organization matrix, Chromium preview and mounted import.',
  e: 'Final 76b526d application / 53142f9 harness: second fresh unprofiled Chromium 600-Artifact/104-folder repeat.',
  f: 'Final 76b526d application / 53142f9 harness: third fresh unprofiled Chromium 600-Artifact/104-folder repeat.',
  g: 'Final 76b526d application / 53142f9 harness: separate unprofiled 600-Artifact/1040-folder Chromium stress case; not a baseline substitute.',
  h: 'Final 76b526d application / 10c7481 harness: fresh unprofiled 600-Artifact/1040-folder stress after explicit bulk-completion wait; G remains unchanged and failed.',
  i: 'Final 76b526d application / 10c7481 harness: fresh unprofiled 600-Artifact/104-folder baseline after the bulk-completion wait; not a replacement for D-F.',
};

function browserRun(id) {
  assert(Object.hasOwn(dispositions, id), 'Unknown run ID');
  const root = id === 'debug-a' ? '/tmp/makersvault-g13c-picker-debug-0909a' : `/tmp/makersvault-g13c-picker-0909${id}`;
  directory(root);
  const artifacts = [];
  const reports = {};
  let summary;
  for (const name of fs.readdirSync(root).sort()) {
    const file = path.join(root, name);
    if (name === 'summary.json') {
      summary = json(file);
      artifacts.push(hash(file));
    } else if (/^(organization|ordering|folder-picker|preview|mount)-(chromium|firefox|webkit)$/.test(name)) {
      directory(file);
      const report = {};
      for (const child of fs.readdirSync(file).sort()) {
        assert(/^(baseline\.json|corpus-manifest\.json|startup-(chromium|firefox|webkit)\.json|stdout\.txt|stderr\.txt|(folder-picker|selection-toolbar)-(chromium|firefox|webkit)\.png)$/.test(child), `Unexpected artifact: ${child}`);
        const source = path.join(file, child);
        artifacts.push(hash(source));
        if (child.endsWith('.json')) report[child] = json(source);
      }
      reports[name] = report;
    } else throw new Error(`Unexpected output entry: ${name}`);
  }
  assert(summary, 'Missing runner summary');
  return { id, disposition: dispositions[id], output_root: root, summary, reports, raw_artifacts: artifacts };
}

function audit() {
  const root = '/tmp/makersvault-g13c-picker-audit-0909';
  directory(root);
  const summary = json(path.join(root, 'summary.json'));
  assert.equal(summary.status, 'audit_completed_not_release_clearance');
  const prior = json(path.join(__dirname, 'remediation-image-matches.json'));
  const comparison = { prior_record: 'remediation-image-matches.json', comparison: 'All reduced advisory/package/version/severity/source/namespace/location/match/fix records compared as sorted JSON objects' };
  for (const target of ['api', 'web']) {
    const report = json(path.join(root, `image-${target}.json`));
    const reduced = report.matches.map(m => ({
      advisory: m.vulnerability.id, severity: m.vulnerability.severity,
      source: m.vulnerability.dataSource, namespace: m.vulnerability.namespace,
      package: m.artifact.name, version: m.artifact.version, type: m.artifact.type,
      locations: m.artifact.locations.map(l => l.path),
      match_types: m.matchDetails.map(d => d.type),
      fix_state: m.vulnerability.fix.state, fix_versions: m.vulnerability.fix.versions,
    }));
    assert.equal(reduced.length, summary.scans[`image-${target}`].matches);
    comparison[`${target}_equal`] = JSON.stringify(records(reduced)) === JSON.stringify(records(prior[target].matches));
    if (!comparison[`${target}_equal`]) comparison[`${target}_current_records`] = reduced;
  }
  const raw_artifacts = fs.readdirSync(root).sort().map(name => {
    assert(/^(image-(api|web)\.(json|stderr\.txt)|(partial-)?summary\.json)$/.test(name), 'Unexpected audit artifact');
    return hash(path.join(root, name));
  });
  return { ...summary, reduced_match_comparison: comparison, raw_artifacts };
}

const [mode, ...ids] = process.argv.slice(2);
assert(['browser', 'audit'].includes(mode), 'Use browser <run IDs> or audit');
if (mode === 'audit') assert.equal(ids.length, 0);
else assert(ids.length > 0 && new Set(ids).size === ids.length, 'Supply unique run IDs');
const result = mode === 'audit' ? audit() : {
  schema: 1,
  notice: 'Synthetic local development evidence. All supplied attempts retained; see per-run disposition. Private fixture keys, credentials and log bodies are not included. No release acceptance or risk waiver.',
  runs: ids.map(browserRun),
};
process.stdout.write(JSON.stringify(result, null, 2) + '\n');
