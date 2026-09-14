// Actual loopback HTTP with a stdin-controlled synthetic picker, never native UI.
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const {spawn,execFileSync}=require('node:child_process');
const {createRequire}=require('node:module');
const {chromium,firefox,webkit}=createRequire('/deps/package.json')('playwright-core');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
// Retain all 25 cases; the derived harness observes the specific navigation
// instead of allowing a later favicon request to overwrite the referrer sample.
execFileSync(process.execPath,['/checks/make-plate-async-picker-regression.cjs'],{stdio:'inherit'});
const results=[];
async function bounded(promise,ms,label){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(label)),ms);})]);}finally{clearTimeout(timer);}}
async function fixture(){
 const child=spawn('/fixtures/consent-http-fixture',['--local-picker-fixture'],{stdio:['pipe','pipe','pipe'],env:{}});
 let ready,closed,buffer='',stderr='',bad=false;const records=[];
 const readiness=new Promise(resolve=>{ready=resolve;});
 const ended=new Promise(resolve=>child.once('close',(code,signal)=>resolve({code,signal})));
 child.on('error',()=>{bad=true;});child.stdin.on('error',()=>{});
 child.stdout.on('data',data=>{
  buffer+=data.toString();if(buffer.length>8192){bad=true;child.kill('SIGKILL');return;}
  let i;while((i=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,i);buffer=buffer.slice(i+1);try{const row=JSON.parse(line);records.push(row);if(row.Kind==='ready')ready(row);else if(row.Kind==='closed')closed=row;else bad=true;}catch{bad=true;}}
 });
 child.stderr.on('data',data=>{stderr+=data.toString().slice(0,4096-stderr.length);});
 try{
  const row=await bounded(readiness,4000,'picker fixture readiness timeout');
  assert.match(row.URL,/^http:\/\/127\.0\.0\.1:\d+\/preset-preview\/[a-f0-9]{64}$/);
  return {url:row.URL,complete(command){assert(['r','n','f'].includes(command));child.stdin.write(command);},async stop(consume=false){
   child.stdin.end(consume?'t':'x');let outcome;
   try{outcome=await bounded(ended,4000,'picker fixture teardown timeout');}finally{if(child.exitCode===null&&child.signalCode===null){child.kill('SIGKILL');await ended;}}
   assert.deepEqual(outcome,{code:0,signal:null});assert.equal(bad,false);assert.equal(stderr,'');assert.equal(buffer,'');assert.equal(records.length,2);assert(closed);
   await assert.rejects(fetch(row.URL,{signal:AbortSignal.timeout(1000)}));return closed;
  }};
 }catch(error){child.kill('SIGKILL');await ended;throw error;}
}
async function submit(page,name){
 const [response]=await Promise.all([page.waitForNavigation({waitUntil:'load'}),page.getByRole('button',{name,exact:true}).click()]);
 assert.equal(response.status(),200);return response;
}
async function refreshUntil(page,local,text){
 // Only explicit GET navigation; no source script, automatic refresh or status API.
 const start=Date.now();
 while(Date.now()-start<4000){
  const response=await page.goto(local.url,{waitUntil:'load'});assert.equal(response.status(),200);
  if((await page.locator('body').textContent()).includes(text))return;
  await new Promise(resolve=>setTimeout(resolve,25));
 }
 throw new Error('picker completion not visible');
}
(async()=>{
 for(const [engine,launcher] of Object.entries({chromium,firefox,webkit})){
  const browser=await launcher.launch({headless:true});
  try{for(const viewport of [{width:1024,height:768},{width:390,height:844}]){
   for(const scenario of ['approve','stop-picker','native-cancel','unavailable','owner-close']){
    const local=await fixture();let stopped=false,stages=0;const errors=[],foreign=[];
    const page=await browser.newPage({viewport});page.setDefaultTimeout(5000);
    page.on('pageerror',()=>errors.push('pageerror'));
    page.on('request',request=>{if(new URL(request.url()).origin!==new URL(local.url).origin)foreign.push('foreign');assert(!request.url().includes('PRIVATE_PICKED_FOLDER'));assert(!(request.postData()||'').includes('PRIVATE_PICKED_FOLDER'));});
    const check=async()=>{
     assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
     assert.equal(await page.locator('input:checked').count(),0);
     assert(!(await page.content()).includes('PRIVATE_PICKED_FOLDER'));
     assert.equal(await page.locator('script,meta[http-equiv=refresh]').count(),0);stages++;
    };
    try{
     assert.equal((await page.goto(local.url)).status(),200);await check();
     const start=Date.now();await submit(page,'Allow local reading and choose a folder');const responseMs=Date.now()-start;
     assert(responseMs<3000,'picker held HTTP response');await check();
     assert(await page.getByRole('button',{name:'Cancel folder selection',exact:true}).isVisible());
     assert.equal(await page.getByRole('link',{name:'Refresh status'}).getAttribute('href'),new URL(local.url).pathname);
     if(engine==='chromium'&&scenario==='approve')await page.screenshot({path:'/evidence/async-picker-waiting-'+viewport.width+'.png',fullPage:true});
     await Promise.all([page.waitForNavigation({waitUntil:'load'}),page.getByRole('link',{name:'Refresh status'}).click()]);await check();
     if(scenario==='owner-close'){
      const end=await local.stop();stopped=true;assert.equal(end.Stage,'cancelled');assert.equal(end.Calls,0);assert.equal(end.PickerCalls,1);
     }else if(scenario==='approve'){
      local.complete('r');await refreshUntil(page,local,'Use this folder');await check();
      if(engine==='chromium')await page.screenshot({path:'/evidence/async-picker-selected-'+viewport.width+'.png',fullPage:true});
      await page.locator('input[type=radio]').focus();await page.keyboard.press('Space');
      await submit(page,'Use this folder');await check();
      await page.getByLabel('System presets only (do not read account presets)',{exact:true}).check();
      await submit(page,'Read printer presets');await check();
      await page.locator('input[type=checkbox]').check();await submit(page,'Review selected metadata');await check();
      const raw=await page.locator('pre').textContent(),digest=hash(raw);
      assert.equal(await page.locator('input[name=digest]').inputValue(),digest);
      await submit(page,'Approve local preview');await check();
      const end=await local.stop(true);stopped=true;assert.equal(end.Stage,'consumed');assert.equal(end.Digest,digest);assert.equal(end.Calls,3);assert.equal(end.PickerCalls,1);
     }else{
      if(scenario==='stop-picker')await submit(page,'Cancel folder selection');
      else local.complete(scenario==='native-cancel'?'n':'f');
      await refreshUntil(page,local,scenario==='unavailable'?'selection is unavailable':'Folder selection cancelled');await check();
      assert.equal(await page.locator('input[type=radio]').count(),0);
      await submit(page,'Start over');await check();
      assert(await page.getByRole('button',{name:'Allow local reading and choose a folder',exact:true}).isVisible());
      const end=await local.stop();stopped=true;assert.equal(end.Stage,'cancelled');assert.equal(end.Calls,0);assert.equal(end.PickerCalls,1);
     }
     assert.deepEqual(errors,[]);assert.deepEqual(foreign,[]);
     results.push({engine,version:browser.version(),viewport,scenario,stages,response_ms:responseMs,status:'passed'});
    }finally{await page.close();if(!stopped)await local.stop();}
   }
  }}finally{await browser.close();}
 }
 const binary=fs.readFileSync('/fixtures/consent-http-fixture');
 const report={scope:'real-loopback-http-synthetic-asynchronous-picker-no-native-ui-or-vault',fixture:{file:'consent-http-fixture',bytes:binary.length,sha256:hash(binary)},results};
 fs.writeFileSync('/evidence/async-picker-browser-results.json',JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});
 console.log(JSON.stringify({status:'passed',async_picker_scenarios:results.length,approved_flows:6,stage_checks:results.reduce((n,r)=>n+r.stages,0),engines:3,viewports:2,fixture_sha256:report.fixture.sha256}));
})().catch(error=>{console.error(String(error.stack||error).replace(/http:\/\/127\.0\.0\.1:[^\s"'<>)]*/g,'[private-loopback-url]').replace(/[a-f0-9]{64}/g,'[redacted-token]'));process.exitCode=1;});
