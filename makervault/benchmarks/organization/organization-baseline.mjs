import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { chromium, firefox, webkit } from "playwright-core";
import { loginSession } from "../session-client.mjs";
import { installFirstVisibleCardProbe } from "../first-visible-card.mjs";
import { startChromiumProfile, installProfileObservers, recordProfileDom } from "./chromium-profile.mjs";
import { installOrganizationTiming, readOrganizationTiming, readFolderControlDom } from "./organization-timing.mjs";

const apiUrl = (process.env.MAKERSVAULT_BENCHMARK_API_URL || "http://localhost:18003").replace(/\/$/, "");
const webUrl = (process.env.MAKERSVAULT_BENCHMARK_WEB_URL || "http://localhost:15176").replace(/\/$/, "");
const outputPath = resolve(process.env.MAKERSVAULT_BENCHMARK_OUTPUT || ".artifacts/baseline.json");
const browserName = process.env.MAKERSVAULT_BENCHMARK_BROWSER || "chromium";
const browserType = { chromium, firefox, webkit }[browserName];
if (!browserType) throw new Error(`Unsupported benchmark browser: ${browserName}`);
const username = process.env.MAKERSVAULT_BENCHMARK_USERNAME || "admin";
const password = process.env.MAKERSVAULT_BENCHMARK_PASSWORD || "local-development-only";
const assetCount = Number(process.env.MAKERSVAULT_ORGANIZATION_ASSETS || 600);
const rootCount = Number(process.env.MAKERSVAULT_ORGANIZATION_ROOTS || 8);
if (![8, 80].includes(rootCount)) throw new Error("Organization roots must be 8 (baseline) or 80 (folder stress)");
const branchesPerRoot = 4;
const leavesPerBranch = 2;
let activeBrowser = null;
let activeProfile = null;
const profileEnabled = process.env.MAKERSVAULT_CHROMIUM_PROFILE === "1";
if (profileEnabled && browserName !== "chromium") throw new Error("Profiling requires Chromium");

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
  const [response] = await Promise.all([
    page.waitForResponse(response => response.url().includes("/assets?") && (new URL(response.url()).searchParams.get("q") || "") === query),
    input.press("Enter"),
  ]);
  if (!response.ok()) throw new Error(`Library search failed: ${response.status()}`);
  const expected = (await response.json()).map(asset => asset.id).sort();
  await page.waitForFunction(ids => {
    const visibleIds = [...document.querySelectorAll('[title="Double-click to open large preview"]')].map(card => card.dataset.assetId).sort();
    return visibleIds.length === ids.length && visibleIds.every((id, index) => id === ids[index]);
  }, expected);
}

