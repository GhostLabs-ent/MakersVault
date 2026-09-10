// Reduce private audit/vendor artifacts without suppressing scanner matches.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const input = process.argv[2];
const vendorFile = process.argv[3];
assert.equal(process.argv.length, 4, 'Supply private audit directory and vendor JSON');
assert(/^\/tmp\/makersvault-g13c-security-closeout-[a-z0-9-]+$/.test(input));
assert(/^\/tmp\/makersvault-security-vendor-[a-z0-9-]+\.json$/.test(vendorFile));
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const unique = values => [...new Set(values)].sort();
const summary = read(path.join(input, 'summary.json'));
assert.equal(summary.status, 'audit_completed_not_release_clearance');
assert.equal(summary.verification_sources_dirty, false);
const vendor = read(vendorFile);
const prior = read(path.join(__dirname, 'sidebar-menu-audit.json'));
const old = read(path.join(__dirname, 'remediation-image-matches.json'));
const images = {};
const families = {};
for (const name of ['api', 'web']) {
  const raw = read(path.join(input, `image-${name}.json`));
  images[name] = raw.matches.map(row => {
    const {artifact:a, vulnerability:v} = row;
    const family = a.upstreams?.[0]?.name || a.name;
    families[v.id] ||= new Set();
    families[v.id].add(family);
    return {advisory:v.id, severity:v.severity, source:v.dataSource,
      namespace:v.namespace, package:a.name, version:a.version, type:a.type,
      locations:unique(a.locations.map(loc=>loc.path)),
      match_types:unique(row.matchDetails.map(match=>match.type)),
      fix_state:v.fix?.state || '', fix_versions:unique(v.fix?.versions || [])};
  });
  assert.equal(images[name].length, summary.scans[`image-${name}`].matches);
}
const normalize = rows => rows.map(row=>JSON.stringify({...row,
  locations:unique(row.locations), match_types:unique(row.match_types),
  fix_versions:unique(row.fix_versions)})).sort();
const apiEqual = JSON.stringify(normalize(images.api)) === JSON.stringify(normalize(prior.reduced_match_comparison.api_current_records));
const webEqual = JSON.stringify(normalize(images.web)) === JSON.stringify(normalize(old.web.matches));
const ids = unique([...images.api, ...images.web].map(row=>row.advisory));
assert.deepEqual(ids, vendor.ids, 'Vendor seed must cover the complete fresh inventory');
assert.equal(ids.length, 97);
const excluded = new Set(['CVE-2026-4224','CVE-2026-7210','CVE-2026-3644','CVE-2026-4519','CVE-2026-4360','CVE-2025-13462','CVE-2025-13837']);
const absentPerl = new Set(['CVE-2026-42496','CVE-2026-42497','CVE-2026-9538','CVE-2026-57433',
  'CVE-2025-15649','CVE-2026-48959','CVE-2026-48961','CVE-2026-48962','CVE-2026-7010','CVE-2026-7017']);
const pythonNoCaller = new Set(['CVE-2026-15806','CVE-2025-15366','CVE-2025-15367','CVE-2026-6019','CVE-2026-19672','CVE-2026-3479']);
const records = ids.map(id => {
  const c = vendor.cna[id];
  const d = vendor.debian[id];
  let disposition = 'unresolved_platform_residual';
  let section = 'S04';
  if (excluded.has(id)) {disposition='vendor_branch_exclusion'; section='S03';}
  else if (id === 'CVE-2026-15310') {disposition='application_read_paths_mitigated_interpreter_unpatched'; section='S03';}
  else if (id === 'CVE-2026-17084') {disposition='reachable_normalization_requires_decision'; section='S02';}
  else if (['CVE-2025-12781','CVE-2026-3446'].includes(id)) {disposition='bounded_application_semantics_reviewed'; section='S03';}
  else if (pythonNoCaller.has(id)) {disposition='no_matching_application_call_path_identified'; section='S03';}
  else if (absentPerl.has(id)) disposition='required_perl_module_not_loadable_in_inspected_runtime';
  else if (id === 'CVE-2026-8376') disposition='32_bit_precondition_absent_in_inspected_64_bit_runtime';
  else if (id === 'CVE-2025-60876') disposition='no_application_input_to_busybox_wget_identified';
  return {id, source_families:unique(families[id]), review_section:section, disposition,
    risk_acceptance:'not_granted',
    cna:{url:c.url, ...(c.error ? {error:c.error} : {sha256:c.sha256, updated:c.metadata?.dateUpdated,
      ...(excluded.has(id) ? {affected:c.affected} : {})})},
    ...(d ? {debian:{url:d.url, ...(d.error ? {error:d.error} : {sha256:d.sha256,
      trixie_rows:d.text.split('\n').map(line=>line.trim()).filter(line=>/\btrixie\b.*\b(?:vulnerable|fixed|undetermined)$/.test(line))})}} : {})};
});
const rawArtifacts = fs.readdirSync(input).filter(name=>/\.(json|txt)$/.test(name)).sort().map(name=>({file:name,sha256:digest(path.join(input,name)),bytes:fs.statSync(path.join(input,name)).size}));
const pythonDevelopment = read(path.join(input, 'python-development.json')).dependencies.filter(row=>row.vulns.length).map(row=>({name:row.name,version:row.version,vulnerabilities:row.vulns.map(({description,...fields})=>fields)}));
const npmWeb = read(path.join(input, 'npm-web.json')).vulnerabilities;
const report = {...summary, raw_artifacts:rawArtifacts, vendor_snapshot:{sha256:digest(vendorFile),captured_at:vendor.captured_at,
  matched_unique_ids:ids.length,cna_success:records.filter(row=>!row.cna.error).length,
  cna_errors:records.filter(row=>row.cna.error).map(row=>row.id),
  debian_success:records.filter(row=>row.debian&&!row.debian.error).length},
  reduced_match_comparison:{scope:'advisory, severity, source, namespace, package, version, type, locations, match_types, fix_state, fix_versions; not every raw scanner field',
    api_prior:'sidebar-menu-audit.json#reduced_match_comparison.api_current_records',api_equal:apiEqual,
    web_prior:'remediation-image-matches.json#web.matches',web_equal:webEqual},
  language_findings:{npm_web:npmWeb,python_development:pythonDevelopment},
  review_scope:'SECURITY_CLOSEOUT.md; review completed, no owner risk acceptance or release clearance'};
const outputs = {'security-closeout-audit.json':report,
  'security-closeout-inventory.json':{schema:1,source_revision:summary.source_revision,images:summary.images,
    api:{matches:images.api},web:{matches:images.web},advisory_review:records}};
for (const name of Object.keys(outputs)) assert(!fs.existsSync(path.join(__dirname,name)), `Refusing to overwrite ${name}`);
for (const [name,value] of Object.entries(outputs)) fs.writeFileSync(path.join(__dirname,name),JSON.stringify(value,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({written:Object.keys(outputs),api_matches:images.api.length,web_matches:images.web.length,
  unique_ids:ids.length,api_equal:apiEqual,web_equal:webEqual,
  cna_errors:report.vendor_snapshot.cna_errors,
  families:unique(Object.values(families).flatMap(value=>[...value]))}));
