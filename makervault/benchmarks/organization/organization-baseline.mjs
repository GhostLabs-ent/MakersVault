import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { chromium } from "playwright-core";

const apiUrl = (process.env.MAKERSVAULT_BENCHMARK_API_URL || "http://localhost:18003").replace(/\/$/, "");
const webUrl = (process.env.MAKERSVAULT_BENCHMARK_WEB_URL || "http://localhost:15176").replace(/\/$/, "");
const outputPath = resolve(process.env.MAKERSVAULT_BENCHMARK_OUTPUT || ".artifacts/baseline.json");
const username = process.env.MAKERSVAULT_BENCHMARK_USERNAME || "admin";
const password = process.env.MAKERSVAULT_BENCHMARK_PASSWORD || "local-development-only";
const assetCount = Number(process.env.MAKERSVAULT_ORGANIZATION_ASSETS || 600);
const rootCount = 8;
const branchesPerRoot = 4;
const leavesPerBranch = 2;
let activeBrowser = null;

const percentile = (values, ratio) => {
  if (!values.length) return 0;
  const ordered = [...values].sort((a, b) => a - b);
  return ordered[Math.min(ordered.length - 1, Math.floor(ordered.length * ratio))];
};

const summarize = values => ({
  samples: values.length,
  p50: percentile(values, 0.50),
  p95: percentile(values, 0.95),
  max: Math.max(0, ...values),
});

