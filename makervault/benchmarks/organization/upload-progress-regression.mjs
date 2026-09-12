import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium, firefox, webkit } from "playwright-core";

const origin = process.env.MAKERSVAULT_BENCHMARK_WEB_URL;
const engine = process.env.MAKERSVAULT_BENCHMARK_BROWSER;
const output = process.env.MAKERSVAULT_BENCHMARK_OUTPUT;
const report = { engine, status: "in_progress", checks: [],
  scope: "Real browser/HTTPS upload; delayed response and 413/401 errors explicitly injected, not performance/device qualification" };
const save = () => writeFile(output, JSON.stringify(report, null, 2) + "\n");
const browser = await ({ chromium, firefox, webkit }[engine]).launch({ headless: true });
const directory = await mkdtemp(join(tmpdir(), "makersvault-upload-fixture-"));
let releaseResponse = () => {};
try {
  const page = await browser.newPage({ viewport: { width: 1024, height: 768 } });
  page.setDefaultTimeout(10000);
  page.on("dialog", dialog => dialog.dismiss());
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  async function check(name) { report.checks.push(name); await save(); }
  async function signIn() {
    await page.locator('input[autocomplete="username"]').fill(process.env.MAKERSVAULT_BENCHMARK_USERNAME);
    await page.locator('input[autocomplete="current-password"]').fill(process.env.MAKERSVAULT_BENCHMARK_PASSWORD);
    await page.locator("form").getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByRole("button", { name: "Upload folder", exact: true }).waitFor();
  }
  function mesh(triangles) {
    const bytes = Buffer.alloc(84 + triangles * 50);
    bytes.writeUInt32LE(triangles, 80);
    for (let index = 0; index < triangles; index++) {
      bytes.writeFloatLE(1, 84 + index * 50 + 24);
      bytes.writeFloatLE(1, 84 + index * 50 + 40);
    }
    return bytes;
  }
  const files = { "small.stl": mesh(1), "large.stl": mesh(1000) };
  const folder = join(directory, `UP1-${engine}`);
  await mkdir(join(folder, "parts"), { recursive: true });
  for (const [name, bytes] of Object.entries(files)) await writeFile(join(folder, "parts", name), bytes);
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await signIn();
  let resolveReceived;
  const received = new Promise(resolve => { resolveReceived = resolve; });
  const hold = new Promise(resolve => { releaseResponse = resolve; });
  let uploadCalls = 0;
  await page.route("**/api/upload", async route => {
    uploadCalls++;
    const headers = await route.request().allHeaders();
    assert(headers.cookie?.includes("__Host-makersvault_session="));
    assert(headers["x-csrf-token"]);
    assert(!headers.authorization);
    if (uploadCalls === 1) {
      const response = await route.fetch();
      assert.equal(response.status(), 200);
      resolveReceived();
      await hold;
      await route.fulfill({ response });
    } else await route.continue();
  });
  const selection = page.locator('input[type="file"][webkitdirectory]');
  await selection.setInputFiles(folder);
  await Promise.race([received, new Promise((_, reject) => {
    const timer = setTimeout(() => reject(new Error("Upload did not reach fixture API")), 10000);
    timer.unref();
  })]);
  const panel = page.getByRole("complementary", { name: "Upload progress", exact: true });
  await panel.getByText("0 / 2 files saved", { exact: true }).waitFor();
  assert.equal(await panel.locator('[data-upload-phase="complete"]').count(), 0);
  report.heldResponsePhase = await panel.locator("section").getAttribute("data-upload-phase");
  await check("secure-cookie/CSRF XHR reaches real API; held response is not called saved or complete");
  releaseResponse();
  await panel.locator('[data-upload-phase="complete"]').waitFor();
  await panel.getByText("2 / 2 files saved", { exact: true }).waitFor();
  assert.equal(await panel.getByRole("progressbar").getAttribute("value"), "100");
  assert.equal(uploadCalls, 2);
  const allAssets = await (await page.request.get(origin + "/api/assets?limit=100")).json();
  const folders = await (await page.request.get(origin + "/api/folders")).json();
  const parent = folders.find(item => item.name === `UP1-${engine}`);
  const child = folders.find(item => item.name === "parts" && item.parent_id === parent?.id);
  assert(child, "Nested destination missing");
  for (const [name, bytes] of Object.entries(files)) {
    const asset = allAssets.find(item => item.filename === name && item.folder_id === child.id);
    assert(asset, name);
    const stored = await (await page.request.get(origin + "/api" + asset.url)).body();
    assert.equal(createHash("sha256").update(stored).digest("hex"), createHash("sha256").update(bytes).digest("hex"));
  }
  await check("folder upload preserves nested destination and exact bytes; final count and percentage are correct");
  await panel.getByRole("button", { name: "Dismiss upload result" }).click();
  await page.unroute("**/api/upload");
  uploadCalls = 0;
  await page.route("**/api/upload", async route => {
    uploadCalls++;
    if (uploadCalls === 1) await route.fulfill({ status: 413, contentType: "application/json", body: '{"detail":"Injected upload ceiling"}' });
    else await route.continue();
  });
  const pickedFiles = Object.entries(files).map(([name, buffer]) => ({ name, mimeType: "model/stl", buffer }));
  await page.locator('header input[type="file"]').first().setInputFiles(pickedFiles);
  await panel.locator('[data-upload-phase="partial"]').waitFor();
  await panel.getByText("1 / 2 files saved · 1 failed", { exact: true }).waitFor();
  assert.equal(await panel.locator('[data-upload-phase="complete"]').count(), 0);
  await check("injected 413 remains a failure while the next selected file uploads successfully");
  await page.unroute("**/api/upload");
  uploadCalls = 0;
  await page.route("**/api/upload", async route => {
    uploadCalls++;
    await route.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"Injected expired session"}' });
  });
  await page.locator('header input[type="file"]').first().setInputFiles(pickedFiles);
  await page.locator('input[autocomplete="username"]').waitFor();
  assert.equal(uploadCalls, 1);
  assert.equal(await panel.count(), 0);
  await page.unroute("**/api/upload");
  await signIn();
  assert.equal(await panel.count(), 0);
  await check("injected 401 stops remaining uploads and clears progress across sign-in");
  assert.deepEqual(errors, []);
  report.browserVersion = browser.version();
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = error.message;
  throw error;
} finally {
  releaseResponse();
  await save();
  await browser.close();
  await rm(directory, { recursive: true }); // Only this generated mkdtemp fixture.
}
