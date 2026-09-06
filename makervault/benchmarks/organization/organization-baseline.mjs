import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { chromium, firefox, webkit } from "playwright-core";
import { loginSession } from "../session-client.mjs";

const apiUrl = (process.env.MAKERSVAULT_BENCHMARK_API_URL || "http://localhost:18003").replace(/\/$/, "");
const webUrl = (process.env.MAKERSVAULT_BENCHMARK_WEB_URL || "http://localhost:15176").replace(/\/$/, "");
const outputPath = resolve(process.env.MAKERSVAULT_BENCHMARK_OUTPUT || ".artifacts/baseline.json");
const browserName = process.env.MAKERSVAULT_BENCHMARK_BROWSER || "chromium";
const browserType = { chromium, firefox, webkit }[browserName];
if (!browserType) throw new Error(`Unsupported benchmark browser: ${browserName}`);
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
  return loginSession(apiUrl, webUrl, username, password);
}

async function apiJson(token, path, init = {}) {
  const response = await token.fetch(path, {
    ...init,
    headers: {
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers || {}),
    },
  });
  if (!response.ok) throw new Error(`${init.method || "GET"} ${path} failed: ${response.status} ${await response.text()}`);
  return response.json();
}

async function uploadModel(token, { filename, title, notes, tags, folderId, content = "cube([1, 2, 3]);\n" }) {
  const data = new FormData();
  data.set("file", new Blob([content], { type: "text/plain" }), filename);
  if (title) data.set("title", title);
  if (notes) data.set("notes", notes);
  if (tags?.length) data.set("tags", tags.join(","));
  if (folderId) data.set("folder_id", folderId);
  const response = await token.fetch("/upload", {
    method: "POST",
    body: data,
  });
  if (!response.ok) throw new Error(`Upload ${filename} failed: ${response.status} ${await response.text()}`);
  return response.json();
}

async function uploadRelatedFile(token, assetId, filename, content, type) {
  const data = new FormData();
  data.set("file", new Blob([content], { type }), filename);
  const response = await token.fetch(`/asset/${assetId}/files`, {
    method: "POST",
    body: data,
  });
  if (!response.ok) throw new Error(`Related upload ${filename} failed: ${response.status} ${await response.text()}`);
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

  const standardAssetCount = Math.max(0, assetCount - 4);
  const uploadOne = async index => {
    const sequence = String(index).padStart(4, "0");
    const leaf = leaves[index % leaves.length];
    return uploadModel(token, {
      filename: `fixture-${sequence}.scad`,
      title: `Fixture ${sequence}`,
      notes: `Deterministic organization benchmark item ${sequence}`,
      tags: ["gate-3", `bucket-${index % 12}`],
      folderId: leaf.id,
      content: `// Gate 3 fixture ${sequence}\ncube([${index % 17 + 1}, 2, 3]);\n`,
    });
  };

  const concurrency = 4;
  let cursor = 0;
  const workers = Array.from({ length: concurrency }, async () => {
    while (cursor < standardAssetCount) {
      const index = cursor;
      cursor += 1;
      await uploadOne(index);
    }
  });
  await Promise.all(workers);

  const bulkSourceFolder = leaves[0];
  const bulkDestinationFolder = leaves[1];
  const bulkSuccess = await uploadModel(token, {
    filename: "bulk-success.scad",
    title: "Workflow Bulk Success",
    notes: "Gate 3 bulk source",
    tags: ["gate-3", "keep-this-tag"],
    folderId: bulkSourceFolder.id,
  });
  const bulkConflict = await uploadModel(token, {
    filename: "bulk-conflict.scad",
    title: "Workflow Bulk Conflict",
    notes: "Gate 3 bulk source",
    tags: ["gate-3", "keep-that-tag"],
    folderId: bulkSourceFolder.id,
  });
  const destinationConflict = await uploadModel(token, {
    filename: "bulk-conflict.scad",
    title: "Workflow Bulk Conflict",
    notes: "Gate 3 move conflict target",
    tags: ["gate-3"],
    folderId: bulkDestinationFolder.id,
  });
  let bundle = await uploadModel(token, {
    filename: "bundle-proof.scad",
    title: "Workflow Bundle Proof",
    notes: "Gate 3 supporting and prepared visibility proof",
    tags: ["gate-3"],
    folderId: leaves[2].id,
  });
  bundle = await uploadRelatedFile(token, bundle.id, "assembly.pdf", "%PDF-1.4\nGate 3 proof\n", "application/pdf");
  bundle = await uploadRelatedFile(
    token,
    bundle.id,
    "prepared.gcode",
    "; printer_model = P1S\n; filament_type = PLA\n; nozzle_diameter = 0.4\n; layer_height = 0.2\n; total estimated time = 3h 12m\nG1 X10 Y10\n",
    "text/plain",
  );
  return {
    roots,
    branches,
    leaves,
    standardAssetCount,
    special: { bulkSuccess, bulkConflict, destinationConflict, bundle, bulkSourceFolder, bulkDestinationFolder },
  };
}

