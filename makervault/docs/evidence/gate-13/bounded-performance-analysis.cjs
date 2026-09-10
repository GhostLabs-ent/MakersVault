// Read-only collection of this bounded pass; private logs are hashed, never published.
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

const dispositions = {
  a: 'Unprofiled 600-Artifact/1040-folder stress on c42614e; unchanged timing budgets.',
  b: 'Unprofiled 600-Artifact/104-folder organization and separate mixed preview on c42614e.',
};
function browserRun(id) {
  assert(Object.hasOwn(dispositions, id), 'Unknown run ID');
  const root = `/tmp/makersvault-g13c-bounded-0910${id}`;
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

const ids = process.argv.slice(2);
assert(ids.length > 0 && new Set(ids).size === ids.length, 'Supply unique run IDs');
process.stdout.write(JSON.stringify({schema: 1, runs: ids.map(browserRun)}, null, 2) + '\n');
