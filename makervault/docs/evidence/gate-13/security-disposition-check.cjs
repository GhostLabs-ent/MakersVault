// Build/check the proposed owner package; never accepts, suppresses or edits old evidence.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const local = name => read(path.join(__dirname, name));
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const unique = values => [...new Set(values)].sort();
const app = path.resolve(__dirname, '../../..');
const output = path.join(__dirname, 'security-disposition-proposal.json');
assert(process.argv.length <= 3 && [undefined, '--write'].includes(process.argv[2]));
const checked = JSON.parse(execFileSync(process.execPath,
  [path.join(__dirname, 'security-containment-analysis.cjs')], {encoding:'utf8'}));
assert.equal(checked.status, 'passed');
const prior = local('security-residual-decisions.json');
const verified = local('security-containment-verification.json');
const inventory = local('security-closeout-inventory.json');
const directory = path.join(os.homedir(), '.local/state/makersvault/verification/containment-disposition-components');
const run = read(path.join(directory, 'result.json'));
assert.equal(run.exit_code, 0);
assert.equal(run.source_revision, '290df5518b7863802c06f96080336f9d7ed6e079');
assert.equal(run.end_source_revision, run.source_revision);
assert.equal(run.verification_source_status, '');
assert.equal(run.end_verification_source_status, '');
assert(run.command.includes(verified.lifecycle.images.api));
assert(run.command.includes('--network') && run.command.includes('none'));
const probeHashes = {};
for (const file of ['started.json', 'result.json', 'stdout.log', 'stderr.log']) {
  const full = path.join(directory, file);
  assert.equal(fs.statSync(full).mode & 0o077, 0);
  probeHashes[file] = hash(full);
}
for (const row of run.artifacts) assert.equal(probeHashes[row.file], row.sha256);
const probe = read(path.join(directory, 'stdout.log'));
assert.equal(probe.zipdetails.which, null);
assert.deepEqual(probe.zipdetails.present_paths, []);
assert.equal(probe.zipdetails.package_search_exit, 1);
assert.equal(probe.zipdetails.package_search_stdout, '');
assert.equal(probe.sqlite.python_runtime, verified.components.sqlite);
assert.deepEqual(probe.sqlite.symbols, {
  sqlite3changeset_apply:true, sqlite3changeset_apply_v2:true, sqlite3changeset_apply_v3:false,
});

