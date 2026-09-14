// Read-only MP-1b-8 join: source, commands, retained failures, logs and UI artifacts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const repository = path.resolve(__dirname,'../../../..');
const app = path.join(repository,'makervault');
const root = path.join(os.homedir(),'.local/state/makersvault/verification');
const index = JSON.parse(fs.readFileSync(path.join(__dirname,'make-plate-consent-verification.json'),'utf8'));
const git = (...args)=>execFileSync('git',args,{cwd:repository,encoding:'utf8'}).trim();
const digest = data=>crypto.createHash('sha256').update(data).digest('hex');
assert.equal(index.schema_version,1);
assert.equal(index.gate,'MP-1b-8');
assert.equal(index.private_evidence_root,root);
assert.equal(index.entry_revision,'d0dc059bf4afbb7862bbc76184b19dddbcce9929');
const sources=['makervault/api','makervault/web','makervault/slicer-bridge',
  'makervault/docs/evidence/gate-13/security-hardening-run.cjs',
  'makervault/docs/evidence/gate-13/make-plate-consent-check.sh',
  'makervault/docs/evidence/gate-13/make-plate-consent-browser.cjs',
  'makervault/benchmarks/organization/package.json','makervault/benchmarks/organization/package-lock.json'];
assert.equal(git('status','--porcelain','--',...sources),'');
git('diff','--exit-code',index.implementation_revision,'--',...sources);
git('diff','--exit-code',index.entry_revision,'--','makervault/api','makervault/web',
  'makervault/slicer-bridge/cmd','makervault/slicer-bridge/go.mod',
  'makervault/slicer-bridge/internal/printerpreset','makervault/slicer-bridge/internal/presetworker/supervisor.go',
  'makervault/slicer-bridge/internal/presetfiles/hints_windows.go',
  'makervault/slicer-bridge/internal/presetfiles/hints_linux.go');
const expected=['consent-preflight','browser-deps','browser-preflight','browser-diagnostic',
  'consent-preflight-b','browser-preflight-b','consent-final','browser-final'];