async function measureApi(token, path, repetitions = 20) {
  const durations = [];
  let itemCount = null;
  for (let index = 0; index < repetitions; index += 1) {
    const started = performance.now();
    const response = await token.fetch(path);
    const body = await response.json();
    durations.push(performance.now() - started);
    if (!response.ok) throw new Error(`GET ${path} failed: ${response.status}`);
    itemCount = Array.isArray(body) ? body.length : null;
  }
  return { path, itemCount, latencyMs: summarize(durations) };
}

async function searchLibrary(page, input, query) {
  await input.fill(query);
  await Promise.all([
    page.waitForResponse(response => response.url().includes("/assets?") && (new URL(response.url()).searchParams.get("q") || "") === query),
    input.press("Enter"),
  ]);
  await page.locator('[title="Double-click to open large preview"]').first().waitFor();
}

async function main() {
  const token = await login();
  const seededAt = performance.now();
  const folders = await seedLibrary(token);
  const seedMs = performance.now() - seededAt;
  const targetLeaf = folders.leaves.at(-1);
  const exactSearch = `Fixture ${String(folders.standardAssetCount - 1).padStart(4, "0")}`;
  const api = {
    firstPage: await measureApi(token, "/assets?limit=25&offset=0"),
    exactSearch: await measureApi(token, `/assets?limit=25&offset=0&q=${encodeURIComponent(exactSearch)}`),
    folderPage: await measureApi(token, `/assets?limit=25&offset=0&folder_id=${targetLeaf.id}`),
    folders: await measureApi(token, "/folders"),
  };

  const launchOptions = browserName === "chromium"
    ? { headless: true, args: ["--enable-precise-memory-info"] }
    : { headless: true };
  const browser = await browserType.launch(launchOptions);
  activeBrowser = browser;
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await mkdir(dirname(outputPath), { recursive: true });
  const dialogMessages = [];
  page.on("dialog", async dialog => {
    dialogMessages.push(dialog.message());
    await dialog.dismiss();
  });
  await page.addInitScript(() => {
    window.__mvOrganizationBenchmark = { longTasks: [], phase: "navigation" };
    try {
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) {
          window.__mvOrganizationBenchmark.longTasks.push({
            duration: entry.duration,
            phase: window.__mvOrganizationBenchmark.phase,
          });
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

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "selection"; });
  const checkboxes = page.getByRole("checkbox");
  await checkboxes.nth(0).check();
  await checkboxes.nth(1).check();

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "load-more"; });
  const loadMoreStarted = performance.now();
  await page.getByRole("button", { name: "Load more" }).click();
  await page.waitForFunction(count => document.querySelectorAll('[title="Double-click to open large preview"]').length > count, initialCardCount);
  const loadMoreMs = performance.now() - loadMoreStarted;
  const loadedCardCount = await page.locator('[title="Double-click to open large preview"]').count();
  const selectedAfterLoadMore = await page.locator('input[type="checkbox"]:checked').count();
  const selectedBeforeFilter = await page.locator('input[type="checkbox"]:checked').count();
  const visibleBulkToolbarBeforeFilter = await page.locator('[role="toolbar"]').count();
  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "evidence-screenshot"; });
  await page.screenshot({ path: resolve(dirname(outputPath), `selection-toolbar-${browserName}.png`) });

  const librarySearch = page.getByPlaceholder("Search title, filename, notes...");
  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "search"; });
  const searchStarted = performance.now();
  await searchLibrary(page, librarySearch, exactSearch);
  const browserSearchMs = performance.now() - searchStarted;
  const browserSearchResultCount = await page.locator('[title="Double-click to open large preview"]').count();
  const selectedAfterFilter = await page.locator('input[type="checkbox"]:checked').count();

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "bundle"; });
  await searchLibrary(page, librarySearch, "Workflow Bundle Proof");
  const preparedSummaryVisible = await page.getByText("Bambu Lab P1S", { exact: false }).isVisible();
  await page.getByRole("button", { name: /Supporting files/ }).click();
  await page.getByRole("link", { name: "assembly.pdf" }).waitFor();
  const supportingDocumentVisible = await page.getByRole("link", { name: "assembly.pdf" }).isVisible();
  const preparedPayloadLinkCount = await page.getByRole("link", { name: "prepared.gcode" }).count();

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "bulk-move"; });
  await searchLibrary(page, librarySearch, "Gate 3 bulk source");
  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "bulk-tags"; });
  await page.getByRole("checkbox", { name: "Select Workflow Bulk Success" }).check();
  await page.getByRole("checkbox", { name: "Select Workflow Bulk Conflict" }).check();
  const bulkToolbar = page.getByRole("toolbar", { name: "Selected models" });
  await bulkToolbar.getByRole("button", { name: "Move" }).click();
  await bulkToolbar.getByLabel(/Destination for/).selectOption(folders.special.bulkDestinationFolder.id);
  await bulkToolbar.getByRole("button", { name: "Move selected" }).click();
  await page.getByText("1 failed and remain selected:", { exact: false }).waitFor();
  const mixedMoveSelectedAfter = await page.locator('input[type="checkbox"]:checked').count();
  const mixedMoveFailureVisible = await page.getByText("Workflow Bulk Conflict:", { exact: false }).isVisible();

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "download"; });
  await page.getByRole("checkbox", { name: "Select Workflow Bulk Success" }).check();
  await bulkToolbar.getByRole("button", { name: "Tags" }).click();
  const bulkTagInput = bulkToolbar.getByPlaceholder("Type tags and press comma/Enter");
  await bulkTagInput.fill("gate-3-added");
  await bulkTagInput.press("Enter");
  await bulkToolbar.getByRole("button", { name: "Apply to 2" }).click();
  await page.getByText("Completed successfully.").waitFor();
  const taggedAssetsResponse = await token.fetch(`/assets?q=${encodeURIComponent("Gate 3 bulk source")}&limit=25`);
  const taggedAssets = await taggedAssetsResponse.json();
  const tagPreservationVerified = taggedAssets.length === 2
    && taggedAssets.every(asset => asset.tags.includes("gate-3-added"))
    && taggedAssets.some(asset => asset.tags.includes("keep-this-tag"))
    && taggedAssets.some(asset => asset.tags.includes("keep-that-tag"));

  await page.getByRole("checkbox", { name: "Select Workflow Bulk Success" }).check();
  await page.getByRole("checkbox", { name: "Select Workflow Bulk Conflict" }).check();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("toolbar", { name: "Selected models" }).getByRole("button", { name: "Download" }).click();
  const selectedDownload = await downloadPromise;
  const selectedDownloadSuggestedFilename = selectedDownload.suggestedFilename();

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "delete"; });
  const dialogsBeforeMultiDelete = dialogMessages.length;
  await page.getByRole("toolbar", { name: "Selected models" }).getByRole("button", { name: "Delete…" }).click();
  const bulkDeleteBlockedVisible = await page.getByText("Permanent bulk delete is unavailable.").isVisible();
  await page.waitForTimeout(100);
  const unexpectedMultiDeleteDialog = dialogMessages.length > dialogsBeforeMultiDelete;

  await page.getByRole("toolbar", { name: "Selected models" }).getByRole("button", { name: "Clear" }).click();
  await page.getByRole("checkbox", { name: "Select Workflow Bulk Success" }).check();
  const dialogsBeforeSingleDelete = dialogMessages.length;
  await page.getByRole("toolbar", { name: "Selected models" }).getByRole("button", { name: "Delete…" }).click();
  await page.waitForTimeout(100);
  const singleDeleteConfirmation = dialogMessages.length > dialogsBeforeSingleDelete ? dialogMessages.at(-1) : "";
  const singleDeleteSelectionAfterCancel = await page.locator('input[type="checkbox"]:checked').count();

  await searchLibrary(page, librarySearch, "");

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "folder-navigation"; });
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
  const parentBranch = folders.branches.find(branch => branch.id === targetLeaf.parent_id);
  if (!parentBranch) throw new Error("Target leaf parent is missing");
  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("button", { name: parentBranch.name, exact: true }).click();
  await page.getByText("No models directly in this folder").waitFor();
  const childFolderButton = page.locator("main").getByRole("button", { name: targetLeaf.name, exact: true });
  const parentBreadcrumbButton = page.getByRole("navigation", { name: "Breadcrumb" })
    .getByRole("button", { name: parentBranch.name, exact: true });
  await childFolderButton.waitFor();
  await parentBreadcrumbButton.waitFor();
  const childFolderEmptyStateVisible = await childFolderButton.isVisible();
  const breadcrumbAncestorNavigationVisible = await parentBreadcrumbButton.isVisible();

  const browserMetrics = await page.evaluate(() => {
    const longTasks = window.__mvOrganizationBenchmark?.longTasks || [];
    const byPhase = {};
    for (const task of longTasks) {
      if (!byPhase[task.phase]) byPhase[task.phase] = { count: 0, totalMs: 0, maxMs: 0 };
      byPhase[task.phase].count += 1;
      byPhase[task.phase].totalMs += task.duration;
      byPhase[task.phase].maxMs = Math.max(byPhase[task.phase].maxMs, task.duration);
    }
    const interactionTasks = longTasks.filter(task => !["navigation", "evidence-screenshot"].includes(task.phase));
    return {
      longTasks: {
        count: longTasks.length,
        totalMs: longTasks.reduce((sum, task) => sum + task.duration, 0),
        maxMs: Math.max(0, ...longTasks.map(task => task.duration)),
        byPhase,
      },
      maxInteractionLongTaskMs: Math.max(0, ...interactionTasks.map(task => task.duration)),
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
      engine: browserName,
      performanceBudgetEnforced: browserName === "chromium",
      firstCardsMs,
      initialCardCount,
      loadMoreMs,
      loadedCardCount,
      selectedAfterLoadMore,
      exactSearchMs: browserSearchMs,
      exactSearchResultCount: browserSearchResultCount,
      selectedBeforeFilter,
      selectedAfterFilter,
      visibleBulkToolbarBeforeFilter,
      preparedSummaryVisible,
      supportingDocumentVisible,
      preparedPayloadLinkCount,
      mixedMoveSelectedAfter,
      mixedMoveFailureVisible,
      tagPreservationVerified,
      selectedDownloadSuggestedFilename,
      bulkDeleteBlockedVisible,
      unexpectedMultiDeleteDialog,
      singleDeleteConfirmation,
      singleDeleteSelectionAfterCancel,
      folderSearchMs,
      visibleFolderRows,
      folderOpenMs,
      folderCardCount,
      childFolderEmptyStateVisible,
      breadcrumbAncestorNavigationVisible,
      ...browserMetrics,
    },
  };
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(`Organization baseline written to ${outputPath}`);
  console.log(JSON.stringify(result, null, 2));

  const failures = [];
  for (const [name, probe] of Object.entries(api)) {
    if (probe.latencyMs.p95 >= 100) failures.push(`${name} API p95 was ${probe.latencyMs.p95.toFixed(1)} ms`);
  }
  if (browserName === "chromium") {
    if (result.browser.firstCardsMs >= 1_000) failures.push(`first cards took ${result.browser.firstCardsMs.toFixed(1)} ms`);
    if (result.browser.loadMoreMs >= 500) failures.push(`load more took ${result.browser.loadMoreMs.toFixed(1)} ms`);
    if (result.browser.exactSearchMs >= 300) failures.push(`exact search took ${result.browser.exactSearchMs.toFixed(1)} ms`);
    if (result.browser.folderSearchMs >= 300) failures.push(`folder search took ${result.browser.folderSearchMs.toFixed(1)} ms`);
    if (result.browser.folderOpenMs >= 300) failures.push(`folder open took ${result.browser.folderOpenMs.toFixed(1)} ms`);
    if (result.browser.maxInteractionLongTaskMs > 50) failures.push(`organization interaction long task reached ${result.browser.maxInteractionLongTaskMs.toFixed(1)} ms`);
  }
  if (result.browser.selectedAfterLoadMore !== 2 || result.browser.selectedBeforeFilter !== 2 || result.browser.selectedAfterFilter !== 0) {
    failures.push("selection was not preserved by load-more and cleared by filter scope");
  }
  if (result.browser.visibleBulkToolbarBeforeFilter !== 1) failures.push("selection toolbar was not visible");
  if (result.browser.breadcrumbCount !== 1 || !result.browser.breadcrumbAncestorNavigationVisible) failures.push("breadcrumb navigation was not available");
  if (!result.browser.childFolderEmptyStateVisible) failures.push("child-folder empty state was not available");
  if (!result.browser.preparedSummaryVisible || !result.browser.supportingDocumentVisible || result.browser.preparedPayloadLinkCount !== 0) {
    failures.push("supporting/prepared file visibility contract failed");
  }
  if (result.browser.mixedMoveSelectedAfter !== 1 || !result.browser.mixedMoveFailureVisible) failures.push("mixed move did not retain and explain the failed ID");
  if (!result.browser.tagPreservationVerified) failures.push("bulk tag mutation replaced unrelated tags");
  if (!result.browser.selectedDownloadSuggestedFilename.endsWith(".zip")) failures.push("selected download did not produce a ZIP");
  if (!result.browser.bulkDeleteBlockedVisible || result.browser.unexpectedMultiDeleteDialog) failures.push("permanent multi-delete was not blocked");
  if (!result.browser.singleDeleteConfirmation.includes("primary and supporting files") || result.browser.singleDeleteSelectionAfterCancel !== 1) {
    failures.push("single-delete confirmation/cancel contract failed");
  }
  if (failures.length) throw new Error(`Organization benchmark failed:\n- ${failures.join("\n- ")}`);
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(async () => {
  if (activeBrowser) await activeBrowser.close().catch(() => {});
});
