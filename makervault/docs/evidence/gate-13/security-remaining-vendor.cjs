// Capture only previously readable primary endpoints; never retry failed endpoints.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
assert.equal(process.argv.length, 2);
const root = path.join(os.homedir(), '.local/state/makersvault/verification');
const output = path.join(root, 'containment-remaining-vendor');
assert(!fs.lstatSync(root).isSymbolicLink()); assert.equal(fs.statSync(root).mode & 0o077, 0);
fs.mkdirSync(output, {mode: 0o700}); // New private capture only, never overwrite.
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
const git = args => execFileSync('git', args, {encoding: 'utf8'}).trim();
const ids = ['CVE-2026-19499', 'CVE-2026-19542', 'CVE-2026-50812', 'CVE-2026-77117', 'CVE-2026-80489'];
const sources = [
  ...ids.map(id => ({key: 'debian-' + id, id, url: 'https://security-tracker.debian.org/tracker/' + id})),
  ...ids.filter(id => !id.endsWith('50812')).map(id => ({key: 'redhat-' + id, id,
    url: 'https://access.redhat.com/security/cve/' + id.toLowerCase()})),
  ...['CVE-2026-80489', 'CVE-2026-50812'].map(id => ({key: 'ubuntu-' + id, id,
    url: 'https://ubuntu.com/security/' + id})),
  {key: 'sqlite-fix', id: 'b869ed6', url: 'https://github.com/sqlite/sqlite/commit/b869ed6b067d623cb1383549f2a18aa35508385d'},
];
const report = {schema: 1, scope: 'Five unaccepted holds only; no installed update or owner disposition',
  started_at: new Date().toISOString(), entry_revision: git(['rev-parse', 'HEAD']),
  script_sha256: sha(fs.readFileSync(__filename)), captures: {}};
const clean = text => text.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
  .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '').replace(/<\/(tr|h1|h2|p|pre)>/gi, '\n')
  .replace(/<\/?[^>]+>/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&').replace(/[ \t]+/g, ' ').trim();
let index = 0;
async function worker() {
  while (index < sources.length) {
    const source = sources[index++];
    const row = report.captures[source.key] = {...source, started_at: new Date().toISOString()};
    try {
      const response = await fetch(source.url, {redirect: 'error', signal: AbortSignal.timeout(20000)});
      row.http_status = response.status;
      assert(response.ok, 'HTTP ' + response.status);
      const parts = []; let size = 0;
      for await (const part of response.body) {
        size += part.length; assert(size <= 2 * 1024 * 1024, 'Page exceeds limit'); parts.push(part);
      }
      const bytes = Buffer.concat(parts);
      row.file = source.key + '.html'; row.sha256 = sha(bytes); row.bytes = bytes.length;
      fs.writeFileSync(path.join(output, row.file), bytes, {flag: 'wx', mode: 0o600});
      const text = clean(bytes.toString('utf8'));
      assert(text.includes(source.id), 'Missing expected page identity');
      if (source.key.startsWith('debian-')) {
        assert(text.includes('Vulnerable and fixed packages'));
        row.trixie_rows = text.split('\n').map(line => line.trim()).filter(line => /\btrixie\b.*\b(vulnerable|fixed)\b/.test(line));
        assert(row.trixie_rows.length);
      }
      row.status = 'captured';
    } catch (error) { row.status = 'unavailable_not_retried'; row.error = error.message; }
    row.finished_at = new Date().toISOString();
  }
}
async function main() {
  await Promise.all([worker(), worker()]);
  const files = git(['ls-files', '--', 'makervault/api']).split('\n').filter(file => /^makervault\/api\/[^/]+\.py$/.test(file));
  const pattern = /strfmon|tdelete|iconv|sqlite3changeset|enable_load_extension|load_extension|ctypes|cffi/i;
  report.direct_api_source_review = {pattern: pattern.source, flags: 'i', files: files.map(file => {
    const bytes = fs.readFileSync(file);
    return {file, sha256: sha(bytes), hits: bytes.toString('utf8').split('\n').flatMap((line, index) =>
      pattern.test(line) ? [{line: index + 1, text: line.trim()}] : [])};
  }), limitation: 'Direct API Python source tokens only; not a complete native, dynamic, dependency or operator-recovery call graph.'};
  report.end_revision = git(['rev-parse', 'HEAD']); report.finished_at = new Date().toISOString();
  fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(report, null, 2) + '\n', {flag: 'wx', mode: 0o600});
  console.log(JSON.stringify({output, captured: Object.values(report.captures).filter(row => row.status === 'captured').length,
    unavailable: Object.values(report.captures).filter(row => row.status !== 'captured'),
    trixie: Object.values(report.captures).filter(row => row.trixie_rows).map(row => ({id: row.id, rows: row.trixie_rows})),
    direct_source_files: files.length, direct_source_hits: report.direct_api_source_review.files.flatMap(row => row.hits).length}));
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