async function main() {
  const token = await login();
  const seededAt = performance.now();
  const folders = await seedLibrary(token);
  const seedMs = performance.now() - seededAt;
  const targetLeaf = folders.leaves[Math.min(folders.standardAssetCount, folders.leaves.length) - 1];
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
  const mainRegion = page.locator("main");
  const sidebar = page.locator("aside");
  const cards = mainRegion.locator('[title="Double-click to open large preview"]');
  const folderIds = [...folders.roots, ...folders.branches, ...folders.leaves].map(folder => folder.id);
  await page.addInitScript(installFirstVisibleCardProbe);
  await mkdir(dirname(outputPath), { recursive: true });
  if (profileEnabled) {
    activeProfile = await startChromiumProfile(page, dirname(outputPath));
  }
  const dialogMessages = [];
  let acceptDialog = null;
  page.on("dialog", async dialog => {
    dialogMessages.push(dialog.message());
    const accept = dialog.message() === acceptDialog;
    acceptDialog = null;
    if (accept) await dialog.accept();
    else await dialog.dismiss();
  });
  await page.addInitScript(installOrganizationTiming);

  if (profileEnabled) {
    await page.addInitScript({ content: `(() => {
      const install = ${installProfileObservers.toString()};
      let value = window.__mvOrganizationBenchmark;
      Object.defineProperty(window, "__mvOrganizationBenchmark", {
        configurable: true, get: () => value,
        set: next => { value = next; install(next); },
      });
      if (value) install(value);
    })();` });
  }

  const navigationStarted = performance.now();
  await page.goto(webUrl, { waitUntil: "domcontentloaded" });
  const documentLoaded = performance.now();
  await page.locator('input[autocomplete="username"]').waitFor();
  const loginFormVisible = performance.now();
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  const formFilled = performance.now();
  await page.locator("form").getByRole("button", { name: "Sign in" }).click();
  const signInClicked = performance.now();
  await cards.first().waitFor({ timeout: 30_000 });
  const firstCardsWaitReturnMs = performance.now() - navigationStarted;
  await page.waitForFunction(() => Number.isFinite(window.__mvFirstVisibleCard?.atMs), undefined, { timeout: 30_000 });
  const firstVisibleCard = await page.evaluate(() => window.__mvFirstVisibleCard);
  const firstCardsMs = firstVisibleCard.atMs;
  const startupBreakdown = {
    documentMs: documentLoaded - navigationStarted,
    formWaitMs: loginFormVisible - documentLoaded,
    formFillMs: formFilled - loginFormVisible,
    signInClickMs: signInClicked - formFilled,
    afterClickToCardsMs: performance.now() - signInClicked,
    includesLoginAutomation: true,
  };
  // Preserve startup diagnostics even if a later workflow assertion aborts the report.
  await writeFile(resolve(dirname(outputPath), `startup-${browserName}.json`),
    `${JSON.stringify({ firstCardsMs, firstCardsWaitReturnMs, firstVisibleCard, startupBreakdown }, null, 2)}\n`, "utf8");
  const initialCardCount = await cards.count();
  const initialFolderControls = await page.evaluate(readFolderControlDom, folderIds);
  if (profileEnabled) await recordProfileDom(page, "initial-cards");

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "selection"; });
  await cards.nth(0).locator("..").getByRole("checkbox").check();
  await cards.nth(1).locator("..").getByRole("checkbox").check();

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "load-more"; });
  const loadMoreStarted = performance.now();
  await mainRegion.getByRole("button", { name: "Load more" }).click();
  await page.waitForFunction(count => document.querySelectorAll('[title="Double-click to open large preview"]').length > count, initialCardCount);
  const loadMoreMs = performance.now() - loadMoreStarted;
  const loadedCardCount = await cards.count();
  const loadedFolderControls = await page.evaluate(readFolderControlDom, folderIds);
  if (profileEnabled) await recordProfileDom(page, "after-load-more");
  const selectedAfterLoadMore = await page.locator('input[type="checkbox"]:checked').count();
  const selectedBeforeFilter = await page.locator('input[type="checkbox"]:checked').count();
  const visibleBulkToolbarBeforeFilter = await page.locator('[role="toolbar"]').count();
  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "evidence-screenshot"; });
  await page.screenshot({ path: resolve(dirname(outputPath), `selection-toolbar-${browserName}.png`) });

  const librarySearch = mainRegion.getByPlaceholder("Search title, filename, notes...");
  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "search"; });
  const searchStarted = performance.now();
  await searchLibrary(page, librarySearch, exactSearch);
  const browserSearchMs = performance.now() - searchStarted;
  const browserSearchResultCount = await cards.count();
  const selectedAfterFilter = await page.locator('input[type="checkbox"]:checked').count();

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "bundle"; });
  await searchLibrary(page, librarySearch, "Workflow Bundle Proof");
  const bundleCard = cards.first().locator("..");
  const preparedSummaryVisible = await bundleCard.getByText("Bambu Lab P1S", { exact: false }).isVisible();
  await bundleCard.getByRole("button", { name: /Supporting files/ }).click();
  await bundleCard.getByRole("link", { name: "assembly.pdf" }).waitFor();
  const supportingDocumentVisible = await bundleCard.getByRole("link", { name: "assembly.pdf" }).isVisible();
  const preparedPayloadLinkCount = await mainRegion.getByRole("link", { name: "prepared.gcode" }).count();

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "bulk-move"; });
  await searchLibrary(page, librarySearch, "Gate 3 bulk source");
  const successCard = mainRegion.locator(`[data-asset-id="${folders.special.bulkSuccess.id}"]`).locator("..");
  const conflictCard = mainRegion.locator(`[data-asset-id="${folders.special.bulkConflict.id}"]`).locator("..");
  await successCard.getByRole("checkbox", { name: "Select Workflow Bulk Success" }).check();
  await conflictCard.getByRole("checkbox", { name: "Select Workflow Bulk Conflict" }).check();
  const bulkToolbar = mainRegion.getByRole("toolbar", { name: "Selected models" });
  await bulkToolbar.getByRole("button", { name: "Move" }).click();
  await bulkToolbar.getByLabel(/Destination for/).selectOption(folders.special.bulkDestinationFolder.id);
  await bulkToolbar.getByRole("button", { name: "Move selected" }).click();
  await page.getByText("1 failed and remain selected:", { exact: false }).waitFor();
  const mixedMoveSelectedAfter = await page.locator('input[type="checkbox"]:checked').count();
  const mixedMoveFailureVisible = await page.getByText("Workflow Bulk Conflict:", { exact: false }).isVisible();

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "bulk-tags"; });
  await successCard.getByRole("checkbox", { name: "Select Workflow Bulk Success" }).check();
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

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "download"; });
  await successCard.getByRole("checkbox", { name: "Select Workflow Bulk Success" }).check();
  await conflictCard.getByRole("checkbox", { name: "Select Workflow Bulk Conflict" }).check();
  const downloadPromise = page.waitForEvent("download");
  await bulkToolbar.getByRole("button", { name: "Download" }).click();
  const selectedDownload = await downloadPromise;
  const selectedDownloadSuggestedFilename = selectedDownload.suggestedFilename();

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "trash"; });
  async function waitForTrash(ids) {
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      const items = await apiJson(token, "/trash");
      if (items.length === ids.length && ids.every(id => items.some(item => item.id === id))) return;
      await new Promise(resolveWait => setTimeout(resolveWait, 100));
    }
    throw new Error("Trash IDs did not match the confirmed selection");
  }
  async function restoreInUi(assets) {
    await sidebar.getByRole("button", { name: "Trash", exact: true }).click();
    await mainRegion.getByRole("heading", { name: "Trash", exact: true }).waitFor();
    for (const asset of assets) {
      const row = mainRegion.getByTitle(asset.name, { exact: true }).locator("..").locator("..");
      const [response] = await Promise.all([
        page.waitForResponse(response => response.url().endsWith(`/trash/${asset.id}/restore`) && response.request().method() === "POST"),
        row.getByRole("button", { name: "Restore", exact: true }).click(),
      ]);
      if (response.status() !== 200) throw new Error("UI restore failed");
      const restored = await response.json();
      if (restored.id !== asset.id || restored.folder_id !== asset.folder_id || restored.name !== asset.name) {
        throw new Error("Restore changed model identity or folder");
      }
      const bytes = await token.fetch(restored.url);
      if (!bytes.ok || await bytes.text() !== "cube([1, 2, 3]);\n") throw new Error("Restore changed primary bytes");
    }
    await waitForTrash([]);
    await sidebar.getByRole("button", { name: /All files/ }).click();
    await searchLibrary(page, librarySearch, "Gate 3 bulk source");
  }

  await bulkToolbar.getByRole("button", { name: "Delete…" }).click();
  const bulkTrashRecoverableVisible = await page.getByText("Every version and supporting file remains recoverable.").isVisible();
  await bulkToolbar.getByRole("button", { name: "Cancel", exact: true }).click();
  const bulkTrashSelectionAfterPanelCancel = await page.locator('input[type="checkbox"]:checked').count();
  await waitForTrash([]);

  await bulkToolbar.getByRole("button", { name: "Clear" }).click();
  await successCard.getByRole("checkbox", { name: "Select Workflow Bulk Success" }).check();
  const dialogsBeforeSingleDelete = dialogMessages.length;
  await bulkToolbar.getByRole("button", { name: "Delete…" }).click();
  await page.waitForTimeout(100);
  const singleDeleteConfirmation = dialogMessages.length > dialogsBeforeSingleDelete ? dialogMessages.at(-1) : "";
  const singleDeleteSelectionAfterCancel = await page.locator('input[type="checkbox"]:checked').count();
  await waitForTrash([]);
  acceptDialog = 'Move "Workflow Bulk Success" to Trash? You can restore it later.';
  await bulkToolbar.getByRole("button", { name: "Delete…" }).click();
  await waitForTrash([folders.special.bulkSuccess.id]);
  await restoreInUi(taggedAssets.filter(asset => asset.id === folders.special.bulkSuccess.id));
  const singleTrashRestoreVerified = true;

  await successCard.getByRole("checkbox", { name: "Select Workflow Bulk Success" }).check();
  await conflictCard.getByRole("checkbox", { name: "Select Workflow Bulk Conflict" }).check();
  await bulkToolbar.getByRole("button", { name: "Delete…" }).click();
  await bulkToolbar.getByRole("button", { name: "Move to Trash", exact: true }).click();
  await waitForTrash([]); // Confirmation is dismissed unless explicitly armed.
  const bulkTrashSelectionAfterDialogCancel = await page.locator('input[type="checkbox"]:checked').count();
  acceptDialog = "Move 2 selected models to Trash? You can restore them later.";
  await bulkToolbar.getByRole("button", { name: "Move to Trash", exact: true }).click();
  await waitForTrash(taggedAssets.map(asset => asset.id));
  await restoreInUi(taggedAssets);
  const bulkTrashRestoreVerified = true;

  await searchLibrary(page, librarySearch, "");

  await page.evaluate(() => { window.__mvOrganizationBenchmark.phase = "folder-navigation"; });
  const folderSearch = sidebar.getByLabel("Search folders");
  const folderSearchStarted = performance.now();
  await folderSearch.fill(targetLeaf.path);
  await sidebar.getByTitle(targetLeaf.path).waitFor();
  const folderSearchMs = performance.now() - folderSearchStarted;
  const visibleFolderRows = await page.locator(".sidebar-tree-row:visible").count();

  const folderOpenStarted = performance.now();
  await sidebar.getByTitle(targetLeaf.path).click();
  await page.waitForFunction(({ folderId, count }) => {
    const cards = [...document.querySelectorAll('[title="Double-click to open large preview"]')];
    return cards.length === count && cards.every(card => card.parentElement.querySelector("[data-folder-id]")?.getAttribute("data-folder-id") === folderId);
  }, { folderId: targetLeaf.id, count: api.folderPage.itemCount });
  const folderOpenMs = performance.now() - folderOpenStarted;
  const folderCardCount = await cards.count();
  const folderViewControls = await page.evaluate(readFolderControlDom, folderIds);
  if (profileEnabled) await recordProfileDom(page, "folder-open");
  const parentBranch = folders.branches.find(branch => branch.id === targetLeaf.parent_id);
  if (!parentBranch) throw new Error("Target leaf parent is missing");
  await mainRegion.getByRole("navigation", { name: "Breadcrumb" }).getByRole("button", { name: parentBranch.name, exact: true }).click();
  await page.getByText("No models directly in this folder").waitFor();
  const childFolderButton = page.locator("main").getByRole("button", { name: targetLeaf.name, exact: true });
  const parentBreadcrumbButton = mainRegion.getByRole("navigation", { name: "Breadcrumb" })
    .getByRole("button", { name: parentBranch.name, exact: true });
  await childFolderButton.waitFor();
  await parentBreadcrumbButton.waitFor();
  const childFolderEmptyStateVisible = await childFolderButton.isVisible();
  const breadcrumbAncestorNavigationVisible = await parentBreadcrumbButton.isVisible();

  const timingMetrics = await page.evaluate(readOrganizationTiming);
  const browserMetrics = await page.evaluate(() => {
    return {
      userAgent: navigator.userAgent,
      heapBytes: performance.memory?.usedJSHeapSize ?? null,
      breadcrumbCount: document.querySelectorAll('nav[aria-label*="breadcrumb" i], [aria-label*="breadcrumb" i]').length,
    };
  });

  if (activeProfile) {
    const observations = await page.evaluate(() => ({ ...window.__mvProfile,
      timeOrigin: performance.timeOrigin,
      resources: performance.getEntriesByType("resource").map(entry => ({
        path: new URL(entry.name).pathname, initiatorType: entry.initiatorType,
        startTime: entry.startTime, duration: entry.duration, responseStart: entry.responseStart,
        responseEnd: entry.responseEnd, transferSize: entry.transferSize,
      })),
      dom: { elements: document.querySelectorAll("*").length,
        options: document.querySelectorAll("option").length },
    }));
    await writeFile(resolve(dirname(outputPath), "profile-observations.json"), JSON.stringify(observations, null, 2) + "\n", { flag: "wx", mode: 0o600 });
    await activeProfile.finish();
    activeProfile = null;
  }
  await browser.close();
  activeBrowser = null;
  const result = {
    schema: 4,
    diagnosticProfile: profileEnabled,
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
      firstCardsWaitReturnMs,
      firstVisibleCard,
      startupBreakdown,
      initialCardCount,
      loadMoreMs,
      loadedCardCount,
      folderControls: { initial: initialFolderControls, loaded: loadedFolderControls, folder: folderViewControls },
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
      bulkTrashRecoverableVisible,
      bulkTrashSelectionAfterPanelCancel,
      bulkTrashSelectionAfterDialogCancel,
      singleTrashRestoreVerified,
      bulkTrashRestoreVerified,
      singleDeleteConfirmation,
      singleDeleteSelectionAfterCancel,
      folderSearchMs,
      visibleFolderRows,
      folderOpenMs,
      folderCardCount,
      childFolderEmptyStateVisible,
      breadcrumbAncestorNavigationVisible,
      ...browserMetrics,
      ...timingMetrics,
    },
  };
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(`Organization baseline written to ${outputPath}`);
  console.log(JSON.stringify(result, null, 2));

  const failures = [];
  for (const snapshot of Object.values(result.browser.folderControls)) {
    if (snapshot.cardFolderOptions !== 0 || snapshot.openDialogs !== 0) failures.push("Closed cards eagerly mounted folder destinations");
  }
  for (const [name, probe] of Object.entries(api)) {
    if (probe.latencyMs.p95 >= 100) failures.push(`${name} API p95 was ${probe.latencyMs.p95.toFixed(1)} ms`);
  }
  if (browserName === "chromium") {
    if (!Number.isFinite(result.browser.firstCardsMs)) failures.push("First-visible card timestamp unavailable");
    else if (result.browser.firstCardsMs >= 1_000) failures.push(`first cards took ${result.browser.firstCardsMs.toFixed(1)} ms`);
    if (result.browser.loadMoreMs >= 500) failures.push(`load more took ${result.browser.loadMoreMs.toFixed(1)} ms`);
    if (result.browser.exactSearchMs >= 300) failures.push(`exact search took ${result.browser.exactSearchMs.toFixed(1)} ms`);
    if (result.browser.folderSearchMs >= 300) failures.push(`folder search took ${result.browser.folderSearchMs.toFixed(1)} ms`);
    if (result.browser.folderOpenMs >= 300) failures.push(`folder open took ${result.browser.folderOpenMs.toFixed(1)} ms`);
    if (!result.browser.longTasksAvailable) failures.push("Long Tasks API unavailable; Chromium timing cannot be qualified");
    else if (result.browser.maxInteractionLongTaskMs > 50) failures.push(`organization interaction long task reached ${result.browser.maxInteractionLongTaskMs.toFixed(1)} ms`);
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
  if (!result.browser.bulkTrashRecoverableVisible || result.browser.bulkTrashSelectionAfterPanelCancel !== 2 || result.browser.bulkTrashSelectionAfterDialogCancel !== 2) failures.push("bulk Trash cancellation/recoverability contract failed");
  if (!result.browser.singleDeleteConfirmation.includes("You can restore it later") || result.browser.singleDeleteSelectionAfterCancel !== 1) {
    failures.push("single-Trash confirmation/cancel contract failed");
  }
  if (!result.browser.singleTrashRestoreVerified || !result.browser.bulkTrashRestoreVerified) failures.push("Trash/restore identity and byte contract failed");
  if (failures.length) throw new Error(`Organization benchmark failed:\n- ${failures.join("\n- ")}`);
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(async () => {
  if (activeProfile) await activeProfile.finish().catch(error => console.error("Profile collection failed:", error.message));
  if (activeBrowser) await activeBrowser.close().catch(() => {});
});