const conditions = {
  C1: 'Exact named linux/amd64 development images only. No transfer to a rebuild, another architecture, desktop or a public candidate.',
  C2: 'Canonical Compose and entrypoint; nonzero API PUID/PGID; no privileged/capability overrides. Actual API/Nginx processes retain five empty capability sets and no-new-privileges.',
  C3: 'Production-style HTTPS, authentication/authorization, outbound-hostname checks and existing file/preview guards remain enabled; do not expose development servers to untrusted networks.',
  C4: 'Raw snapshots come only from trusted operator-controlled installations with protected provenance and private staging. GNU tar, chown and SQLite processing are not a hostile-input sandbox; checksums do not authenticate origin.',
  C5: 'Keep writable vault access, native memory-corruption/data-loss and denial-of-service residuals explicit. No read-only-root or memory/CPU/PID cap is claimed; daemon containment does not cover separate privileged operator recovery.',
  C6: 'Expiry is the earlier of acceptance plus 30 days or candidate freeze/13D. Reopen immediately for a relevant vendor fix, new caller/input path, changed image/platform, changed advisory, missing evidence or weaker controls. No automatic renewal.',
  C7: 'Approval is local-qualification risk acceptance only, not publication, deployment, a support-policy change, S04/G13-04 closure or Gate 13C/13D acceptance. Hold entries remain unwaived.',
};
const modules = {
  'CVE-2025-15649':'IO::Uncompress::Unzip',
  'CVE-2026-42496':'Archive::Tar', 'CVE-2026-42497':'Archive::Tar',
  'CVE-2026-9538':'Archive::Tar', 'CVE-2026-57433':'Storable',
  'CVE-2026-48959':'IO::Uncompress::Unzip', 'CVE-2026-48962':'File::GlobMapper',
  'CVE-2026-7010':'HTTP::Tiny', 'CVE-2026-7017':'HTTP::Tiny',
};
const holds = {
  'CVE-2026-5450': ['Allocating scanf conversion in installed glibc; no complete native reachability exclusion. Containment does not repair heap corruption.', 'Obtain an applicable supported glibc fix and requalify, or document the actual native call boundary for this conversion; otherwise request a separately explicit informed exception.'],
  'CVE-2026-19499': ['Installed glibc still affected in Debian; description insufficient, current CNA retrieval 404 and upstream detail unavailable through this review.', 'Obtain authoritative preconditions or a supported installed fix; do not infer safety from missing text.'],
  'CVE-2026-19542': ['Debian identifies a tdelete stack-access issue and still marks installed glibc affected; current CNA retrieval 404 and upstream detail unavailable.', 'Establish native tdelete call/input applicability or install an applicable supported fix; unavailable detail is not an exclusion.'],
  'CVE-2026-77117': ['Installed glibc still affected in Debian; description insufficient, current CNA retrieval 404 and upstream detail unavailable through this review.', 'Obtain authoritative preconditions or a supported installed fix; do not infer safety from missing text.'],
  'CVE-2026-80489': ['Installed glibc still affected in Debian; description insufficient, current CNA retrieval 404 and upstream detail unavailable through this review.', 'Obtain authoritative preconditions or a supported installed fix; do not infer safety from missing text.'],
  'CVE-2026-11822': ['SQLite FTS5 is enabled; malformed database plus FTS5 MATCH is the described path. No application MATCH caller identified, but raw recovery opens supplied database bytes.', 'Resolve raw-schema/query reachability with authoritative code evidence or a supported SQLite fix; trusted snapshots alone do not prove parser safety.'],
  'CVE-2026-11824': ['SQLite FTS5 is enabled; malformed continuation-page data during MATCH is the described path. No application MATCH caller identified; raw database boundary remains.', 'Resolve raw-schema/query reachability with authoritative code evidence or a supported SQLite fix; read-only SQLite is not a sandbox.'],
  'CVE-2026-39113': ['sqlar_uncompress is absent from the default connection, but upstream introduction details conflict with Debian affected-version mapping; no whole-extension exclusion established.', 'Reconcile the shipped Debian source/build and sqlar component with the upstream defect, or install an applicable supported fix.'],
  'CVE-2026-50812': ['Described changeset_apply_v3 symbol is absent in the inspected library, while older apply/apply_v2 and SESSION are present. Debian still marks the installed source affected.', 'Reconcile the vendor mapping and actual affected source implementation; absent v3 symbol alone does not clear all shared SESSION code.'],
  'CVE-2026-85091': ['Upstream description names a nonblocking gzwrite/gzprintf path and a newer range than inspected zlib 1.3.1; Debian still marks its installed source affected.', 'Resolve distribution source/backport and native gzwrite/gzprintf call applicability; do not treat generic Python decompression or a headline version comparison as proof.'],
};
const familyRationale = {
  acl: 'Ownership/ACL tooling has privileged path/metadata preconditions. Startup/recovery use chown; require protected storage roots and staging, not a blanket unused-utility exclusion.',
  apt: 'No application-controlled package-manager invocation identified. Package tooling remains installed; operator commands are separate from the capability-free daemon.',
  attr: 'Extended-attribute/metadata tools remain installed; protected operator roots and staging constrain path manipulation, without establishing a native patch.',
  busybox: 'The matched web advisory concerns BusyBox wget, not an identified Nginx parser defect. No application URL-to-wget path identified; BusyBox remains installed.',
  bzip2: 'Compression utility remains installed in the trusted raw-backup/recovery boundary. Archive validation is not a native-parser or resource sandbox.',
  coreutils: 'Startup/recovery use ownership tools. Restrict storage roots and staging to the operator; specific option/race preconditions do not justify excluding the entire family.',
  diffutils: 'No application-controlled diff3 invocation identified. Installed utility and future/operator use remain residual exposure.',
  glibc: 'Core native runtime remains present, including resolver/locale interfaces. Review identifies bounded/local/disputed conditions, not an exhaustive native call graph; accept only temporarily under C1-C7.',
  gzip: 'GNU tar backup/recovery invokes compression paths. Only trusted snapshots and private staging are in scope; corruption/resource risk remains.',
  ncurses: 'No application-controlled terminal-tool invocation identified. Installed terminal libraries/utilities are not proven unreachable from every dependency.',
  pam: 'Web identity is not a PAM service. OS startup/account tools still exist; local/operator preconditions and daemon capability removal constrain, not remove, exposure.',
  pcre2: 'No application-controlled native DFA-regex caller identified. Installed PCRE2 is not proven absent or patched, and dependency/operator callers remain a boundary.',
  perl: 'Perl core, File::Temp and Socket remain present. No application-controlled Perl invocation identified; do not claim the whole interpreter absent or patched.',
  shadow: 'Startup uses OS account tools; web authentication is separate. Local/operator preconditions and protected account/volume configuration are required.',
  sqlite3: 'SQLite is an active runtime dependency. No relevant extension/query caller identified in the prior review, but raw recovery processes supplied database bytes; trusted provenance is required and not parser safety.',
  systemd: 'The API is not a systemd service manager; installed system libraries and local/operator tooling remain. This is no family-wide absence claim.',
  tar: 'Raw recovery invokes GNU tar extraction after Python checks. Require trusted snapshots/private staging; parser differentials, path and resource risks remain.',
  'util-linux': 'Startup actively uses setpriv and now empties daemon capabilities. No untrusted mount/nsenter/login command path identified; operator recovery retains its separate six-capability policy.',
  zlib: 'CVE-2026-27171 concerns negative combine arguments; no matching application caller identified. zlib remains used by native decompression paths and is not patched by containment.',
};
const criticalRationale = {
  'CVE-2026-12087':'CRITICAL scanner label retained. Socket is loadable; its short source argument heap-read defect requires a matching Perl helper call. No application-controlled Perl invocation identified; installed code and dependency/operator uncertainty remain.',
  'CVE-2026-13221':'CRITICAL scanner label retained. Perl core is present; the described large fixed-branch regex trie can make incorrect match decisions. No application-controlled Perl invocation identified; installed code and dependency/operator uncertainty remain.',
};
const records = prior.records.map(old => {
  const bucket = old.proposed_action[0];
  let rationale, exitCriteria;
  if (bucket === 'E') {
    if (modules[old.id]) {
      assert.equal(verified.components.perl.modules_loadable[modules[old.id]], false);
      rationale = `Required ${modules[old.id]} module is not loadable in the exact inspected API runtime; no other image or installed-package exclusion is implied.`;
    } else if (old.id === 'CVE-2026-8376') {
      assert.equal(verified.components.perl.config[1], '8');
      rationale = 'The described defect requires a 32-bit Perl build; inspected Perl has 8-byte pointers on linux/amd64.';
    } else {
      assert.equal(old.id, 'CVE-2026-48961');
      rationale = 'This is the zipdetails CLI defect, not a library-call defect. New inspection finds no installed package manifest or named executable-path entry for zipdetails. IO::Compress module absence alone was insufficient evidence.';
    }
    exitCriteria = 'Recheck the exact precondition for any changed image/module/tool/path/platform; retain raw scanner matches and dated source record.';
  } else if (bucket === 'H') {
    assert(holds[old.id]);
    [rationale, exitCriteria] = holds[old.id];
  } else {
    assert.equal(bucket, 'R');
    assert(old.source_families.every(family => familyRationale[family]), old.id);
    rationale = criticalRationale[old.id] || old.source_families.map(family => familyRationale[family]).join(' ');
    exitCriteria = 'Refresh supported vendor fixes and exact image/call/input evidence before expiry or candidate freeze; requalify a fix or obtain a new explicit disposition, never auto-renew.';
  }
  return {id:old.id, bucket, recommendation:{E:'approve_exact_image_precondition_exclusion',
    R:'approve_time_limited_local_qualification_exception',H:'hold_not_recommended_for_acceptance'}[bucket],
    source_families:old.source_families, matches:old.matches, rationale, exit_criteria:exitCriteria,
    conditions:Object.keys(conditions), source:old.source,
    vendor_review:bucket !== 'R' || criticalRationale[old.id] ? 'Targeted Debian page reread 2026-09-11 UTC; see report limits' : 'Inherited dated 2026-09-10 review; not a fresh vendor reread',
    owner_decision:'pending', accepted_by:null, accepted_at:null, review_due:null};
});
assert.equal(records.length, 80);
assert.equal(unique(records.map(row => row.id)).length, 80);
const counts = Object.fromEntries(['E','R','H'].map(bucket => [bucket, {
  cves:records.filter(row=>row.bucket===bucket).length,
  package_matches:records.filter(row=>row.bucket===bucket).reduce((sum,row)=>sum+row.matches.length,0),
}]));
assert.deepEqual(Object.values(counts).map(row=>row.cves), [11,59,10]);
assert.equal(Object.values(counts).reduce((sum,row)=>sum+row.package_matches,0),167);
assert.deepEqual(unique(records.filter(row=>row.bucket==='H').map(row=>row.id)),Object.keys(holds).sort());
const nativeIds = new Set(records.map(row=>row.id));
const otherIds = unique(['api','web'].flatMap(image=>inventory[image].matches)
  .filter(row=>!nativeIds.has(row.advisory)).map(row=>row.advisory));
