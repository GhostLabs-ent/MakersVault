// Read-only MP-1b-9b-2 evidence join. Never rewrites historical results.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const {execFileSync}=require('node:child_process');
const repository=path.resolve(__dirname,'../../../..'),app=path.join(repository,'makervault');
const index=JSON.parse(fs.readFileSync(path.join(__dirname,'make-plate-linux-ui-verification.json'),'utf8'));
const root=path.join(os.homedir(),'.local/state/makersvault/verification');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const git=(...args)=>execFileSync('git',args,{cwd:repository,encoding:'utf8'}).trim();
assert.equal(index.schema_version,1);assert.equal(index.gate,'MP-1b-9b-2');assert.equal(index.private_evidence_root,root);
assert.equal(index.entry_revision,'810918e391148d6edfcabd8fe980c6a02de5fe27');
assert.equal(index.implementation_revision,'47943b075370b48a28fa8e862e450c87aacf1d03');
const sources=['makervault/api','makervault/web','makervault/slicer-bridge','makervault/docs/evidence/gate-13/security-hardening-run.cjs',
'makervault/docs/evidence/gate-13/make-plate-linux-ui-check.sh','makervault/docs/evidence/gate-13/make-plate-local-server-browser.cjs',
'makervault/benchmarks/organization/package.json','makervault/benchmarks/organization/package-lock.json'];
assert.equal(git('status','--porcelain','--',...sources),'');
git('diff','--exit-code',index.implementation_revision,'--',...sources);
git('diff','--exit-code',index.entry_revision,'--','makervault/api','makervault/web','makervault/slicer-bridge/cmd','makervault/slicer-bridge/go.mod',
'makervault/slicer-bridge/internal/printerpreset','makervault/slicer-bridge/internal/presetfiles','makervault/slicer-bridge/internal/presetworker',
'makervault/docs/evidence/gate-13/make-plate-local-server-browser.cjs','makervault/docs/evidence/gate-13/security-hardening-run.cjs');
git('diff','--exit-code',index.entry_revision,'--','makervault/slicer-bridge/internal/presetui/native_windows.go','makervault/slicer-bridge/internal/presetui/native_windows_test.go');
assert.deepEqual(index.captures.map(c=>c.kind),['go-preflight','go-final','browser-final']);
let hashes=0;
for(const c of index.captures){
 assert.equal(c.directory,'containment-mp1b9b2-'+c.kind+'-20260914');
 const directory=path.join(root,c.directory),r=JSON.parse(fs.readFileSync(path.join(directory,'result.json'),'utf8'));
 assert.equal(r.exit_code,0);assert.equal(r.signal,null);assert.equal(r.command[0],'docker');
 for(const [flag,value] of [['--network','none'],['--pull','never'],['--user','1000:1000']])assert.equal(r.command[r.command.indexOf(flag)+1],value);
 assert(!r.command.includes('-p')&&!r.command.includes('--publish'));
 const final=c.kind.endsWith('-final');
 assert.equal(r.source_revision,final?index.implementation_revision:index.entry_revision);assert.equal(r.end_source_revision,r.source_revision);
 assert.equal(r.verification_source_status,r.end_verification_source_status);if(final)assert.equal(r.verification_source_status,'');
 assert.deepEqual(fs.readdirSync(directory).sort(),c.artifacts.map(a=>a.file));
 for(const a of c.artifacts){
  assert(a.file==='consent-http-fixture'||/^[\w.-]+\.(log|html|png|json)$/.test(a.file));
  const bytes=fs.readFileSync(path.join(directory,a.file));assert.equal(bytes.length,a.bytes);assert.equal(hash(bytes),a.sha256);hashes++;
 }
 for(const a of r.artifacts)assert.deepEqual(a,c.artifacts.find(x=>x.file===a.file));
 const stdout=fs.readFileSync(path.join(directory,'stdout.log'),'utf8');assert.equal(fs.readFileSync(path.join(directory,'stderr.log'),'utf8'),'');
 assert(r.command.includes(app+'/docs/evidence/gate-13:/checks:ro'));assert(r.command.includes(directory+':/evidence'));
 if(c.kind.startsWith('go-')){
  assert(r.command.includes(index.go_image));
  for(const [src,dst] of [['slicer-bridge','/src'],
  ['slicer-bridge/internal/printerpreset/testdata','/mount-fixture'],['slicer-bridge/internal/printerpreset/testdata/child.json','/mount-fixture/child.json'],
  ['slicer-bridge/internal/presetfiles/testdata/location','/location-mount'],['slicer-bridge/internal/presetfiles/testdata/location/system','/location-mount/system'],
  ['slicer-bridge/internal/presetfiles/testdata/accounts','/accounts-mount'],['slicer-bridge/internal/presetfiles/testdata/accounts/user','/accounts-mount/user'],
  ['slicer-bridge/internal/presetfiles/testdata/accounts','/account-child-mount'],['slicer-bridge/internal/presetfiles/testdata/accounts/user/fixture-account','/account-child-mount/user/fixture-account']])assert(r.command.includes(app+'/'+src+':'+dst+':ro'));
  assert.deepEqual(r.command.slice(-3),['sh','/checks/make-plate-linux-ui-check.sh',final?index.implementation_revision:'preflight']);
  const lines=stdout.split('\n'),events=lines.filter(x=>x.startsWith('{')).map(x=>JSON.parse(x));
  assert.equal(events.filter(x=>x.Action==='fail'||x.Action==='skip').length,0);
  const passes=events.filter(x=>x.Action==='pass'&&x.Test),top=passes.filter(x=>!x.Test.includes('/'));
  assert.equal(top.filter(x=>x.Test.startsWith('Test')).length,200);assert.equal(top.length,213);assert.equal(passes.length,444);
  assert.equal(c.unit_tests_passed,200);assert.equal(c.top_level_pass_events,213);assert.equal(c.inclusive_pass_events,444);
  assert.equal(c.artifacts.filter(a=>a.file.endsWith('.html')).length,6);assert(c.artifacts.some(a=>a.file==='consent-http-fixture'));
  assert.match(stdout,/go version go1\.26\.6 linux\/amd64/);assert.match(stdout,/uid=1000/);
  for(const name of ['TestPreviewURLBoundary','TestUIRejectsAmbiguousFramesBeforeAction','TestUIResponseAuthorityAndAtomicity','TestUIServePlatformAndIOFailures',
  'TestUIEnvironmentAllowlist','TestUIPublicPreflightNeverLaunches','TestUIStopsHungAndBlockedInput','TestUICancellationAndBusySlot','TestUIOutputBudgetsAndRedaction',
  'TestUIMalformedStartFailureAndSequentialRelease','TestLocalBrowserOwnedURLAndSingleAttempt','TestLocalBrowserFailureRevokesHost','TestLocalBrowserConcurrentAttempt','TestLinuxFixedCommandPolicy','TestLinuxDesktopEnvironmentBoundary','TestLinuxNativeResultBoundary','TestLinuxNativeCancelAndDiagnosticPrecedence','TestLinuxSystemExecutableTrust','TestLinuxExecKeepsPIDAndSeparatesBrowserStreams'])assert(top.some(x=>x.Test===name));
  if(final){
   assert.equal(lines.filter(x=>x.startsWith('crossbuild=')).length,6);
   for(const platform of ['linux','windows','darwin'])for(const arch of ['amd64','arm64'])assert(lines.includes('crossbuild='+platform+'/'+arch+' bridge-and-five-test-binaries=passed native-execution=not-tested'));
   let progress;const fuzz=[];
   for(const line of lines){
    const p=/^fuzz: elapsed: (\d+)s, execs: (\d+) /.exec(line);if(p)progress={reported_elapsed_seconds:+p[1],executions:+p[2]};
    const done=/^bounded-fuzz=(\w+) passed requested-duration=5s native-device=not-tested$/.exec(line);
    if(done){assert(progress);fuzz.push({target:done[1],requested_seconds:5,...progress});progress=null;}
   }
   assert.equal(fuzz.length,13);assert.deepEqual(fuzz,c.fuzz);assert(fuzz.some(x=>x.target==='FuzzNativeUIFrame'));assert(fuzz.some(x=>x.target==='FuzzPreviewURL'));assert(fuzz.some(x=>x.target==='FuzzLinuxUIResult'));
  }
 }else{
  assert(r.command.includes(index.browser_image));assert.equal(r.command.at(-1),'/checks/make-plate-local-server-browser.cjs');
  assert.equal(r.command[r.command.indexOf('--entrypoint')+1],'node');
  assert(r.command.includes(path.join(root,'containment-mp1b8-browser-deps-20260914')+':/deps:ro'));
  assert(r.command.includes(path.join(root,'containment-mp1b9b2-go-final-20260914')+':/fixtures:ro'));
  const goCapture=index.captures.find(x=>x.kind==='go-final'),goResult=JSON.parse(fs.readFileSync(path.join(root,goCapture.directory,'result.json'),'utf8'));
  assert(Date.parse(r.started_at)>Date.parse(goResult.finished_at)); // build must complete before browser starts
  const report=JSON.parse(fs.readFileSync(path.join(directory,'local-http-browser-results.json'),'utf8'));
  assert.equal(report.scope,'real-loopback-http-synthetic-backend-no-native-helper-or-vault');
  assert.deepEqual(report.fixture,goCapture.artifacts.find(a=>a.file==='consent-http-fixture'));assert.equal(report.results.length,25);
  for(const engine of ['chromium','firefox','webkit'])for(const width of [1024,390])for(const scenario of ['approve','cancel','foreign-origin','outbound-referrer']){
   const row=report.results.find(x=>x.engine===engine&&x.viewport.width===width&&x.scenario===scenario);
   assert(row);assert.equal(row.status,'passed');assert.equal(row.stages,scenario==='approve'?6:1);
  }
  assert(report.results.some(x=>x.scenario==='simulated-launch-failure-pipe-eof'&&x.status==='passed'));
 }
}
const previous=JSON.parse(fs.readFileSync(path.join(__dirname,'make-plate-consent-verification.json'),'utf8'));
assert.equal(index.playwright_tree_sha256,previous.playwright_tree_sha256);
const directory=path.join(root,'containment-mp1b8-browser-deps-20260914');
for(const file of ['package.json','package-lock.json'])assert.equal(hash(fs.readFileSync(path.join(directory,file))),hash(fs.readFileSync(path.join(app,'benchmarks/organization',file))));
const tree=crypto.createHash('sha256');
function visit(dir,prefix=''){for(const name of fs.readdirSync(dir).sort()){const file=path.join(dir,name),rel=prefix+name,s=fs.lstatSync(file);assert(!s.isSymbolicLink());if(s.isDirectory())visit(file,rel+'/');else{assert(s.isFile());tree.update(rel+'\0'+hash(fs.readFileSync(file))+'\n');}}}
visit(path.join(directory,'node_modules/playwright-core'));assert.equal(tree.digest('hex'),index.playwright_tree_sha256);
assert.equal(index.native_windows_tests_executed,0);assert.equal(index.native_macos_tests_executed,0);assert.equal(index.native_linux_ui_executed,0);
console.log(JSON.stringify({gate:index.gate,status:'linux_helper_foundation_locally_verified_desktop_qualification_and_consent_wiring_open',artifact_hashes_checked:hashes,retained_failed_captures:0}));
