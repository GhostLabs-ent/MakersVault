// One-shot owner-authorized synthetic fixture transport; no stored credentials.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const [host, build] = process.argv.slice(2);
const durable = path.join(os.homedir(), '.local/state/makersvault/verification');
const socketRoot = path.join(durable, 'containment-mac-reader');
if (host === '--prepare' && build === undefined) {
  fs.mkdirSync(socketRoot, {mode: 0o700}); // Fresh private runtime socket directory.
  console.log(JSON.stringify({socket: path.join(socketRoot, 'ssh')}));
  process.exit(0);
}
assert.match(host || '', /^[a-zA-Z0-9._-]+@(?:\d{1,3}\.){3}\d{1,3}$/);
assert.match(build || '', /^containment-mac-reader-build-(preflight|debug|final)$/);
const root = path.join(durable, build);
assert(!fs.lstatSync(root).isSymbolicLink());
assert.equal(fs.statSync(root).mode & 0o077, 0);
assert(!fs.lstatSync(socketRoot).isSymbolicLink());
assert.equal(fs.statSync(socketRoot).mode & 0o077, 0);
const socket = path.join(socketRoot, 'ssh');
assert(fs.lstatSync(socket).isSocket());
const archive = path.join(root, 'native-tests.tar.gz');
assert(fs.lstatSync(archive).isFile());
const bytes = fs.readFileSync(archive);
assert(bytes.length > 0 && bytes.length < 64 * 1024 * 1024);
console.log(JSON.stringify({payload_bytes: bytes.length, payload_sha256: crypto.createHash('sha256').update(bytes).digest('hex')}));
const command = 'umask 077; native_root=$(mktemp -d /private/tmp/makersvault-mp1b3.XXXXXX) || exit 90; ' +
  'printf "native-fixture-root=%s\\n" "$native_root"; ' +
  'tar -xzf - -C "$native_root" || exit 92; cd "$native_root" || exit 93; /bin/sh ./run.sh';
const child = spawn('ssh', ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
  '-S', socket, host, command], {stdio: ['pipe', 'inherit', 'inherit']});
const timer = setTimeout(() => child.kill('SIGTERM'), 600000);
child.on('error', () => { clearTimeout(timer); process.exitCode = 1; });
child.stdin.on('error', () => {});
child.stdin.end(bytes);
child.on('close', (code, signal) => {
  clearTimeout(timer);
  console.log(JSON.stringify({native_transport_exit: code, signal}));
  process.exitCode = code ?? 1;
});