assert.deepEqual(index.captures.map(c=>c.kind),expected);
let hashes=0;
for(const capture of index.captures){
  assert.equal(capture.directory,`containment-mp1b8-${capture.kind}-20260914`);
  const directory=path.join(root,capture.directory);
  const result=JSON.parse(fs.readFileSync(path.join(directory,'result.json'),'utf8'));
  const failing=['browser-preflight','browser-diagnostic'].includes(capture.kind);
  assert.equal(result.exit_code,failing?1:0);
  assert.equal(result.signal,null);
  assert.equal(result.command[0],'docker');
  const arg=key=>result.command[result.command.indexOf(key)+1];
  assert.equal(arg('--network'),capture.kind==='browser-deps'?'bridge':'none');
  assert.equal(arg('--pull'),'never');assert.equal(arg('--user'),'1000:1000');
  assert.equal(result.source_revision,result.end_source_revision);
  assert.equal(result.verification_source_status,result.end_verification_source_status);
  const final=capture.kind.endsWith('-final');
  assert.equal(result.source_revision,final?index.implementation_revision:index.entry_revision);
  if(final)assert.equal(result.verification_source_status,'');
  for(const artifact of capture.artifacts){
    assert.match(artifact.file,/^[\w.-]+\.(log|html|png|json)$/);
    const data=fs.readFileSync(path.join(directory,artifact.file));
    assert.equal(data.length,artifact.bytes);assert.equal(digest(data),artifact.sha256);hashes++;
  }
  for(const log of result.artifacts){
    assert.deepEqual(log,capture.artifacts.find(a=>a.file===log.file));
  }
  const stdout=fs.readFileSync(path.join(directory,'stdout.log'),'utf8');
  const stderr=fs.readFileSync(path.join(directory,'stderr.log'),'utf8');
  if(!failing&&capture.kind!=='browser-deps')assert.equal(stderr,'');
  if(capture.kind.startsWith('consent-')){
    assert(result.command.includes(index.go_image));
    const mounts=[['slicer-bridge','/src'],['docs/evidence/gate-13','/checks'],
      ['slicer-bridge/internal/printerpreset/testdata','/mount-fixture'],
      ['slicer-bridge/internal/printerpreset/testdata/child.json','/mount-fixture/child.json'],
      ['slicer-bridge/internal/presetfiles/testdata/location','/location-mount'],
      ['slicer-bridge/internal/presetfiles/testdata/location/system','/location-mount/system'],
      ['slicer-bridge/internal/presetfiles/testdata/accounts','/accounts-mount'],
      ['slicer-bridge/internal/presetfiles/testdata/accounts/user','/accounts-mount/user'],
      ['slicer-bridge/internal/presetfiles/testdata/accounts','/account-child-mount'],
      ['slicer-bridge/internal/presetfiles/testdata/accounts/user/fixture-account','/account-child-mount/user/fixture-account']];
    for(const [src,dst] of mounts)assert(result.command.includes(app+'/'+src+':'+dst+':ro'));
    assert.deepEqual(result.command.slice(-3),['sh','/checks/make-plate-consent-check.sh',final?index.implementation_revision:'preflight']);
    const lines=stdout.split('\n');
    const events=lines.filter(x=>x.startsWith('{')).map(x=>JSON.parse(x));
    assert.equal(events.filter(x=>x.Action==='fail'||x.Action==='skip').length,0);
    const passes=events.filter(x=>x.Action==='pass'&&x.Test), top=passes.filter(x=>!x.Test.includes('/'));
    assert.equal(top.filter(x=>x.Test.startsWith('Test')).length,capture.unit_tests_passed);
    assert.equal(top.length,capture.top_level_pass_events);assert.equal(passes.length,capture.inclusive_pass_events);
    assert.match(stdout,/uid=1000/);assert.match(stdout,/go version go1\.26\.6 linux\/amd64/);
    assert.equal(capture.artifacts.filter(a=>a.file.endsWith('.html')).length,6);
    if(final){
      for(const name of ['TestConsentNoReadBeforeApprovalAndExplicitChoices','TestConsentReviewDigestOneShotAndCopy',
        'TestConsentCancelInflightRejectsLateCompletion','TestConsentApprovedDataCanStillBeRevoked',
        'TestConsentSelectionLimitsAndChangedSource','TestConsentRealWorkerSyntheticLayout',
        'TestLocalPageRejectsForeignAndMalformedRequests','TestLocalPageEscapingAndDisplayBudget',
        'TestNativeLocationWireHasNoSuppliedAuthority','TestNativeLocationWorkerDeadlineAndSlot'])assert(top.some(x=>x.Test===name));
      assert.equal(lines.filter(x=>x.startsWith('crossbuild=')).length,6);
      for(const platform of ['linux','windows','darwin'])for(const arch of ['amd64','arm64']){
        assert(lines.includes(`crossbuild=${platform}/${arch} bridge-and-four-test-binaries=passed native-execution=not-tested`));
      }
      const fuzz=[];let progress;
      for(const line of lines){
        const p=/^fuzz: elapsed: (\d+)s, execs: (\d+) /.exec(line);
        if(p)progress={reported_elapsed_seconds:+p[1],executions:+p[2]};
        const done=/^bounded-fuzz=(\w+) passed requested-duration=5s native-device=not-tested$/.exec(line);
        if(done){assert(progress);fuzz.push({target:done[1],requested_seconds:5,...progress});progress=null;}
      }
      assert.equal(fuzz.length,10);assert.deepEqual(fuzz,capture.fuzz);
    }
  }else{
    assert(result.command.includes(index.browser_image));
    if(capture.kind==='browser-deps'){
      assert(result.command.includes(app+'/benchmarks/organization:/locked:ro'));
      assert.match(result.command.at(-1),/npm ci --ignore-scripts --no-audit --no-fund/);
      for(const file of ['package.json','package-lock.json']){
        assert.equal(digest(fs.readFileSync(path.join(directory,file))),digest(fs.readFileSync(path.join(app,'benchmarks/organization',file))));
      }
      continue;
    }
    assert.equal(result.command.at(-1),'/checks/make-plate-consent-browser.cjs');
    assert(result.command.includes(app+'/docs/evidence/gate-13:/checks:ro'));
    const fixtureKind=final?'consent-final':capture.kind==='browser-preflight-b'?'consent-preflight-b':'consent-preflight';
    const fixtureDirectory=path.join(root,`containment-mp1b8-${fixtureKind}-20260914`);
    assert(result.command.includes(fixtureDirectory+':/fixtures:ro'));
    assert(result.command.includes(path.join(root,'containment-mp1b8-browser-deps-20260914')+':/deps:ro'));
    if(failing){
      assert.match(stderr,/AssertionError/);
      if(capture.kind==='browser-diagnostic'){
        const failure=JSON.parse(stdout.trim());
        assert.equal(failure.failure,'horizontal-overflow');assert.equal(failure.engine,'chromium');
        assert.equal(failure.stage,'review');assert.equal(failure.layout.width,390);assert.equal(failure.layout.scroll,596);
      }
    }else{
      const report=JSON.parse(fs.readFileSync(path.join(directory,'browser-results.json'),'utf8'));
      assert.equal(report.scope,'synthetic-rendering-only-no-http-or-native-integration');
      assert.equal(report.results.length,36);
      for(const engine of ['chromium','firefox','webkit'])for(const width of [1024,390])for(const stage of ['consent','roots','accounts','presets','review','approved']){
        assert(report.results.some(x=>x.engine===engine&&x.viewport.width===width&&x.stage===stage&&x.status==='passed'));
      }
      for(const artifact of report.artifacts){
        assert.deepEqual(artifact,index.captures.find(c=>c.kind===fixtureKind).artifacts.find(a=>a.file===artifact.file));
      }
    }
  }
}
// Pin the installed locked test dependency, not just its mutable directory name.
const deps=path.join(root,'containment-mp1b8-browser-deps-20260914/node_modules/playwright-core');
const tree=crypto.createHash('sha256');
function visit(directory,prefix=''){
  for(const name of fs.readdirSync(directory).sort()){
    const file=path.join(directory,name),relative=prefix+name,stat=fs.lstatSync(file);
    assert(!stat.isSymbolicLink());
    if(stat.isDirectory())visit(file,relative+'/');
    else {assert(stat.isFile());tree.update(relative+'\0'+digest(fs.readFileSync(file))+'\n');}
  }
}
visit(deps);assert.equal(tree.digest('hex'),index.playwright_tree_sha256);
assert.equal(index.native_windows_tests_executed,0);assert.equal(index.native_macos_tests_executed,0);
console.log(JSON.stringify({gate:index.gate,status:'local_consent_foundation_verified_production_and_native_gates_open',artifact_hashes_checked:hashes,retained_failed_browser_runs:2}));
