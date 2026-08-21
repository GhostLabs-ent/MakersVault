import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { chromium } from "playwright-core";

const apiUrl = (process.env.MAKERSVAULT_BENCHMARK_API_URL || "http://localhost:18004").replace(/\/$/, "");
const webUrl = (process.env.MAKERSVAULT_BENCHMARK_WEB_URL || "http://localhost:15177").replace(/\/$/, "");
const outputPath = resolve(process.env.MAKERSVAULT_MOUNT_SCAN_OUTPUT || ".artifacts/mount-scan.json");
const username = process.env.MAKERSVAULT_BENCHMARK_USERNAME || "admin";
const password = process.env.MAKERSVAULT_BENCHMARK_PASSWORD || "local-development-only";
let browser = null;

async function loginApi() {
  const response = await fetch(`${apiUrl}/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw new Error(`API login failed: ${response.status} ${await response.text()}`);
  return (await response.json()).token;
}

async function latestScan(token) {
  const response = await fetch(`${apiUrl}/settings/mount-import/scan`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error(`Scan status failed: ${response.status} ${await response.text()}`);
  return response.json();
}

async function waitForTerminalScan(token, previousId = null) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const scan = await latestScan(token);
    if (scan && scan.id !== previousId && scan.status !== "running") return scan;
    await new Promise(resolveWait => setTimeout(resolveWait, 100));
  }
  throw new Error("Mounted-library scan did not reach a terminal state");
}

async function assertCount(page, label, count) {
  const card = page.getByText(label, { exact: true }).locator("..");
  await card.getByText(String(count), { exact: true }).waitFor();
}

async function main() {
  const token = await loginApi();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(webUrl, { waitUntil: "domcontentloaded" });
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Settings" }).waitFor({ timeout: 30_000 });
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("button", { name: /Imports & Folder Scan/ }).click();

  await page.getByText("Mount path: /imports", { exact: true }).waitFor();
  await page.getByText("Copy into MakersVault:", { exact: true }).waitFor();
  await page.getByText(/managed copy that remains usable if the mount is unavailable/).waitFor();

  await page.getByRole("button", { name: "Rescan now" }).click();
  const first = await waitForTerminalScan(token);
  if (first.status !== "completed_with_failures") throw new Error(`Unexpected first status: ${first.status}`);
  if (first.imported !== 2 || first.skipped !== 0 || first.failed !== 1) {
    throw new Error(`Unexpected first counts: ${JSON.stringify(first)}`);
  }
  await page.getByText("completed with failures", { exact: true }).waitFor({ timeout: 10_000 });
  await assertCount(page, "Imported", 2);
  await assertCount(page, "Unchanged", 0);
  await assertCount(page, "Failed", 1);
  await page.getByText("rejected.stl", { exact: true }).waitFor();
  await page.getByText(/symbolic link/).waitFor();

  await page.getByRole("button", { name: "Rescan now" }).click();
  const second = await waitForTerminalScan(token, first.id);
  if (second.imported !== 0 || second.skipped !== 2 || second.failed !== 1) {
    throw new Error(`Unexpected repeat counts: ${JSON.stringify(second)}`);
  }
  await assertCount(page, "Imported", 0);
  await assertCount(page, "Unchanged", 2);
  await assertCount(page, "Failed", 1);

  await page.getByRole("checkbox", { name: /Copy files into MakersVault storage/ }).uncheck();
  await page.getByText("Index in place:", { exact: true }).waitFor();
  await page.getByText(/mount remains authoritative and must stay available/).waitFor();
  await page.getByText(/does not delete the source/).waitFor();

  const result = {
    capturedAt: new Date().toISOString(),
    first,
    repeat: second,
    browser: {
      copyOwnershipVisible: true,
      indexOwnershipVisible: true,
      failureDetailsVisible: true,
    },
  };
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

try {
  await main();
} finally {
  await browser?.close();
}
