// Read-only MP-1b-9b-4a evidence join; historical failures/checkers are not rewritten.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const {execFileSync}=require('node:child_process');
const repository=path.resolve(__dirname,'../../../..'),app=path.join(repository,'makervault');
const index=JSON.parse(fs.readFileSync(path.join(__dirname,'make-plate-native-qualification-verification.json'),'utf8'));
const root=path.join(os.homedir(),'.local/state/makersvault/verification');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const git=(...args)=>execFileSync('git',args,{cwd:repository,encoding:'utf8'}).trim();
assert.equal(index.schema_version,1);assert.equal(index.gate,'MP-1b-9b-4a');assert.equal(index.private_evidence_root,root);
assert.equal(index.entry_revision,'e4d121bbe5ec0014817ca43cbd472f66cc43f987');
assert.equal(index.implementation_revision,'01594bd3e8f024e15a195690d82a8cbe72b02e63');
const sources=['makervault/api','makervault/web','makervault/slicer-bridge','makervault/docs/evidence/gate-13/security-hardening-run.cjs',
'makervault/docs/evidence/gate-13/make-plate-native-qualification-check.sh','makervault/docs/evidence/gate-13/make-plate-async-picker-check.sh','makervault/docs/evidence/gate-13/make-plate-async-picker-browser.cjs',
'makervault/docs/evidence/gate-13/make-plate-async-picker-regression.cjs','makervault/docs/evidence/gate-13/make-plate-local-server-browser.cjs',
'makervault/benchmarks/organization/package.json','makervault/benchmarks/organization/package-lock.json'];
assert.equal(git('status','--porcelain','--',...sources),'');
git('diff','--exit-code',index.implementation_revision,'--',...sources);
git('diff','--exit-code',index.entry_revision,'--','makervault/api','makervault/web','makervault/slicer-bridge/cmd','makervault/slicer-bridge/go.mod',
'makervault/slicer-bridge/internal/printerpreset','makervault/slicer-bridge/internal/presetfiles','makervault/slicer-bridge/internal/presetworker',
'makervault/slicer-bridge/internal/presetui','makervault/slicer-bridge/internal/presetconsent/server.go',
'makervault/docs/evidence/gate-13/make-plate-local-server-browser.cjs','makervault/docs/evidence/gate-13/security-hardening-run.cjs');
assert.deepEqual(index.captures.map(c=>c.kind),['go-preflight','go-final','go-final2','browser-final']);
let hashes=0;
for(const c of index.captures){
 assert.equal(c.directory,'containment-mp1b9b4a-'+c.kind+'-20260915');
 const directory=path.join(root,c.directory);
 const r=JSON.parse(fs.readFileSync(path.join(directory,'result.json'),'utf8'));
 const final=c.kind!=='go-preflight';
 assert.equal(r.exit_code,c.kind==='go-final'?1:0);assert.equal(c.exit_code,r.exit_code);assert.equal(c.duration_seconds,r.duration_seconds);
 assert.equal(r.signal,null);assert.equal(r.command[0],'docker');
 for(const [flag,value] of [['--network','none'],['--pull','never'],['--user','1000:1000']])assert.equal(r.command[r.command.indexOf(flag)+1],value);
 assert(!r.command.includes('-p')&&!r.command.includes('--publish')&&!r.command.includes('--privileged'));
 assert.equal(r.source_revision,final?index.implementation_revision:index.entry_revision);assert.equal(r.end_source_revision,r.source_revision);
 assert.equal(r.verification_source_status,r.end_verification_source_status);if(final)assert.equal(r.verification_source_status,'');
 assert.deepEqual(fs.readdirSync(directory).sort(),c.artifacts.map(a=>a.file));
 for(const a of c.artifacts){
  assert(a.file==='consent-http-fixture'||/^preset-native-(linux|windows)-(amd64|arm64)(\.exe)?$/.test(a.file)||/^[\w.-]+\.(log|html|png|json|txt)$/.test(a.file));
  const bytes=fs.readFileSync(path.join(directory,a.file));assert.equal(bytes.length,a.bytes);assert.equal(hash(bytes),a.sha256);hashes++;
 }
 for(const a of r.artifacts)assert.deepEqual(a,c.artifacts.find(x=>x.file===a.file));
 const stdout=fs.readFileSync(path.join(directory,'stdout.log'),'utf8'),stderr=fs.readFileSync(path.join(directory,'stderr.log'),'utf8');
 assert(r.command.includes(app+'/docs/evidence/gate-13:/checks:ro'));assert(r.command.includes(directory+':/evidence'));
 if(c.kind==='go-final'){
  assert.equal(stderr,'');assert(r.command.includes(index.go_image));
  assert.deepEqual(r.command.slice(-3),['sh','/checks/make-plate-native-qualification-check.sh',index.implementation_revision]);
  assert.match(stdout,/--- FAIL: FuzzBambuLocations/);assert.match(stdout,/context deadline exceeded/);
  assert.equal(stdout.split('\n').filter(x=>x.startsWith('crossbuild=')).length,6);
  assert.equal(stdout.split('\n').filter(x=>x.startsWith('bounded-fuzz=')).length,5);
  assert(!c.artifacts.some(a=>a.file.startsWith('preset-native-')));
  continue; // retained failed fuzz run is not final qualification evidence
 }
 if(c.kind.startsWith('go-')){
  assert.equal(stderr,'');assert(r.command.includes(index.go_image));
  for(const [src,dst] of [['slicer-bridge','/src'],
  ['slicer-bridge/internal/printerpreset/testdata','/mount-fixture'],['slicer-bridge/internal/printerpreset/testdata/child.json','/mount-fixture/child.json'],
  ['slicer-bridge/internal/presetfiles/testdata/location','/location-mount'],['slicer-bridge/internal/presetfiles/testdata/location/system','/location-mount/system'],
  ['slicer-bridge/internal/presetfiles/testdata/accounts','/accounts-mount'],['slicer-bridge/internal/presetfiles/testdata/accounts/user','/accounts-mount/user'],
  ['slicer-bridge/internal/presetfiles/testdata/accounts','/account-child-mount'],['slicer-bridge/internal/presetfiles/testdata/accounts/user/fixture-account','/account-child-mount/user/fixture-account']])assert(r.command.includes(app+'/'+src+':'+dst+':ro'));
  assert.deepEqual(r.command.slice(-3),['sh','/checks/make-plate-native-qualification-check.sh',final?index.implementation_revision:'preflight']);
  const lines=stdout.split('\n'),events=lines.filter(x=>x.startsWith('{')).map(x=>JSON.parse(x));
  assert.equal(events.filter(x=>x.Action==='fail'||x.Action==='skip').length,0);
  const passes=events.filter(x=>x.Action==='pass'&&x.Test),top=passes.filter(x=>!x.Test.includes('/'));
  assert.equal(top.filter(x=>x.Test.startsWith('Test')).length,215);assert.equal(top.length,229);assert.equal(passes.length,481);
  assert.equal(c.unit_tests_passed,215);assert.equal(c.top_level_pass_events,229);assert.equal(c.inclusive_pass_events,481);
  assert.equal(c.artifacts.filter(a=>a.file.endsWith('.html')).length,6);assert(c.artifacts.some(a=>a.file==='consent-http-fixture'));
  assert.match(stdout,/go version go1\.26\.6 linux\/amd64/);assert.match(stdout,/uid=1000/);
  for(const name of ['TestPickerExplicitAsyncConsentAndConfirmation','TestPickerCancellationKeepsSlotAndDropsLateSuccess',
  'TestPickerOwnerCloseAndExpiryDiscardLateResult','TestPickerErrorsAndInvalidPathsNeverFallBack',
  'TestPickerRejectsUnconsentedStaleAndPathActions','TestPickerHTTPReturnsBeforeDialogAndRefreshIsReadOnly',
  'TestLocalBrowserOwnedURLAndSingleAttempt','TestLocalBrowserFailureRevokesHost','TestLocalBrowserConcurrentAttempt'])assert(top.some(x=>x.Test===name));
  const inspection=JSON.parse(fs.readFileSync(path.join(directory,'qualification-inspect.json'),'utf8'));
  assert.equal(inspection.schema_version,1);assert.equal(inspection.scope,'native-ui-with-synthetic-metadata-only');
  assert.equal(inspection.source_revision,final?index.implementation_revision:'preflight');
  assert.equal(inspection.os,'linux');assert.equal(inspection.architecture,'amd64');assert.equal(inspection.go_version,'go1.26.6');
  assert.equal(inspection.outcome,'inspection_only_no_native_ui');assert.equal(inspection.browser_accepted,false);assert.equal(inspection.gate_qualified,false);
  assert(!('synthetic_review_sha256' in inspection));
  assert.match(fs.readFileSync(path.join(directory,'qualification-default-build-refused.txt'),'utf8'),/build constraints exclude all Go files/);
  assert.match(fs.readFileSync(path.join(directory,'qualification-noninteractive.txt'),'utf8'),/redirected input\/output is refused/);
  assert.match(fs.readFileSync(path.join(directory,'qualification-worker-refused.txt'),'utf8'),/Qualification only/);
  const binaries=c.artifacts.filter(a=>a.file.startsWith('preset-native-'));
  assert.equal(binaries.length,final?4:1);
  for(const name of ['TestUIQualificationSyntheticSession','TestUIQualificationIgnoresFilesystemAuthority','TestUIQualificationRejectsInvalidWork',
  'TestQualificationCommandRequiresExactConsent','TestQualificationCommandRejectsExtraAuthority','TestQualificationInspectIsNotNativeEvidence',
  'TestQualificationOwnerClosesAndRedactsFailures','TestQualificationPrecancelAndUnavailable','TestQualificationLocalOwnerWithoutNativeLaunch'])assert(top.some(x=>x.Test===name));
  assert(top.some(x=>x.Test==='FuzzQualificationConsent'));
  if(final){
   assert.equal(lines.filter(x=>x.startsWith('qualification-crossbuild=')).length,4);
   for(const platform of ['linux','windows'])for(const arch of ['amd64','arm64']){
    assert(lines.includes('qualification-crossbuild='+platform+'/'+arch+' executable-and-two-test-binaries=passed native-ui=not-tested'));
    assert(binaries.some(a=>a.file==='preset-native-'+platform+'-'+arch+(platform==='windows'?'.exe':'')));
   }
   assert.equal(lines.filter(x=>x.startsWith('crossbuild=')).length,6);
   for(const platform of ['linux','windows','darwin'])for(const arch of ['amd64','arm64'])assert(lines.includes('crossbuild='+platform+'/'+arch+' bridge-and-five-test-binaries=passed native-execution=not-tested'));
   let progress;const fuzz=[];
   for(const line of lines){
    const p=/^fuzz: elapsed: (\d+)s, execs: (\d+) /.exec(line);if(p)progress={reported_elapsed_seconds:+p[1],executions:+p[2]};
    const done=/^bounded-fuzz=(\w+) passed requested-duration=5s native-device=not-tested$/.exec(line);
    if(done){assert(progress);fuzz.push({target:done[1],requested_seconds:5,...progress});progress=null;}
   }
   assert.equal(fuzz.length,14);assert.deepEqual(fuzz,c.fuzz);
  }
 }else{
  assert(r.command.includes(index.browser_image));assert.equal(r.command.at(-1),'/checks/make-plate-async-picker-browser.cjs');
  assert.equal(r.command[r.command.indexOf('--entrypoint')+1],'node');
  assert(r.command.includes(path.join(root,'containment-mp1b8-browser-deps-20260914')+':/deps:ro'));
  const goCapture=index.captures.find(x=>x.kind===(final?'go-final2':'go-preflight'));
  const goResult=JSON.parse(fs.readFileSync(path.join(root,goCapture.directory,'result.json'),'utf8'));
  assert(r.command.includes(path.join(root,goCapture.directory)+':/fixtures:ro'));
  assert(Date.parse(r.started_at)>Date.parse(goResult.finished_at));
  assert.equal(stderr,'');
  const report=JSON.parse(fs.readFileSync(path.join(directory,'local-http-browser-results.json'),'utf8'));
  assert.equal(report.scope,'real-loopback-http-synthetic-backend-navigation-bound-referrer-no-native-helper-or-vault');
  assert.deepEqual(report.fixture,goCapture.artifacts.find(a=>a.file==='consent-http-fixture'));assert.equal(report.results.length,25);
  for(const engine of ['chromium','firefox','webkit'])for(const width of [1024,390])for(const scenario of ['approve','cancel','foreign-origin','outbound-referrer']){
   const row=report.results.find(x=>x.engine===engine&&x.viewport.width===width&&x.scenario===scenario);
   assert(row);assert.equal(row.status,'passed');assert.equal(row.stages,scenario==='approve'?6:1);
  }
  assert(report.results.some(x=>x.scenario==='simulated-launch-failure-pipe-eof'&&x.status==='passed'));
  const refs=stdout.split('\n').filter(x=>x.startsWith('{')).map(x=>JSON.parse(x)).filter(x=>x.referrer_check);
  assert.equal(refs.length,6);
  for(const r of refs){assert.equal(r.requests.filter(x=>x.route==='referrer-navigation'&&x.referrer==='absent').length,1);assert(!r.requests.some(x=>x.referrer==='different-origin'));}
  const picker=JSON.parse(fs.readFileSync(path.join(directory,'async-picker-browser-results.json'),'utf8'));
  assert.equal(picker.scope,'real-loopback-http-synthetic-asynchronous-picker-no-native-ui-or-vault');
  assert.deepEqual(picker.fixture,report.fixture);assert.equal(picker.results.length,30);
  for(const engine of ['chromium','firefox','webkit'])for(const width of [1024,390])for(const scenario of ['approve','stop-picker','native-cancel','unavailable','owner-close']){
   const row=picker.results.find(x=>x.engine===engine&&x.viewport.width===width&&x.scenario===scenario);
   assert(row);assert.equal(row.status,'passed');assert(row.response_ms>=0&&row.response_ms<3000);
   assert.equal(row.stages,scenario==='approve'?8:scenario==='owner-close'?3:5);
  }
  assert.equal(picker.results.reduce((n,r)=>n+r.stages,0),156);
 }
}
const added=['internal/presetconsent/qualification_ui.go','internal/presetconsent/qualification_ui_test.go',
'qualification/preset-native/README.md','qualification/preset-native/main.go','qualification/preset-native/main_test.go'];
assert.deepEqual(git('diff','--name-status',index.entry_revision,'--','makervault/slicer-bridge').split('\n'),
added.map(p=>'A\tmakervault/slicer-bridge/'+p));
for(const p of added.filter(p=>p.endsWith('.go')))assert(fs.readFileSync(path.join(app,'slicer-bridge',p),'utf8').startsWith('//go:build makersvault_native_qualification\n\n'));
const previous=JSON.parse(fs.readFileSync(path.join(__dirname,'make-plate-consent-verification.json'),'utf8'));
assert.equal(index.playwright_tree_sha256,previous.playwright_tree_sha256);
const directory=path.join(root,'containment-mp1b8-browser-deps-20260914');
for(const file of ['package.json','package-lock.json'])assert.equal(hash(fs.readFileSync(path.join(directory,file))),hash(fs.readFileSync(path.join(app,'benchmarks/organization',file))));
const tree=crypto.createHash('sha256');
function visit(dir,prefix=''){for(const name of fs.readdirSync(dir).sort()){const file=path.join(dir,name),rel=prefix+name,s=fs.lstatSync(file);assert(!s.isSymbolicLink());if(s.isDirectory())visit(file,rel+'/');else{assert(s.isFile());tree.update(rel+'\0'+hash(fs.readFileSync(file))+'\n');}}}
visit(path.join(directory,'node_modules/playwright-core'));assert.equal(tree.digest('hex'),index.playwright_tree_sha256);
assert.equal(index.native_windows_tests_executed,0);assert.equal(index.native_macos_tests_executed,0);assert.equal(index.native_linux_ui_executed,0);
console.log(JSON.stringify({gate:index.gate,status:'native_qualification_package_prepared_no_native_ui_or_profile_qualification',artifact_hashes_checked:hashes,retained_failed_captures:1,retained_incomplete_captures:0}));
