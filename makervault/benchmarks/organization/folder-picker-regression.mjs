import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { chromium, firefox, webkit } from "playwright-core";
import { loginSession } from "../session-client.mjs";

const origin = process.env.MAKERSVAULT_BENCHMARK_WEB_URL;
const api = process.env.MAKERSVAULT_BENCHMARK_API_URL;
const username = process.env.MAKERSVAULT_BENCHMARK_USERNAME;
const password = process.env.MAKERSVAULT_BENCHMARK_PASSWORD;
const engine = process.env.MAKERSVAULT_BENCHMARK_BROWSER;
const output = resolve(process.env.MAKERSVAULT_BENCHMARK_OUTPUT);
const report = { schema: 1, capturedAt: new Date().toISOString(), engine, status: "in_progress", checks: [],
  scope: "Functional real-browser checks; explicitly injected refresh/navigation races are not performance or physical-device qualification" };
const save = () => writeFile(output, JSON.stringify(report, null, 2) + "\n");
let browser;

async function main() {
  await mkdir(dirname(output), { recursive: true });
  const session = await loginSession(api, origin, username, password);
  async function json(path, body, status = 200, client = session) {
    const response = await client.fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    assert.equal(response.status, status, `POST ${path}`); return response.json();
  }
  const left = await json("/folders", { name: "Left" });
  const right = await json("/folders", { name: "Right" });
  const source = await json("/folders", { name: "Brackets", parent_id: left.id });
  const collision = await json("/folders", { name: "Brackets", parent_id: right.id });
  const free = await json("/folders", { name: "Free folder", parent_id: right.id });
  async function upload(folder) {
    const form = new FormData();
    form.set("file", new Blob(["cube([1,2,3]);\n"]), "moving-model.scad");
    form.set("title", "Moving model"); form.set("folder_id", folder);
    const response = await session.fetch("/upload", { method: "POST", body: form });
    assert.equal(response.status, 200); return response.json();
  }
  const target = await upload(source.id);
  const other = await upload(collision.id);
  browser = await ({ chromium, firefox, webkit }[engine]).launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(10000);
  const alerts = [];
  page.on("dialog", async dialog => { alerts.push(dialog.message()); await dialog.dismiss(); });
  const mutations = [];
  page.on("request", request => {
    if (request.method() === "POST" && /\/api\/asset\/[^/]+\/folder$/.test(new URL(request.url()).pathname)) {
      mutations.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() });
    }
  });
  async function signIn(targetPage, user, secret) {
    await targetPage.goto(origin, { waitUntil: "domcontentloaded" });
    await targetPage.locator('input[autocomplete="username"]').fill(user);
    await targetPage.locator('input[autocomplete="current-password"]').fill(secret);
    await targetPage.locator("form").getByRole("button", { name: "Sign in", exact: true }).click();
    await targetPage.locator('[data-asset-id]').first().waitFor();
  }
  await signIn(page, username, password);
  const main = page.locator("main"), sidebar = page.locator("aside");
  const card = main.locator(`[data-asset-id="${target.id}"]`).locator("..");
  const move = card.getByRole("button", { name: "Move to folder…", exact: true });
  const dialog = page.getByRole("dialog", { name: "Move to folder", exact: true });
  const search = dialog.getByRole("searchbox", { name: "Search destinations" });
  const destinations = dialog.getByRole("listbox", { name: "Destination folder" });
  const confirm = dialog.getByRole("button", { name: "Move model", exact: true });
  async function check(label) { report.checks.push(label); await save(); }
  async function folderIs(expected) {
    const response = await session.fetch("/assets?limit=25"); assert.equal(response.status, 200);
    const assets = await response.json();
    assert.equal(assets.find(asset => asset.id === target.id)?.folder_id ?? null, expected);
    assert.equal(assets.find(asset => asset.id === other.id)?.folder_id, collision.id);
  }
  async function closed() {
    await dialog.waitFor({ state: "detached" });
    assert.equal(await page.locator("dialog").count(), 0);
    assert.equal(await card.locator("option").count(), 2); // Only placeholder + Download file for an untagged SCAD.
  }
  async function choose(id) {
    await move.click(); await dialog.waitFor();
    await destinations.selectOption(id ?? "");
  }
  async function confirmStatus(status) {
    const [response] = await Promise.all([
      page.waitForResponse(response => new URL(response.url()).pathname === `/api/asset/${target.id}/folder` && response.request().method() === "POST"),
      confirm.click(),
    ]);
    assert.equal(response.status(), status);
  }
  await closed();
  await move.focus(); await move.press("Enter");
  assert.equal(await search.evaluate(element => document.activeElement === element), true);
  assert.equal(await confirm.isDisabled(), true);
  await search.fill("Right / Free folder"); await search.press("Enter");
  assert.equal(await destinations.evaluate(element => document.activeElement === element), true);
  await destinations.press("End"); assert.equal(await destinations.inputValue(), free.id);
  await destinations.press("Enter");
  assert.equal(await confirm.evaluate(element => document.activeElement === element), true);
  assert.equal(mutations.length, 0);
  await confirm.press("Escape"); await closed();
  assert.equal(await move.evaluate(element => document.activeElement === element), true);
  await folderIs(source.id);
  await check("keyboard opens/searches/selects; Enter selects without moving; Escape cancels and returns focus");

  await move.click(); await search.fill("not a folder");
  assert.equal(await destinations.isDisabled(), true); assert.equal(await confirm.isDisabled(), true);
  assert.equal(await dialog.getByRole("status").textContent(), "No matching folders.");
  await search.fill("Brackets");
  assert.equal(await destinations.getByRole("option", { name: "Left / Brackets", exact: true }).count(), 1);
  assert.equal(await destinations.getByRole("option", { name: "Right / Brackets", exact: true }).count(), 1);
  await destinations.selectOption(source.id); assert.equal(await confirm.isDisabled(), true);
  await destinations.selectOption(collision.id); assert.equal(await confirm.isEnabled(), true);
  await page.setViewportSize({ width: 390, height: 844 });
  const box = await dialog.boundingBox(); assert(box.x >= 0 && box.x + box.width <= 390);
  await page.screenshot({ path: resolve(dirname(output), `folder-picker-${engine}.png`) });
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click(); await closed();
  assert.equal(mutations.length, 0); await folderIs(source.id);
  await page.setViewportSize({ width: 1440, height: 900 });
  await check("full paths disambiguate duplicate leaves; empty/current destination blocked; narrow dialog and Cancel preserve bytes/location");

  await choose(free.id); const before = mutations.length;
  await confirmStatus(200); await closed(); await folderIs(free.id);
  assert.equal(mutations.length, before + 1);
  assert.equal(mutations.at(-1).path, `/api/asset/${target.id}/folder`);
  assert.equal(mutations.at(-1).body.folder_id, free.id);
  assert.equal(await card.locator("[data-folder-id]").textContent(), "Right / Free folder");
  await choose(null); await confirmStatus(200); await closed(); await folderIs(null);
  await choose(source.id); await confirmStatus(200); await closed(); await folderIs(source.id);
  const payload = await session.fetch(target.url);
  assert.equal(await payload.text(), "cube([1,2,3]);\n");
  await check("explicit confirmation moves exactly the intended ID, updates its path, supports Unassigned, preserves the other ID and primary bytes");

  await choose(collision.id); await confirmStatus(409);
  await dialog.getByRole("alert").waitFor(); await folderIs(source.id);
  assert.equal(await destinations.inputValue(), collision.id);
  await destinations.selectOption(free.id); await confirmStatus(200); await closed();
  await choose(source.id); await confirmStatus(200); await closed();
  await check("real folder/name conflict stays visible and permits a deliberate destination retry");

  const deleted = await json("/folders", { name: "Temporary destination" });
  await page.reload(); await move.waitFor(); await choose(deleted.id);
  assert.equal((await session.fetch(`/folder/${deleted.id}`, { method: "DELETE" })).status, 200);
  await confirmStatus(400); await dialog.getByRole("alert").waitFor(); await folderIs(source.id);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await choose(free.id);
  assert.equal((await session.fetch(`/asset/${target.id}`, { method: "DELETE" })).status, 200);
  await confirmStatus(404); await dialog.getByRole("alert").waitFor();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await json(`/trash/${target.id}/restore`, {}); await page.reload(); await move.waitFor();
  await check("deleted destination and deleted Artifact are refused by the API without moving a different model");

  const endpoint = `**/api/asset/${target.id}/folder`;
  await page.route(endpoint, route => route.fulfill({ status: 403, contentType: "application/json", body: '{"detail":"Synthetic permission refusal"}' }));
  await choose(free.id); await confirmStatus(403); await dialog.getByRole("alert").waitFor();
  await folderIs(source.id); assert.equal(alerts.length, 0);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click(); await page.unroute(endpoint);
  await check("permission refusal remains actionable in the dialog without a false success or sign-out");

  await choose(free.id); const beforeInvalidation = mutations.length;
  // Controlled lifecycle race, not a normal user action: a native modal makes the background inert.
  await main.getByRole("button", { name: "Search", exact: true }).evaluate(element => element.click());
  await closed(); assert.equal(mutations.length, beforeInvalidation);
  await move.waitFor(); await choose(free.id);
  await sidebar.getByTitle("Right", { exact: true }).evaluate(element => element.click());
  await dialog.waitFor({ state: "detached" }); assert.equal(mutations.length, beforeInvalidation);
  await sidebar.getByRole("button", { name: /All files/ }).click(); await move.waitFor();
  await check("injected refresh/folder-view changes invalidate an unconfirmed picker without any POST");

  let release, captured;
  const held = new Promise(resolve => { release = resolve; });
  const ready = new Promise(resolve => { captured = resolve; });
  await page.route(endpoint, async route => { captured(); await held;
    await route.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"Synthetic late authorization failure"}' }); });
  try {
    await choose(free.id); await confirm.click();
    let timer;
    try { await Promise.race([ready, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Move request not captured")), 10000); })]); }
    finally { clearTimeout(timer); }
    assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), true);
    assert.equal(await dialog.getByRole("button", { name: "Moving…", exact: true }).isDisabled(), true);
    await page.keyboard.press("Escape"); assert.equal(await dialog.count(), 1);
    await sidebar.getByRole("button", { name: "Trash", exact: true }).evaluate(element => element.click());
    await main.getByRole("heading", { name: "Trash", exact: true }).waitFor();
    release(); await page.unrouteAll({ behavior: "wait" }); await page.waitForTimeout(200);
    assert.equal(alerts.length, 0); assert.equal(await dialog.count(), 0);
    assert.equal(await main.getByRole("heading", { name: "Trash", exact: true }).count(), 1);
    await folderIs(source.id);
  } finally { release(); }
  await check("double-submit/cancel blocked during confirmed work; late 401 after injected view departure cannot affect the new view");

  await sidebar.getByRole("button", { name: /All files/ }).click(); await move.waitFor();
  await page.route(endpoint, route => route.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"Synthetic current authorization failure"}' }));
  await choose(free.id); await confirmStatus(401);
  await page.locator('input[autocomplete="username"]').waitFor();
  assert.equal(alerts.length, 1); assert.match(alerts[0], /session has expired/); await folderIs(source.id);
  await check("current 401 still closes the picker and requires sign-in");

  const temporary = randomUUID() + "-Initial", replacement = randomUUID() + "-Changed";
  await json("/session/reauthenticate", { password });
  await json("/users", { username: "picker-viewer", display_name: "Picker Viewer", password: temporary, role: "viewer" }, 201);
  const initialViewer = await loginSession(api, origin, "picker-viewer", temporary);
  await json("/account/password", { new_password: replacement }, 200, initialViewer);
  const viewerSession = await loginSession(api, origin, "picker-viewer", replacement);
  const viewer = await browser.newPage();
  await signIn(viewer, "picker-viewer", replacement);
  assert.equal(await viewer.getByRole("button", { name: "Move to folder…", exact: true }).count(), 0);
  assert.equal(await viewer.locator("dialog").count(), 0);
  assert.equal(await viewer.locator("[data-folder-id]").count(), 2);
  const denied = await viewerSession.fetch(`/asset/${target.id}/folder`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ folder_id: free.id }) });
  assert.equal(denied.status, 403); await folderIs(source.id);
  await check("real Viewer account sees current paths but no move controls; API independently denies mutation");
  report.status = "passed";
}

main().catch(error => { report.status = "failed"; report.error = error.message; process.exitCode = 1; })
  .finally(async () => { await browser?.close().catch(() => {}); await save(); });