assert.equal(otherIds.length,17);
for (const record of records) {
  const matches = ['api','web'].flatMap(image=>inventory[image].matches.filter(row=>row.advisory===record.id)
    .map(row=>({image,package:row.package,version:row.version,severity:row.severity})));
  assert.deepEqual(record.matches,matches);
}
const files = ['security-residual-decisions.json','security-containment-verification.json',
  'security-closeout-inventory.json','security-disposition-components.py'];
const report = {schema:1,status:'proposal_only_no_acceptances',prepared_date_utc:'2026-09-11',
  application_revision:verified.revision,entry_revision:run.source_revision,
  images:Object.fromEntries(['api','web'].map(image=>[image,{id:verified.lifecycle.images[image],platform:'linux/amd64'}])),
  scope:'S04 only: 80 native CVEs / 167 matches. All 184 image matches remain; 17 interpreter CVEs / 17 matches stay in S02/S03.',
  input_sha256:Object.fromEntries(files.map(file=>[file,hash(path.join(__dirname,file))])),
  probe:{directory,run,raw_sha256:probeHashes,observations:probe},
  owner_policy:{proposed_approver:'VincentCinque (repository maintainer); confirm on approval',
    accepted_by:null,accepted_at:null,review_due:null,risk_acceptance:'not_granted',
    expiry:'Earlier of acceptance plus 30 days or candidate freeze/13D; reopen immediately under C6',
    record_approval:'Append a new named, dated decision record referencing this proposal hash and exact IDs; do not rewrite historical proposed evidence.',
    release_authority:'none',conditions},
  counts,unchanged_image_matches:{api:181,web:3},records};
if (process.argv[2] === '--write') fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
else assert.deepEqual(read(output),report,'Proposal drift or invented owner acceptance');
let links = 0;
for (const name of ['SECURITY_DISPOSITION_PROPOSAL.md']) {
  const text = fs.readFileSync(path.join(__dirname,name),'utf8');
  for (const match of text.matchAll(/\]\(((?:[^\s()]|\([^)]*\))+)\)/g)) {
    if (/^(https?:|#)/.test(match[1])) continue;
    assert(fs.existsSync(path.resolve(__dirname,decodeURIComponent(match[1].split('#')[0]))),match[1]);
    links++;
  }
}
assert.equal(execFileSync('git',['diff','--name-only',verified.revision,'--','api','web','scripts',
  'benchmarks','slicer-bridge','docker-compose.yml','docker-compose.deploy.yml','docker-deploy.yml','../Makefile'],
  {cwd:app,encoding:'utf8'}).trim(),'');
console.log(JSON.stringify({status:'passed',counts,accepted:0,retained_scanner_matches:184,
  containment_hash_checks:checked.checked_hashes,probe_hash_checks:4,local_links:links}));
