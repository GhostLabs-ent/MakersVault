// Read-only vendor snapshot for the advisory IDs in the captured image inventory.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
async function get(url, maximum = 2 * 1024 * 1024, asJson = true) {
  const response = await fetch(url, {signal: AbortSignal.timeout(45000), redirect: 'error'});
  assert(response.ok, `${url}: HTTP ${response.status}`);
  let size = 0;
  const parts = [];
  for await (const part of response.body) {
    size += part.length;
    assert(size <= maximum, 'Vendor response exceeds bound');
    parts.push(part);
  }
  const data = Buffer.concat(parts);
  return {url, bytes: size, sha256: crypto.createHash('sha256').update(data).digest('hex'), value: asJson ? JSON.parse(data) : data.toString('utf8')};
}
async function main() {
  assert.equal(process.argv.length, 3, 'Supply a new /tmp/makersvault-security-vendor-*.json output');
  const output = process.argv[2];
  assert(/^\/tmp\/makersvault-security-vendor-[a-z0-9-]+\.json$/.test(output), 'Output must be a named temporary artifact');
  assert(!fs.existsSync(output), 'Never overwrite an existing vendor snapshot');
  const prior = JSON.parse(fs.readFileSync(path.join(__dirname, 'remediation-image-matches.json')));
  const ids = [...new Set([...prior.api.matches, ...prior.web.matches].map(row => row.advisory))].sort();
  assert(ids.every(id => /^CVE-\d{4}-\d+$/.test(id)));
  // Do not download the entire Debian database: retain bounded per-advisory pages.
  const debianIds = new Set(prior.api.matches.filter(row => row.package !== 'python').map(row => row.advisory));
  const debian = {};
  const cna = {};
  let index = 0;
  async function worker() {
    while (index < ids.length) {
      const id = ids[index++];
      const [, year, number] = id.split('-');
      const group = Math.floor(Number(number)/1000) + 'xxx';
      const url = `https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/${year}/${group}/${id}.json`;
      try {
        const result = await get(url, 2*1024*1024);
        const record = result.value.containers?.cna;
        assert(record && result.value.cveMetadata.cveId === id, 'Invalid CVE record');
        cna[id] = {url, sha256: result.sha256, metadata: result.value.cveMetadata,
          provider: record.providerMetadata, title: record.title,
          description: record.descriptions?.find(row => row.lang === 'en')?.value,
          affected: record.affected, references: record.references, tags: record.tags};
      } catch (error) { cna[id] = {url, error: String(error.message)}; }
      if (debianIds.has(id)) {
        const source = `https://security-tracker.debian.org/tracker/${id}`;
        try {
          const result = await get(source, 2*1024*1024, false);
          const text = result.value.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
            .replace(/<\/(tr|h1|h2|p|pre)>/gi, '\n').replace(/<\/?[^>]+>/g, ' ')
            .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&')
            .replace(/[ \t]+/g, ' ').trim();
          debian[id] = {url:source, sha256:result.sha256, text};
        } catch (error) { debian[id] = {url:source, error:String(error.message)}; }
      }
    }
  }
  await Promise.all(Array.from({length:4}, worker));
  const report = {schema:1, captured_at:new Date().toISOString(),
    seed_inventory: 'remediation-image-matches.json; compare IDs to fresh scan before relying on coverage',
    ids, debian: Object.fromEntries(Object.entries(debian).sort()),
    cna: Object.fromEntries(Object.entries(cna).sort())};
  fs.writeFileSync(output, JSON.stringify(report, null, 2)+'\n', {flag:'wx', mode:0o600});
  console.log(JSON.stringify({output, ids:ids.length, cna_errors: Object.entries(cna).filter(([,v])=>v.error),
    debian_errors: Object.entries(debian).filter(([,v])=>v.error)}));
}
main().catch(error => {console.error(error.message); process.exitCode = 1;});
