// Read-only reducer for the named sidebar-menu slice's synthetic reports. No fixture keys or log bodies.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

function regular(file) {
  const stat = fs.lstatSync(file);
  assert(stat.isFile() && stat.size <= 128 * 1024 * 1024, `Not a bounded regular file: ${file}`);
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
  control: 'Old 76b526d images / 82cb2cc harness: expected regression refusal at nine eager closed menus; not performance evidence.',
  a: '82cb2cc application/harness development matrix: new dropdown lookup failed in each engine. Ordering never ran: concurrent full verification rebuilt the local image tags and the earlier API image reference disappeared. No result from A qualifies final images.',
  b: 'Final 82cb2cc images / a3e3504 harness: Chromium and Firefox pass all 17 checks; WebKit fails in the combined synthetic drop/download check. Seven ordering cases pass.',
  debug: 'Final 82cb2cc images / 74232d6 harness: WebKit failure narrowed to synthetic file-drop upload, before ZIP download; no application change.',
  h: 'Final 82cb2cc images / e841b79 harness: Chromium/Firefox pass 17 checks and ordering passes. WebKit retains NotFoundError preflight and fails constructing DragEvent with the plain-object FileList fixture; not a WebKit pass.',
  i: 'Final 82cb2cc images / 7551745 harness: WebKit native-branded FileList attempt fails the immediate drop-highlight assertion. Retained failure, not qualification.',
  j: 'Final 82cb2cc images / 7b0bb6e harness: WebKit repeat uses an explicit FileList-only DOM event and waits for the drop highlight. Native synthetic-entry/OS drag remain unqualified.',
  c: '82cb2cc images: unprofiled baseline organization matrix plus separate preview and mounted-import probes.',
  d: '82cb2cc images: unprofiled 600-Artifact/1040-folder stress, unchanged timing budgets.',
  e: '82cb2cc images: second fresh unprofiled 600-Artifact/104-folder Chromium baseline.',
  f: '82cb2cc images: third fresh unprofiled 600-Artifact/104-folder Chromium baseline.',
  g: '82cb2cc images: second fresh unprofiled 600-Artifact/1040-folder Chromium stress.',
};

function browserRun(id) {
  assert(Object.hasOwn(dispositions, id), 'Unknown run ID');
  const root = ['control', 'debug'].includes(id) ? `/tmp/makersvault-g13c-sidebar-0910-${id}` : `/tmp/makersvault-g13c-sidebar-0910${id}`;
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
  assert(['passed', 'failed', 'interrupted'].includes(summary.status), 'Run is not complete');
  return { id, disposition: dispositions[id], output_root: root, summary, reports, raw_artifacts: artifacts };
}

function audit(id) {
  const root = '/tmp/makersvault-g13c-sidebar-audit-0910' + (id === 'final' ? '-final' : '');
  directory(root);
  if (id === 'initial') {
    assert(!fs.existsSync(path.join(root, 'summary.json')), 'Initial audit unexpectedly completed');
    return { ...json(path.join(root, 'partial-summary.json')), status: 'incomplete_not_release_clearance',
      failure: 'API scan completed on the development image export; web image reference disappeared after concurrent lifecycle rebuild. Not the final-image audit.',
      raw_artifacts: fs.readdirSync(root).sort().map(name => {
        assert(/^(image-api\.(json|stderr\.txt)|partial-summary\.json)$/.test(name), 'Unexpected initial audit artifact');
        return hash(path.join(root, name));
      }) };
  }
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
    if (!comparison[`${target}_equal`]) {
      comparison[`${target}_current_records`] = reduced;
      const identity = row => JSON.stringify([row.advisory, row.namespace, row.package, row.version, row.type]);
      const before = new Map(prior[target].matches.map(row => [identity(row), row]));
      const after = new Map(reduced.map(row => [identity(row), row]));
      assert.equal(before.size, prior[target].matches.length, 'Ambiguous prior match identity');
      assert.equal(after.size, reduced.length, 'Ambiguous current match identity');
      comparison[`${target}_added_identities`] = [...after.keys()].filter(key => !before.has(key));
      comparison[`${target}_removed_identities`] = [...before.keys()].filter(key => !after.has(key));
      comparison[`${target}_changed_fields`] = reduced.flatMap(row => {
        const old = before.get(identity(row));
        if (!old) return [];
        const fields = Object.keys(row).filter(key => JSON.stringify(stable(old[key])) !== JSON.stringify(stable(row[key])));
        return fields.length ? [{ advisory: row.advisory, package: row.package, version: row.version,
          fields: Object.fromEntries(fields.map(key => [key, { before: old[key], after: row[key] }])) }] : [];
      });
    }
  }
  const raw_artifacts = fs.readdirSync(root).sort().map(name => {
    assert(/^(image-(api|web)\.(json|stderr\.txt)|(partial-)?summary\.json)$/.test(name), 'Unexpected audit artifact');
    return hash(path.join(root, name));
  });
  return { ...summary, reduced_match_comparison: comparison, raw_artifacts };
}

const [mode, ...ids] = process.argv.slice(2);
assert(['browser', 'audit'].includes(mode), 'Use browser <run IDs> or audit initial|final');
if (mode === 'audit') assert(ids.length === 1 && ['initial', 'final'].includes(ids[0]));
else assert(ids.length > 0 && new Set(ids).size === ids.length, 'Supply unique run IDs');
const result = mode === 'audit' ? audit(ids[0]) : {
  schema: 1,
  notice: 'Synthetic local development evidence. All supplied attempts retained; see per-run disposition. Private fixture keys, credentials and log bodies are not included. No release acceptance or risk waiver.',
  runs: ids.map(browserRun),
};
process.stdout.write(JSON.stringify(result, null, 2) + '\n');
