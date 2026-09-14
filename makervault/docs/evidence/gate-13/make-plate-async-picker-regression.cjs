// MP-1b-9b-3: derived historical HTTP regressions; bind referrer checks to navigation.
// Offline-container, actual HTTP/browser lifecycle harness; synthetic backend only.
// No native browser helper, installed handler, real profile or vault is exercised.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const crypto=require('node:crypto');
const http=require('node:http');
const {spawn}=require('node:child_process');
const {createRequire}=require('node:module');
const {chromium,firefox,webkit}=createRequire('/deps/package.json')('playwright-core');
const results=[];
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
async function bounded(promise,ms,label){
  let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(label)),ms);})]);}
  finally{clearTimeout(timer);}
}
async function fixture(){
  const child=spawn('/fixtures/consent-http-fixture',['--local-http-fixture'],{stdio:['pipe','pipe','pipe'],env:{}});
  let ready,closed,buffer='',stderr='',bad=false;
  const readiness=new Promise(resolve=>{ready=resolve;});
  const ended=new Promise(resolve=>child.once('close',(code,signal)=>resolve({code,signal})));
  const records=[];
  child.on('error',()=>{bad=true;});
  child.stdout.on('data',data=>{
    buffer+=data.toString();
    if(buffer.length>8192){bad=true;child.kill('SIGKILL');return;}
    let i;
    while((i=buffer.indexOf('\n'))>=0){
      const line=buffer.slice(0,i);buffer=buffer.slice(i+1);
      try{const record=JSON.parse(line);records.push(record);if(record.Kind==='ready')ready(record);else if(record.Kind==='closed')closed=record;else bad=true;}
      catch{bad=true;}
    }
  });
  child.stderr.on('data',data=>{stderr+=data.toString().slice(0,4096-stderr.length);});
  child.stdin.on('error',()=>{}); // child may already have closed after HTTP Cancel
  try{
    const record=await bounded(readiness,4000,'fixture readiness timeout');
    assert.match(record.URL,/^http:\/\/127\.0\.0\.1:\d+\/preset-preview\/[a-f0-9]{64}$/);
    return {url:record.URL,async stop(consume=false){
      child.stdin.end(consume?'t':'');
      let outcome;
      try{outcome=await bounded(ended,4000,'fixture teardown timeout');}
      finally{if(child.exitCode===null&&child.signalCode===null){child.kill('SIGKILL');await ended;}}
      assert.equal(outcome.code,0);assert.equal(outcome.signal,null);assert.equal(bad,false);
      assert.equal(stderr,'');assert.equal(buffer,'');assert.equal(records.length,2);
      assert(closed&&closed.Kind==='closed');
      // New connection must fail after the owned process/listener has gone away.
      await assert.rejects(fetch(record.URL,{signal:AbortSignal.timeout(1000)}));
      return closed;
    }};
  }catch(error){child.stdin.end();child.kill('SIGKILL');await ended;throw error;}
}
async function submit(page,name){
  const [response]=await Promise.all([page.waitForNavigation({waitUntil:'load'}),page.getByRole('button',{name,exact:true}).click()]);
  if(response.status()!==200){
    const req=response.request(),headers=await req.allHeaders(),origin=new URL(req.url()).origin;
    console.log(JSON.stringify({failure:'browser-form-rejected',button:name,status:response.status(),method:req.method(),origin:headers.origin===origin?'exact-local':headers.origin==='null'?'null':headers.origin?'foreign':'missing',fetchSite:headers['sec-fetch-site']||'missing',contentType:headers['content-type']||'missing'}));
  }
  assert.equal(response.status(),200);return response;
}
(async()=>{
  let attackHTML='',lastReferrer;
  const attackRequests=[];
  const attack=http.createServer((req,res)=>{
    const referrer=req.headers.referer;
    attackRequests.push({route:req.url==='/referrer-check'?'referrer-navigation':req.url==='/'?'attack-navigation':'other',
      referrer:referrer===undefined?'absent':referrer.startsWith('http://127.0.0.1:'+attack.address().port)?'attack-origin':'different-origin'});
    if(req.url==='/referrer-check')lastReferrer=referrer;
    res.setHeader('Content-Type','text/html');res.end(attackHTML);
  });
  await new Promise(resolve=>attack.listen(0,'127.0.0.1',resolve));
  const attackOrigin='http://127.0.0.1:'+attack.address().port;
  try{
    for(const [engine,launcher] of Object.entries({chromium,firefox,webkit})){
      const browser=await launcher.launch({headless:true});
      try{
        for(const viewport of [{width:1024,height:768},{width:390,height:844}]){
          for(const scenario of ['approve','cancel','foreign-origin','outbound-referrer']){
            const local=await fixture();let stopped=false;
            const page=await browser.newPage({viewport});page.setDefaultTimeout(5000);
            const errors=[],foreign=[];let stages=0;
            page.on('pageerror',()=>errors.push('pageerror'));
            const origin=new URL(local.url).origin;
            page.on('request',request=>{
              const u=new URL(request.url());
              if(u.origin!==origin&&u.origin!==attackOrigin)foreign.push(u.origin);
            });
            const check=async()=>{
              assert.equal(await page.getByRole('heading',{level:1}).textContent(),'Printer preset preview');
              assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
              assert.equal(await page.locator('input:checked').count(),0);
              stages++;
            };
            try{
              const first=await page.goto(local.url,{waitUntil:'load'});
              assert.equal(first.status(),200);await check();
              const headers=first.headers();
              assert.equal(headers['cache-control'],'no-store');assert.equal(headers['referrer-policy'],'same-origin');
              assert.equal(headers['x-frame-options'],'DENY');assert.equal(headers['x-content-type-options'],'nosniff');
              assert(headers['content-security-policy'].includes("form-action 'self'"));
              if(scenario==='approve'){
                await submit(page,'Allow local reading');await check();
                await page.locator('input[type=radio]').first().focus();await page.keyboard.press('Space');
                await submit(page,'Use this folder');await check();
                await page.getByLabel('System presets only (do not read account presets)',{exact:true}).check();
                await submit(page,'Read printer presets');await check();
                await page.locator('input[type=checkbox]').first().check();
                await submit(page,'Review selected metadata');await check();
                const raw=await page.locator('pre').textContent(),digest=hash(raw);
                assert.equal(await page.locator('input[name=digest]').inputValue(),digest);
                assert.equal(JSON.parse(raw)[0].source.name,'Fixture');
                if(engine==='chromium')await page.screenshot({path:'/evidence/local-http-review-'+viewport.width+'.png',fullPage:true});
                await submit(page,'Approve local preview');await check();
                assert(await page.getByRole('heading',{name:'Local preview approved',exact:true}).isVisible());
                const end=await local.stop(true);stopped=true;
                assert.equal(end.Stage,'consumed');assert.equal(end.Digest,digest);assert.equal(end.Calls,4);
              }else if(scenario==='cancel'){
                await submit(page,'Cancel');
                const end=await local.stop();stopped=true;
                assert.equal(end.Stage,'cancelled');assert.equal(end.Calls,0);assert.equal(end.Digest,'');
              }else if(scenario==='outbound-referrer'){
                // Inject only a test link to an owned second loopback origin.
                // No request interception/header overrides: observe browser policy.
                attackHTML='<title>Referrer check</title>';lastReferrer='not-requested';attackRequests.length=0;
                await page.evaluate(target=>{const a=document.createElement('a');a.href=target;a.textContent='Test outgoing link';document.body.append(a);},attackOrigin+'/referrer-check');
                await Promise.all([page.waitForNavigation({waitUntil:'load'}),page.getByRole('link',{name:'Test outgoing link'}).click()]);
                assert.equal(lastReferrer,undefined);
                assert.equal(attackRequests.filter(r=>r.route==='referrer-navigation').length,1);
                assert(!attackRequests.some(r=>r.referrer==='different-origin'));
                console.log(JSON.stringify({referrer_check:engine,width:viewport.width,requests:attackRequests}));
                const end=await local.stop();stopped=true;assert.equal(end.Calls,0);assert.equal(end.Stage,'cancelled');
              }else{
                // Known nonce+CSRF is deliberate: foreign Origin must still refuse.
                const csrf=await page.locator('input[name=csrf]').first().inputValue();
                const revision=await page.locator('input[name=revision]').first().inputValue();
                attackHTML='<form method="post" action="'+local.url+'"><input name="csrf" value="'+csrf+'"><input name="revision" value="'+revision+'"><button name="decision" value="allow">Foreign approval</button></form>';
                await page.goto(attackOrigin,{waitUntil:'load'});
                const [response]=await Promise.all([page.waitForNavigation({waitUntil:'load'}),page.getByRole('button',{name:'Foreign approval'}).click()]);
                assert.equal(response.status(),403);
                await page.goto(local.url,{waitUntil:'load'});
                assert(await page.getByRole('button',{name:'Allow local reading',exact:true}).isVisible());
                const end=await local.stop();stopped=true;assert.equal(end.Calls,0);assert.equal(end.Stage,'cancelled');
              }
              assert.deepEqual(errors,[]);assert.deepEqual(foreign,[]);
              results.push({engine,version:browser.version(),viewport,scenario,stages,status:'passed'});
            }finally{
              await page.close();
              if(!stopped)await local.stop();
            }
          }
        }
      }finally{await browser.close();}
    }
    // Owner closes the readiness pipe when browser startup fails; no native launch.
    const local=await fixture();const end=await local.stop();
    assert.equal(end.Stage,'cancelled');assert.equal(end.Calls,0);
    results.push({scenario:'simulated-launch-failure-pipe-eof',status:'passed'});
  }finally{attack.closeAllConnections();await new Promise(resolve=>attack.close(resolve));}
  const binary=fs.readFileSync('/fixtures/consent-http-fixture');
  const report={scope:'real-loopback-http-synthetic-backend-navigation-bound-referrer-no-native-helper-or-vault',
    fixture:{file:'consent-http-fixture',bytes:binary.length,sha256:hash(binary)},results};
  fs.writeFileSync('/evidence/local-http-browser-results.json',JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});
  console.log(JSON.stringify({status:'passed',scenarios:results.length,approved_flows:6,real_http_stage_checks:36,engines:3,viewports:2,fixture_sha256:report.fixture.sha256}));
})().catch(error=>{
  const message=String(error.stack||error).replace(/http:\/\/127\.0\.0\.1:[^\s"'<>)]*/g,'[private-loopback-url]').replace(/[a-f0-9]{64}/g,'[redacted-token]');
  console.error(message);process.exitCode=1;
});
