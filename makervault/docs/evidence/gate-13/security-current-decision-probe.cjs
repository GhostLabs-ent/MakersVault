// Benign inspection of exact images; reuse existing probes, start no application.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const read = name => JSON.parse(fs.readFileSync(path.join(__dirname,name),'utf8'));
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const current = read('security-reconciliation.json');
const native = read('security-native-verification.json');
assert.equal(process.argv.length,2);
const report = {images:{},commands:[],script_sha256:sha(__filename),probe_sha256:{}};
const command = args => {
  const output = execFileSync('docker',args,{encoding:'utf8',timeout:30000,maxBuffer:4*1024*1024});
  report.commands.push({command:['docker',...args],stdout:output});
  return output;
};
for(const [name,id] of Object.entries(current.images)) {
  const row=JSON.parse(command(['image','inspect','--format','{{json .}}',id]));
  assert.equal(row.Id,id); assert.equal(row.Os,'linux'); assert.equal(row.Architecture,'amd64');
  report.images[name]={id:row.Id,os:row.Os,architecture:row.Architecture,
    revision:row.Config.Labels['org.opencontainers.image.revision']};
  assert.equal(report.images[name].revision,current.application_revision);
  // Full inspect output can include configuration; retain only the selected fields.
  report.commands.pop();
}
for(const [key,name] of [['components','security-closeout-runtime.py'],['delta','security-native-delta.py']]) {
  const probe=path.join(__dirname,name);
  report.probe_sha256[name]=sha(probe);
  const output=command(['run','--rm','--network','none','--read-only','--cap-drop','ALL',
    '--security-opt','no-new-privileges','--user','1000:1000','--entrypoint','python',
    '-v',probe+':/probe.py:ro',current.images.api,'/probe.py']);
  report[key]=JSON.parse(output);
  assert.deepEqual(report[key],key==='components'?native.components:native.delta_probe);
}
const installed=command(['run','--rm','--network','none','--read-only','--cap-drop','ALL',
  '--security-opt','no-new-privileges','--entrypoint','/bin/cat',current.images.web,
  '/lib/apk/db/installed']);
report.web_packages={};
for(const stanza of installed.split('\n\n')) {
  const name=stanza.match(/^P:(.+)$/m)?.[1];
  if(['busybox','busybox-binsh','ssl_client'].includes(name)) {
    assert(!report.web_packages[name]);
    report.web_packages[name]=stanza.match(/^V:(.+)$/m)?.[1];
  }
}
assert.deepEqual(report.web_packages,{'busybox':'1.37.0-r31','busybox-binsh':'1.37.0-r31','ssl_client':'1.37.0-r31'});
report.status='passed';
console.log(JSON.stringify(report));
