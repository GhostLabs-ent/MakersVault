import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { chromium } from "playwright-core";
import { loginSession } from "../session-client.mjs";

const origin = process.env.MAKERSVAULT_BENCHMARK_WEB_URL;
const api = process.env.MAKERSVAULT_BENCHMARK_API_URL;
const username = process.env.MAKERSVAULT_BENCHMARK_USERNAME;
const password = process.env.MAKERSVAULT_BENCHMARK_PASSWORD;
const outputPath = resolve(process.env.MAKERSVAULT_BENCHMARK_OUTPUT);
const report = { schema: 1, capturedAt: new Date().toISOString(), checks: [], status: "in_progress" };
const save = () => writeFile(outputPath, JSON.stringify(report, null, 2) + "\n");
let browser;

async function main() {
  await mkdir(dirname(outputPath), { recursive: true });
  const session = await loginSession(api, origin, username, password);
  async function upload(name, notes = "") {
    const form = new FormData();
    form.set("file", new Blob(["cube([1,2,3]);\n"]), name + ".scad");
    form.set("title", name); form.set("notes", notes); form.set("tags", "base");
    const response = await session.fetch("/upload", { method: "POST", body: form });
    assert.equal(response.status, 200); return response.json();
  }
  for (let i = 0; i < 30; i++) await upload(`Fixture ${String(i).padStart(2, "0")}`);
  const target = await upload("ZZZ restored model", "race needle");
  await upload("ZZZ other model", "race needle");
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(10000);
  const dialogs = [];
  page.on("dialog", async dialog => { dialogs.push(dialog.message()); await dialog.dismiss(); });
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const cards = page.locator('[title="Double-click to open large preview"]');
  await cards.first().waitFor();
  const search = page.getByPlaceholder("Search title, filename, notes...");
  const targetBox = page.getByRole("checkbox", { name: "Select " + target.name, exact: true });

  async function searchFor(query, expected) {
    await search.fill(query);
    await Promise.all([
      page.waitForResponse(response => new URL(response.url()).pathname === "/api/assets" &&
        (new URL(response.url()).searchParams.get("q") || "") === query),
      search.press("Enter"),
    ]);
    await page.waitForFunction(count => document.querySelectorAll('[title="Double-click to open large preview"]').length === count, expected);
  }
  async function holdNext(path, predicate, status) {
    const bounded = async (promise, label) => {
      let timer;
      try {
        return await Promise.race([promise, new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error(`Timed out waiting for ${label}`)), 10000);
        })]);
      } finally { clearTimeout(timer); }
    };
    let release, captured, completed;
    const held = new Promise(resolve => { release = resolve; });
    const ready = new Promise(resolve => { captured = resolve; });
    const done = new Promise(resolve => { completed = resolve; });
    let taken = false;
    const pattern = `**/api/${path}?**`;
    const handler = async route => {
      if (taken || !predicate(new URL(route.request().url()))) return route.continue();
      taken = true;
      const response = await route.fetch();
      captured();
      await held;
      if (status) await route.fulfill({ status, contentType: "application/json", body: '{"detail":"synthetic stale authorization failure"}' });
      else await route.fulfill({ response });
      completed();
    };
    await page.route(pattern, handler);
    return { get ready() { return bounded(ready, `held ${path} response`); }, release, async finish() {
      release(); await bounded(done, `released ${path} response`);
      // Deliberate response-order regression, not a performance measurement.
      await page.waitForTimeout(300);
      await page.unroute(pattern, handler);
    } };
  }
  async function assertFiltered(label) {
    assert.equal(await search.inputValue(), "race needle");
    assert.equal(await cards.count(), 2);
    assert.equal(await targetBox.count(), 1);
    const response = await session.fetch("/assets?limit=25&q=race%20needle");
    assert((await response.json()).some(item => item.id === target.id));
    report.checks.push(label); await save();
  }

  for (const [path, status] of [["assets", null], ["tags", null], ["assets", 401]]) {
    assert.equal((await session.fetch("/asset/" + target.id, { method: "DELETE" })).status, 200);
    await page.getByRole("button", { name: "Trash", exact: true }).click();
    await page.getByRole("heading", { name: "Trash", exact: true }).waitFor();
    const row = page.getByTitle(target.name, { exact: true }).locator("..").locator("..");
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith(`/trash/${target.id}/restore`) && response.request().method() === "POST"),
      row.getByRole("button", { name: "Restore", exact: true }).click(),
    ]);
    await page.getByText(`Restored ${target.name}.`, { exact: true }).waitFor();
    const hold = await holdNext(path, url => !url.searchParams.get("q"), status);
    try {
      await page.getByRole("button", { name: /All files/ }).click();
      await hold.ready;
      await searchFor("race needle", 2);
      await hold.finish();
      await assertFiltered(`restore: late ${path}${status ? " 401" : ""} cannot replace the new search`);
      assert.equal(dialogs.length, 0);
    } finally { hold.release(); }
  }

  await searchFor("", 20);
  const pagination = await holdNext("assets", url => Number(url.searchParams.get("offset")) > 0);
  try {
    await page.getByRole("button", { name: "Load more", exact: true }).click();
    await pagination.ready;
    await searchFor("race needle", 2);
    await pagination.finish();
    await assertFiltered("old pagination cannot append into a newer search");
  } finally { pagination.release(); }

  await searchFor("", 20);
  await search.fill("race needle"); // Not submitted: paging still belongs to All files.
  const [nextPage] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === "/api/assets" &&
      Number(new URL(response.url()).searchParams.get("offset")) > 0),
    page.getByRole("button", { name: "Load more", exact: true }).click(),
  ]);
  assert.equal(new URL(nextPage.url()).searchParams.get("q"), null);
  await page.waitForFunction(() => document.querySelectorAll('[title="Double-click to open large preview"]').length === 32);
  report.checks.push("pagination uses the applied query, not unsubmitted text"); await save();

  const departed = await holdNext("assets", url => url.searchParams.get("q") === "departed", 401);
  try {
    await search.fill("departed"); await search.press("Enter"); await departed.ready;
    await page.getByRole("button", { name: "Trash", exact: true }).click();
    await page.getByRole("heading", { name: "Trash", exact: true }).waitFor();
    await departed.finish();
    assert.equal(await page.getByRole("heading", { name: "Trash", exact: true }).count(), 1);
    assert.equal(dialogs.length, 0);
    report.checks.push("unmounted grid ignores its stale authorization failure"); await save();
  } finally { departed.release(); }

  await page.getByRole("button", { name: /All files/ }).click(); await cards.first().waitFor();
  const current = await holdNext("assets", url => url.searchParams.get("q") === "current", 401);
  try {
    await search.fill("current"); await search.press("Enter"); await current.ready;
    await current.finish();
    await page.locator('input[autocomplete="username"]').waitFor();
    assert.equal(dialogs.length, 1);
    assert(dialogs[0].includes("session has expired"));
    report.checks.push("current authorization failure still requires sign-in");
  } finally { current.release(); }
  report.status = "passed";
}

main().catch(error => {
  report.status = "failed"; report.error = error.message; process.exitCode = 1;
}).finally(async () => { await browser?.close().catch(() => {}); await save(); });
