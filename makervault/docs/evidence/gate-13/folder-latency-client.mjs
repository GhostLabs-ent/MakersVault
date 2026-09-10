import { loginSession } from "/bench/session-client.mjs";
const session = await loginSession(process.env.MV_API, process.env.MV_ORIGIN, process.env.MV_USER, process.env.MV_PASSWORD);
const samples = [];
for (let i=0; i<30; i++) {
  const start = performance.now();
  const response = await session.fetch('/folders');
  const headers = performance.now();
  const text = await response.text();
  const body = performance.now();
  const folders = JSON.parse(text);
  const end = performance.now();
  if (!response.ok || folders.length !== 1040) throw new Error('Fixture request failed');
  samples.push({headers_ms: headers-start, body_ms: body-headers, parse_ms: end-body, total_ms: end-start,
    bytes: Buffer.byteLength(text), encoding: response.headers.get('content-encoding'),
    server: JSON.parse(response.headers.get('x-fixture-timing'))});
}
console.log(JSON.stringify({samples}));
