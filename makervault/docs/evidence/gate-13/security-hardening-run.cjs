// Capture a named verification command into a new private directory.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {spawn, execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');
const [output, command, ...args] = process.argv.slice(2);
const durable = path.join(os.homedir(), '.local/state/makersvault/verification');
const durableOutput = output && path.dirname(output) === durable && /^containment-[a-z0-9-]+$/.test(path.basename(output));
assert(durableOutput || /^\/tmp\/makersvault-security-hardening-[a-z0-9-]+$/.test(output));
if (durableOutput) {
  fs.mkdirSync(durable, {recursive:true, mode:0o700});
  assert(!fs.lstatSync(durable).isSymbolicLink(), 'Evidence root must not be a symlink');
  assert.equal(fs.statSync(durable).mode & 0o077, 0, 'Evidence root must be private');
}
assert(command && args.length);
const repository = path.resolve(__dirname, '../../../..');
fs.mkdirSync(output, {mode:0o700}); // Refuse an existing output, never overwrite.
const git = (...args) => execFileSync('git', ['-C',repository,...args], {encoding:'utf8'}).trim();
const sources = ['Makefile','makervault/api','makervault/web','makervault/scripts','makervault/benchmarks',
  'makervault/slicer-bridge','makervault/docker-compose.yml','makervault/docker-compose.deploy.yml','makervault/docker-deploy.yml'];
const started = new Date();
const metadata = {command:[command,...args],started_at:started.toISOString(),source_revision:git('rev-parse','HEAD'),
  verification_source_status:git('status','--porcelain','--',...sources)};
fs.writeFileSync(path.join(output,'started.json'), JSON.stringify(metadata,null,2)+'\n', {flag:'wx',mode:0o600});
const stdout = fs.openSync(path.join(output,'stdout.log'),'wx',0o600);
const stderr = fs.openSync(path.join(output,'stderr.log'),'wx',0o600);
console.log(JSON.stringify({output,...metadata}));
const child = spawn(command,args,{cwd:repository,stdio:['ignore',stdout,stderr]});
for (const signal of ['SIGINT','SIGTERM']) process.on(signal,()=>child.kill(signal));
child.on('error',error=>console.error(error.message));
child.on('close',(code,signal)=>{
  fs.closeSync(stdout); fs.closeSync(stderr);
  const artifacts = ['stdout.log','stderr.log'].map(file=>({file,bytes:fs.statSync(path.join(output,file)).size,
    sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(output,file))).digest('hex')}));
  const result = {...metadata,finished_at:new Date().toISOString(),duration_seconds:(Date.now()-started.getTime())/1000,
    exit_code:code,signal,end_source_revision:git('rev-parse','HEAD'),
    end_verification_source_status:git('status','--porcelain','--',...sources),artifacts};
  fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx',mode:0o600});
  console.log(JSON.stringify(result));
  process.exitCode=code ?? 1;
});