async function login() {
  const response = await fetch(`${apiUrl}/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw new Error(`API login failed: ${response.status} ${await response.text()}`);
  return (await response.json()).token;
}

async function apiJson(token, path, init = {}) {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers || {}),
    },
  });
  if (!response.ok) throw new Error(`${init.method || "GET"} ${path} failed: ${response.status} ${await response.text()}`);
  return response.json();
}

async function seedLibrary(token) {
  const roots = [];
  const branches = [];
  const leaves = [];
  for (let rootIndex = 0; rootIndex < rootCount; rootIndex += 1) {
    const root = await apiJson(token, "/folders", {
      method: "POST",
      body: JSON.stringify({ name: `Root ${String(rootIndex).padStart(2, "0")}`, tags: ["gate-3"] }),
    });
    roots.push(root);
    for (let branchIndex = 0; branchIndex < branchesPerRoot; branchIndex += 1) {
      const branch = await apiJson(token, "/folders", {
        method: "POST",
        body: JSON.stringify({
          name: `Branch ${String(branchIndex).padStart(2, "0")}`,
          tags: ["gate-3"],
          parent_id: root.id,
        }),
      });
      branches.push(branch);
      for (let leafIndex = 0; leafIndex < leavesPerBranch; leafIndex += 1) {
        const leaf = await apiJson(token, "/folders", {
          method: "POST",
          body: JSON.stringify({
            name: `Leaf ${String(leafIndex).padStart(2, "0")}`,
            tags: ["gate-3"],
            parent_id: branch.id,
          }),
        });
        leaves.push({ ...leaf, path: `${root.name} / ${branch.name} / ${leaf.name}` });
      }
    }
  }

  const uploadOne = async index => {
    const sequence = String(index).padStart(4, "0");
    const leaf = leaves[index % leaves.length];
    const data = new FormData();
    data.set("file", new Blob([`// Gate 3 fixture ${sequence}\ncube([${index % 17 + 1}, 2, 3]);\n`], { type: "text/plain" }), `fixture-${sequence}.scad`);
    data.set("title", `Fixture ${sequence}`);
    data.set("notes", `Deterministic organization benchmark item ${sequence}`);
    data.set("tags", `gate-3,bucket-${index % 12}`);
    data.set("folder_id", leaf.id);
    const response = await fetch(`${apiUrl}/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: data,
    });
    if (!response.ok) throw new Error(`Upload ${sequence} failed: ${response.status} ${await response.text()}`);
    return response.json();
  };

  const concurrency = 4;
  let cursor = 0;
  const workers = Array.from({ length: concurrency }, async () => {
    while (cursor < assetCount) {
      const index = cursor;
      cursor += 1;
      await uploadOne(index);
    }
  });
  await Promise.all(workers);
  return { roots, branches, leaves };
}

async function measureApi(token, path, repetitions = 20) {
  const durations = [];
  let itemCount = null;
  for (let index = 0; index < repetitions; index += 1) {
    const started = performance.now();
    const response = await fetch(`${apiUrl}${path}`, { headers: { Authorization: `Bearer ${token}` } });
    const body = await response.json();
    durations.push(performance.now() - started);
    if (!response.ok) throw new Error(`GET ${path} failed: ${response.status}`);
    itemCount = Array.isArray(body) ? body.length : null;
  }
  return { path, itemCount, latencyMs: summarize(durations) };
}

async function main() {
  const token = await login();
  const seededAt = performance.now();
  const folders = await seedLibrary(token);
  const seedMs = performance.now() - seededAt;
  const targetLeaf = folders.leaves.at(-1);
  const exactSearch = `Fixture ${String(assetCount - 1).padStart(4, "0")}`;
  const api = {
    firstPage: await measureApi(token, "/assets?limit=25&offset=0"),
    exactSearch: await measureApi(token, `/assets?limit=25&offset=0&q=${encodeURIComponent(exactSearch)}`),
    folderPage: await measureApi(token, `/assets?limit=25&offset=0&folder_id=${targetLeaf.id}`),
    folders: await measureApi(token, "/folders"),
  };

  const browser = await chromium.launch({ headless: true, args: ["--enable-precise-memory-info"] });
  activeBrowser = browser;
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.addInitScript(() => {
    window.__mvOrganizationBenchmark = { longTasks: [] };
    try {
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) {
          window.__mvOrganizationBenchmark.longTasks.push(entry.duration);
        }
      }).observe({ type: "longtask", buffered: true });
    } catch {}
  });

  const navigationStarted = performance.now();
  await page.goto(webUrl, { waitUntil: "domcontentloaded" });
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.locator('[title="Double-click to open large preview"]').first().waitFor({ timeout: 30_000 });
  const firstCardsMs = performance.now() - navigationStarted;
  const initialCardCount = await page.locator('[title="Double-click to open large preview"]').count();

  const loadMoreStarted = performance.now();
  await page.getByRole("button", { name: "Load more" }).click();
  await page.waitForFunction(count => document.querySelectorAll('[title="Double-click to open large preview"]').length > count, initialCardCount);
  const loadMoreMs = performance.now() - loadMoreStarted;
  const loadedCardCount = await page.locator('[title="Double-click to open large preview"]').count();

  const checkboxes = page.getByRole("checkbox");
  await checkboxes.nth(0).check();
  await checkboxes.nth(1).check();
  const selectedBeforeFilter = await page.locator('input[type="checkbox"]:checked').count();
  const visibleBulkToolbarBeforeFilter = await page.locator('[role="toolbar"]').count();

  const librarySearch = page.getByPlaceholder("Search title, filename, notes...");
  const searchStarted = performance.now();
  await librarySearch.fill(exactSearch);
  await Promise.all([
    page.waitForResponse(response => response.url().includes("/assets?") && new URL(response.url()).searchParams.get("q") === exactSearch),
    librarySearch.press("Enter"),
  ]);
  await page.locator('[title="Double-click to open large preview"]').first().waitFor();
  const browserSearchMs = performance.now() - searchStarted;
  const browserSearchResultCount = await page.locator('[title="Double-click to open large preview"]').count();
  const selectedAfterFilter = await page.locator('input[type="checkbox"]:checked').count();

  await librarySearch.fill("");
  await Promise.all([
    page.waitForResponse(response => response.url().includes("/assets?") && !new URL(response.url()).searchParams.get("q")),
    librarySearch.press("Enter"),
  ]);
  await page.locator('[title="Double-click to open large preview"]').first().waitFor();

  const folderSearch = page.getByLabel("Search folders");
  const folderSearchStarted = performance.now();
  await folderSearch.fill(targetLeaf.path);
  await page.getByTitle(targetLeaf.path).waitFor();
  const folderSearchMs = performance.now() - folderSearchStarted;
  const visibleFolderRows = await page.locator(".sidebar-tree-row:visible").count();

  const folderOpenStarted = performance.now();
  await page.getByTitle(targetLeaf.path).click();
  await page.waitForFunction(folderId => {
    const selects = [...document.querySelectorAll("select")];
    return selects.some(select => select.value === folderId);
  }, targetLeaf.id);
  const folderOpenMs = performance.now() - folderOpenStarted;
  const folderCardCount = await page.locator('[title="Double-click to open large preview"]').count();

  const browserMetrics = await page.evaluate(() => {
    const longTasks = window.__mvOrganizationBenchmark?.longTasks || [];
    return {
      longTasks: {
        count: longTasks.length,
        totalMs: longTasks.reduce((sum, value) => sum + value, 0),
        maxMs: Math.max(0, ...longTasks),
      },
      heapBytes: performance.memory?.usedJSHeapSize ?? null,
      breadcrumbCount: document.querySelectorAll('nav[aria-label*="breadcrumb" i], [aria-label*="breadcrumb" i]').length,
    };
  });

  await browser.close();
  activeBrowser = null;
  const result = {
    schema: 1,
    capturedAt: new Date().toISOString(),
    corpus: {
      assets: assetCount,
      folders: folders.roots.length + folders.branches.length + folders.leaves.length,
      roots: folders.roots.length,
      branches: folders.branches.length,
      leaves: folders.leaves.length,
      depth: 3,
      seedMs,
    },
    api,
    browser: {
      firstCardsMs,
      initialCardCount,
      loadMoreMs,
      loadedCardCount,
      exactSearchMs: browserSearchMs,
      exactSearchResultCount: browserSearchResultCount,
      selectedBeforeFilter,
      selectedAfterFilter,
      visibleBulkToolbarBeforeFilter,
      folderSearchMs,
      visibleFolderRows,
      folderOpenMs,
      folderCardCount,
      ...browserMetrics,
    },
  };
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(`Organization baseline written to ${outputPath}`);
  console.log(JSON.stringify(result, null, 2));
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(async () => {
  if (activeBrowser) await activeBrowser.close().catch(() => {});
});
