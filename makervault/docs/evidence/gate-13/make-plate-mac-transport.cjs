// Explicit one-shot SSH transfer of our own fixture archive; credentials are
// never arguments/environment/files. Authentication uses an existing private
// OpenSSH control socket established interactively by the operator.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const [host, socket, archive] = process.argv.slice(2);
assert.match(host || '', /^[a-zA-Z0-9._-]+@(?:\d{1,3}\.){3}\d{1,3}$/);
const durable = path.join(os.homedir(), '.local/state/makersvault/verification');
const buildRoot = path.join(durable, 'containment-mac-native-build-final');
assert.equal(socket, path.join(buildRoot, 'ssh'));
assert.equal(archive, path.join(buildRoot, 'native-tests.tar.gz'));
assert.equal(fs.lstatSync(buildRoot).isSymbolicLink(), false);
assert.equal(fs.statSync(buildRoot).mode & 0o077, 0);
assert(fs.lstatSync(socket).isSocket());
assert(fs.lstatSync(archive).isFile());
const bytes = fs.readFileSync(archive);
assert(bytes.length > 0 && bytes.length < 64 * 1024 * 1024);
console.log(JSON.stringify({payload_bytes: bytes.length, payload_sha256: crypto.createHash('sha256').update(bytes).digest('hex')}));
// Remote writes are confined to a fresh private fixture root. No sudo, package
// manager, application config, profile search or handler installation.
const command = 'umask 077; native_root=$(mktemp -d /private/tmp/makersvault-mp1b2.XXXXXX) || exit 90; ' +
  'printf "native-fixture-root=%s\\n" "$native_root"; ' +
  'tar -xzf - -C "$native_root" || exit 92; cd "$native_root" || exit 93; /bin/sh ./run.sh';
const child = spawn('ssh', ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
  '-S', socket, host, command], {stdio: ['pipe', 'inherit', 'inherit']});
const timer = setTimeout(() => child.kill('SIGTERM'), 300000);
child.on('error', () => { clearTimeout(timer); process.exitCode = 1; });
child.stdin.on('error', () => {}); // A failed SSH child may close stdin early.
child.stdin.end(bytes);
child.on('close', (code, signal) => {
  clearTimeout(timer);
  console.log(JSON.stringify({native_transport_exit: code, signal}));
  process.exitCode = code ?? 1;
});
