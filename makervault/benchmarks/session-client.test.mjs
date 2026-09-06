import test from "node:test";
import assert from "node:assert/strict";
import { loginSession } from "./session-client.mjs";

function fixture(cookie = "makersvault_session_dev=fixture-cookie; HttpOnly; Path=/; SameSite=Lax", body = { csrf_token: "fixture-csrf" }) {
  const requests = [];
  return { requests, fetchImpl: async (url, init) => {
    requests.push({ url: String(url), init });
    return String(url).endsWith("/login")
      ? new Response(JSON.stringify(body), { headers: { "set-cookie": cookie } })
      : new Response("{}");
  } };
}

test("cookie-only reads and Origin/CSRF writes; multipart content type stays automatic", async () => {
  const f = fixture();
  const client = await loginSession("http://localhost:18003", "http://localhost:15176", "admin", "fixture", f.fetchImpl);
  await client.fetch("/assets");
  await client.fetch("/upload", { method: "POST", body: new FormData() });
  const read = new Headers(f.requests[1].init.headers);
  const write = new Headers(f.requests[2].init.headers);
  assert.equal(read.get("cookie"), "makersvault_session_dev=fixture-cookie");
  assert.equal(read.get("authorization"), null);
  assert.equal(write.get("origin"), "http://localhost:15176");
  assert.equal(write.get("x-csrf-token"), "fixture-csrf");
  assert.equal(write.get("content-type"), null);
  assert.equal(f.requests[2].init.redirect, "error");
  assert.equal(JSON.stringify(client).includes("fixture-cookie"), false);
});

test("Secure cookies require HTTPS; host-only cookie shape is checked", async () => {
  const secure = "__Host-makersvault_session=fixture-cookie; Secure; HttpOnly; Path=/; SameSite=Lax";
  await assert.rejects(loginSession("http://localhost", "http://localhost", "admin", "fixture", fixture(secure).fetchImpl), /HTTPS/);
  const client = await loginSession("https://localhost/api", "https://localhost", "admin", "fixture", fixture(secure).fetchImpl);
  await client.fetch("/session");
  for (const malformed of [secure + "; Domain=localhost", secure.replace("HttpOnly; ", ""), secure.replace("Path=/", "Path=/api")]) {
    await assert.rejects(loginSession("https://localhost", "https://localhost", "admin", "fixture", fixture(malformed).fetchImpl), /cookie/);
  }
});

test("no JWT or pending-MFA fallback; missing session/CSRF fails closed", async () => {
  for (const body of [{ token: "legacy-secret" }, { mfa_required: true }, {}]) {
    await assert.rejects(loginSession("http://localhost", "http://localhost", "admin", "fixture", fixture(undefined, body).fetchImpl), /session/);
  }
  await assert.rejects(loginSession("http://localhost", "http://localhost", "admin", "fixture", fixture("other=x").fetchImpl), /cookie/);
});

test("requests cannot escape the configured API or override auth/redirect controls", async () => {
  const f = fixture();
  const client = await loginSession("http://localhost/api", "http://localhost", "admin", "fixture", f.fetchImpl);
  for (const path of ["https://evil.test/", "//evil.test/", "/../outside", "/%2e%2e/outside", "/\\evil.test/"]) {
    await assert.rejects(client.fetch(path), /path/);
  }
  for (const headers of [{ Cookie: "other=x" }, { Authorization: "Bearer old" }, { Origin: "https://evil.test" }, { "X-CSRF-Token": "override" }]) {
    await assert.rejects(client.fetch("/assets", { headers }), /override/);
  }
  await assert.rejects(client.fetch("/assets", { redirect: "follow" }), /redirect/);
  assert.equal(f.requests.length, 1);
});

test("failed login does not echo bodies or credentials", async () => {
  const fetchImpl = async () => new Response("sensitive server response", { status: 401 });
  await assert.rejects(loginSession("http://localhost", "http://localhost", "admin", "private-password", fetchImpl), error =>
    error.message === "Harness login failed: HTTP 401");
});
