// Offline rendering/form-control checks of source-generated synthetic HTML only.
// No listener, vault, live form submission, native Windows or screen-reader claim.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const {chromium,firefox,webkit} = createRequire('/deps/package.json')('playwright-core');
const stages = ['consent','roots','accounts','presets','review','approved'];
const artifacts = [];
for (const stage of stages) {
  const file = `consent-${stage}.html`;
  const data = fs.readFileSync('/fixtures/'+file);
  artifacts.push({file, bytes:data.length, sha256:crypto.createHash('sha256').update(data).digest('hex')});
}
(async () => {
  const results = [];
  for (const [engine,launcher] of Object.entries({chromium,firefox,webkit})) {
    const browser = await launcher.launch({headless:true});
    try {
      for (const viewport of [{width:1024,height:768},{width:390,height:844}]) {
        const page = await browser.newPage({viewport});
        page.setDefaultTimeout(10000);
        const errors = [], requests = [];
        page.on('pageerror',e=>errors.push(e.message));
        await page.route('**/*', route=>{requests.push(route.request().url());return route.abort();});
        for (const stage of stages) {
          const html = fs.readFileSync(`/fixtures/consent-${stage}.html`,'utf8');
          await page.setContent(html,{waitUntil:'load'});
          assert.equal(await page.getByRole('heading',{level:1}).textContent(),'Printer preset preview');
          assert((await page.locator('body').innerText()).includes('Nothing is sent or saved'));
          const layout = await page.evaluate(()=>({width:window.innerWidth, scroll:document.documentElement.scrollWidth,
            overflow:[...document.querySelectorAll('main,section,fieldset,pre,p,.choice')].filter(e=>e.getBoundingClientRect().right>window.innerWidth).map(e=>({tag:e.tagName,class:e.className,right:e.getBoundingClientRect().right}))}));
          if (layout.scroll>layout.width) {
            console.log(JSON.stringify({failure:'horizontal-overflow',engine,viewport,stage,layout}));
            await page.screenshot({path:'/evidence/overflow.png',fullPage:true});
          }
          assert(layout.scroll<=layout.width,`${engine}/${viewport.width}/${stage} horizontal overflow`);
          assert.equal(await page.locator('script,iframe,img,link').count(),0);
          if (stage==='roots'||stage==='accounts') {
            assert.equal(await page.locator('input:checked').count(),0);
            const input=page.locator('input[type=radio]').first();
            await input.focus(); await page.keyboard.press('Space');
            assert(await input.isChecked());
            assert(await input.evaluate(e=>e.value.length===64&&!e.value.includes('/')&&e.required));
          }
          if (stage==='presets') {
            assert.equal(await page.locator('input:checked').count(),0);
            await page.locator('input[type=checkbox]').first().check();
            assert.equal(await page.locator('input:checked').count(),1);
          }
          if (stage==='review') {
            const raw=await page.locator('pre').textContent();
            assert.equal(JSON.parse(raw)[0].source.name,'Fixture');
            const hash=crypto.createHash('sha256').update(raw).digest('hex');
            assert.equal(await page.locator('input[name=digest]').inputValue(),hash);
          }
          const buttons=await page.locator('button').evaluateAll(items=>items.map(e=>e.getBoundingClientRect().height));
          assert(buttons.every(height=>height>=44));
          results.push({engine,version:browser.version(),viewport,stage,status:'passed'});
          if (engine==='chromium'&&stage==='accounts') {
            await page.screenshot({path:`/evidence/consent-accounts-${viewport.width}.png`,fullPage:true});
          }
        }
        assert.deepEqual(errors,[]); assert.deepEqual(requests,[]);
        await page.close();
      }
    } finally { await browser.close(); }
  }
  const report={scope:'synthetic-rendering-only-no-http-or-native-integration',artifacts,results};
  fs.writeFileSync('/evidence/browser-results.json',JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});
  console.log(JSON.stringify({status:'passed',render_checks:results.length,engines:3,viewports:2,source_html_hashes:artifacts}));
})().catch(error=>{console.error(error);process.exitCode=1;});
