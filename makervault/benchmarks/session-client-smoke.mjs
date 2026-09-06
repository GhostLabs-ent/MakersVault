import assert from "node:assert/strict";
import { loginSession } from "./session-client.mjs";

const origin = process.env.MAKERSVAULT_HARNESS_ORIGIN;
const client = await loginSession(`${origin}/api`, origin,
  process.env.MAKERSVAULT_HARNESS_USERNAME, process.env.MAKERSVAULT_HARNESS_PASSWORD);
assert.equal((await client.fetch("/assets?limit=1")).status, 200);
const body = new FormData();
body.set("file", new Blob(["solid node-session\nendsolid node-session\n"]), "node-session.stl");
const response = await client.fetch("/upload", { method: "POST", body });
assert.equal(response.status, 200);
const asset = await response.json();
assert.equal((await client.fetch(asset.url)).status, 200);
assert.equal((await client.fetch(`/asset/${asset.id}`, { method: "DELETE" })).status, 200);
assert.equal((await client.fetch("/logout", { method: "POST" })).status, 204);
assert.equal((await client.fetch("/session")).status, 401);
console.log("Benchmark session helper: production HTTPS login/read/upload/download/Trash/logout passed");
