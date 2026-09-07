import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { chromium } from "playwright-core";
import { loginSession } from "../session-client.mjs";

const corpusDir = resolve(process.env.MAKERSVAULT_BENCHMARK_CORPUS || "../benchmarks/preview/corpus/generated");
const outputPath = resolve(process.env.MAKERSVAULT_BENCHMARK_OUTPUT || "../benchmarks/preview/.artifacts/baseline.json");
const apiUrl = (process.env.MAKERSVAULT_BENCHMARK_API_URL || "http://localhost:18002").replace(/\/$/, "");
const webUrl = (process.env.MAKERSVAULT_BENCHMARK_WEB_URL || "http://localhost:15175").replace(/\/$/, "");
const username = process.env.MAKERSVAULT_BENCHMARK_USERNAME || "admin";
const password = process.env.MAKERSVAULT_BENCHMARK_PASSWORD || "local-development-only";
const timeoutMs = Number(process.env.MAKERSVAULT_BENCHMARK_TIMEOUT_MS || 60_000);
let activeBrowser = null;

const percentile = (values, ratio) => {
  if (!values.length) return 0;
  const ordered = [...values].sort((a, b) => a - b);
  return ordered[Math.min(ordered.length - 1, Math.floor(ordered.length * ratio))];
};

async function seedCorpus(manifest, session) {
  const uploaded = [];
  for (const fixture of manifest.fixtures) {
    const bytes = await readFile(resolve(corpusDir, fixture.filename));
    const data = new FormData();
    data.set("file", new Blob([bytes], { type: "application/octet-stream" }), fixture.filename);
    data.set("tags", `gate-2,${fixture.category}`);
    const response = await session.fetch("/upload", {
      method: "POST",
      body: data,
    });
    if (!response.ok) throw new Error(`Upload failed for ${fixture.filename}: ${response.status} ${await response.text()}`);
    uploaded.push(await response.json());
  }
  return uploaded;
}

function requestKind(request) {
  const url = new URL(request.url());
  if (/\/file\//.test(url.pathname)) return "file";
  if (/\/thumb\//.test(url.pathname)) return "thumb";
  if (/\/thumbnail-generated$/.test(url.pathname)) return "thumbnail-upload";
  return null;
}

function createNetworkTracker(page) {
  let phase = "cold";
  const phases = { cold: [], warm: [], detail: [], lightburn: [], lightburnWarm: [] };
  const active = { cold: 0, warm: 0, detail: 0, lightburn: 0, lightburnWarm: 0 };
  const maxActive = { cold: 0, warm: 0, detail: 0, lightburn: 0, lightburnWarm: 0 };
  const requestPhase = new WeakMap();
  page.on("request", request => {
    const kind = requestKind(request);
    if (!kind) return;
    const entry = { kind, method: request.method(), url: request.url(), startedAt: Date.now(), status: null };
    phases[phase].push(entry);
    requestPhase.set(request, { phase, entry });
    if (kind === "file") {
      active[phase] += 1;
      maxActive[phase] = Math.max(maxActive[phase], active[phase]);
    }
  });
  const finish = async request => {
    const tracked = requestPhase.get(request);
    if (!tracked) return;
    tracked.entry.finishedAt = Date.now();
    try {
      tracked.entry.status = (await request.response())?.status() ?? null;
    } catch {}
    if (tracked.entry.kind === "file") active[tracked.phase] = Math.max(0, active[tracked.phase] - 1);
  };
  page.on("requestfinished", finish);
  page.on("requestfailed", finish);
  return {
    setPhase(next) { phase = next; },
    data(name) { return { requests: phases[name], maxActiveFileRequests: maxActive[name] }; },
  };
}

async function installBrowserMetrics(page) {
  await page.addInitScript(() => {
    window.__mvBenchmark = { longTasks: [], longTasksAvailable: false, drifts: [], lastTick: performance.now() };
    const interval = 50;
    setInterval(() => {
      const now = performance.now();
      window.__mvBenchmark.drifts.push(Math.max(0, now - window.__mvBenchmark.lastTick - interval));
      window.__mvBenchmark.lastTick = now;
    }, interval);
    try {
      if (!PerformanceObserver.supportedEntryTypes.includes("longtask")) return;
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) {
          window.__mvBenchmark.longTasks.push({ startTime: entry.startTime, duration: entry.duration });
        }
      }).observe({ type: "longtask", buffered: true });
      window.__mvBenchmark.longTasksAvailable = true;
    } catch {}
  });
}

async function sampleResponsiveness(page, stopSignal) {
  const roundTrips = [];
  const heap = [];
  while (!stopSignal.done) {
    const started = performance.now();
    try {
      const sample = await page.evaluate(() => ({
        now: performance.now(),
        heap: performance.memory?.usedJSHeapSize ?? null,
      }));
      roundTrips.push(performance.now() - started);
      if (sample.heap !== null) heap.push(sample.heap);
    } catch {}
    await new Promise(resolveDelay => setTimeout(resolveDelay, 100));
  }
  return { roundTrips, heap };
}

async function scrollLibrary(page) {
  const cards = page.locator('[title="Double-click to open large preview"]');
  for (let index = 0; index < await cards.count(); index += 1) {
    await cards.nth(index).scrollIntoViewIfNeeded();
    await page.waitForTimeout(100);
  }
}

async function waitForExpectedFiles(page, tracker, phase, expectedMinimum) {
  const started = Date.now();
  let stableSince = Date.now();
  let lastCount = -1;
  while (Date.now() - started < timeoutMs) {
    const data = tracker.data(phase);
    const count = data.requests.filter(request => request.kind === "file").length;
    if (count !== lastCount) {
      stableSince = Date.now();
      lastCount = count;
    }
    const activeStates = await page.locator('[data-preview-state="loading"], [data-preview-state="queued"]').count();
    if (count >= expectedMinimum && activeStates === 0 && Date.now() - stableSince >= 2_000) return false;
    await page.waitForTimeout(250);
  }
  return true;
}

async function collectPhase(page, tracker, phase, timing, samples, timedOut) {
  const browser = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    const debug = gl?.getExtension("WEBGL_debug_renderer_info");
    const metrics = window.__mvBenchmark || { longTasks: [], drifts: [] };
    const previewStates = {};
    for (const node of document.querySelectorAll("[data-preview-state]")) {
      const state = node.getAttribute("data-preview-state") || "unknown";
      previewStates[state] = (previewStates[state] || 0) + 1;
    }
    return {
      userAgent: navigator.userAgent,
      hardwareConcurrency: navigator.hardwareConcurrency,
      deviceMemoryGiB: navigator.deviceMemory ?? null,
      webglVendor: debug && gl ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : null,
      webglRenderer: debug && gl ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
      longTasks: metrics.longTasksAvailable ? metrics.longTasks : null,
      drifts: metrics.drifts,
      images: document.querySelectorAll('[title="Double-click to open large preview"] img').length,
      previewStates,
    };
  });
  const network = tracker.data(phase);
  const kinds = kind => network.requests.filter(request => request.kind === kind).length;
  const longDurations = browser.longTasks?.map(task => task.duration);
  return {
    ...timing,
    timedOut,
    requestCounts: {
      files: kinds("file"),
      thumbnails: kinds("thumb"),
      generatedThumbnailUploads: kinds("thumbnail-upload"),
    },
    originalFileRequests: network.requests
      .filter(request => request.kind === "file")
      .map(request => decodeURIComponent(new URL(request.url).pathname)),
    maxActiveFileRequests: network.maxActiveFileRequests,
    responseRoundTripMs: {
      samples: samples.roundTrips.length,
      p95: percentile(samples.roundTrips, 0.95),
      max: Math.max(0, ...samples.roundTrips),
    },
    eventLoopDriftMs: {
      samples: browser.drifts.length,
      p95: percentile(browser.drifts, 0.95),
      max: Math.max(0, ...browser.drifts),
    },
    longTasks: longDurations ? {
      count: longDurations.length,
      totalMs: longDurations.reduce((sum, value) => sum + value, 0),
      maxMs: Math.max(0, ...longDurations),
    } : null,
    heap: {
      samples: samples.heap.length,
      startBytes: samples.heap[0] ?? null,
      endBytes: samples.heap.at(-1) ?? null,
      peakBytes: samples.heap.length ? Math.max(...samples.heap) : null,
    },
    visiblePreviewState: {
      images: browser.images,
      ...browser.previewStates,
    },
    browser: {
      userAgent: browser.userAgent,
      hardwareConcurrency: browser.hardwareConcurrency,
      deviceMemoryGiB: browser.deviceMemoryGiB,
      webglVendor: browser.webglVendor,
      webglRenderer: browser.webglRenderer,
    },
  };
}

async function runPhase(page, tracker, phase, action, expectedMinimum) {
  tracker.setPhase(phase);
  await page.evaluate(() => {
    if (window.__mvBenchmark) {
      window.__mvBenchmark.longTasks = [];
      window.__mvBenchmark.drifts = [];
    }
  });
  const started = performance.now();
  const stopSignal = { done: false };
  const sampler = sampleResponsiveness(page, stopSignal);
  await action();
  const cardsReadyMs = performance.now() - started;
  await scrollLibrary(page);
  const timedOut = await waitForExpectedFiles(page, tracker, phase, expectedMinimum);
  const settledMs = performance.now() - started;
  stopSignal.done = true;
  const samples = await sampler;
  return collectPhase(page, tracker, phase, { cardsReadyMs, settledMs }, samples, timedOut);
}

async function runDetailProbe(page, tracker, asset) {
  tracker.setPhase("detail");
  await page.evaluate(() => {
    if (window.__mvBenchmark) window.__mvBenchmark.longTasks = [];
  });
  const started = performance.now();
  const card = page.locator(`[title="Double-click to open large preview"][data-asset-id="${asset.id}"]`);
  await card.dblclick();
  const viewer = page.locator("[data-detail-preview-state]").first();
  await viewer.waitFor({ timeout: 10_000 });
  await page.waitForFunction(() => {
    const node = document.querySelector("[data-detail-preview-state]");
    return node?.getAttribute("data-detail-preview-state") !== "loading";
  }, undefined, { timeout: 30_000 });
  const state = await viewer.getAttribute("data-detail-preview-state");
  const loadMs = performance.now() - started;
  const longTasks = await page.evaluate(() => window.__mvBenchmark?.longTasksAvailable ? window.__mvBenchmark.longTasks : null);
  const network = tracker.data("detail");
  await page.getByRole("button", { name: "Close" }).first().click();
  return {
    modelName: asset.name,
    state,
    loadMs,
    originalFileRequests: network.requests.filter(request => request.kind === "file").length,
    maxActiveFileRequests: network.maxActiveFileRequests,
    longTasks: longTasks ? {
      count: longTasks.length,
      maxMs: Math.max(0, ...longTasks.map(task => task.duration)),
    } : null,
  };
}

async function revealAssetCard(page, assetId) {
  const card = page.locator(`[title="Double-click to open large preview"][data-asset-id="${assetId}"]`);
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (await card.isVisible()) return card;
    const loadMore = page.getByRole("button", { name: "Load more", exact: true });
    if (await loadMore.isVisible()) {
      await loadMore.click();
    }
    await page.waitForTimeout(100);
  }
  await card.waitFor({ timeout: 1 });
  return card;
}

async function runLightBurnProbe(page, tracker, token) {
  const png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
  const data = new FormData();
  data.set("file", new Blob([`<LightBurnProject><Preview>data:image/png;base64,${png}</Preview></LightBurnProject>`], { type: "application/xml" }), "lightburn-preview-probe.lbrn2");
  data.set("tags", "gate-2,lightburn-probe");
  const upload = await token.fetch("/upload", {
    method: "POST",
    body: data,
  });
  if (!upload.ok) throw new Error(`LightBurn probe upload failed: ${upload.status} ${await upload.text()}`);
  const asset = await upload.json();

  tracker.setPhase("lightburn");
  await page.evaluate(() => {
    if (window.__mvBenchmark) window.__mvBenchmark.longTasks = [];
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  const card = await revealAssetCard(page, asset.id);
  await card.scrollIntoViewIfNeeded();
  await card.locator("img").waitFor({ timeout: 30_000 });
  const persistenceStarted = Date.now();
  let persisted = null;
  while (Date.now() - persistenceStarted < 10_000) {
    const response = await token.fetch("/assets?limit=1000");
    const assets = await response.json();
    persisted = assets.find(item => item.id === asset.id);
    if (persisted?.preview_status === "ready" && persisted?.thumb_url) break;
    await new Promise(resolveDelay => setTimeout(resolveDelay, 100));
  }
  if (!persisted?.thumb_url) throw new Error("LightBurn probe thumbnail did not persist");
  const coldNetwork = tracker.data("lightburn");
  const longTasks = await page.evaluate(() => window.__mvBenchmark?.longTasksAvailable ? window.__mvBenchmark.longTasks : null);

  tracker.setPhase("lightburnWarm");
  await page.reload({ waitUntil: "domcontentloaded" });
  const warmCard = await revealAssetCard(page, asset.id);
  await warmCard.scrollIntoViewIfNeeded();
  await warmCard.locator("img").waitFor({ timeout: 30_000 });
  await page.waitForTimeout(500);
  const warmNetwork = tracker.data("lightburnWarm");
  return {
    state: persisted.preview_status,
    coldOriginalFileRequests: coldNetwork.requests.filter(request => request.kind === "file").length,
    generatedThumbnailUploads: coldNetwork.requests.filter(request => request.kind === "thumbnail-upload").length,
    warmOriginalFileRequests: warmNetwork.requests.filter(request => request.kind === "file").length,
    longTasks: longTasks ? {
      count: longTasks.length,
      maxMs: Math.max(0, ...longTasks.map(task => task.duration)),
    } : null,
  };
}

async function main() {
  const manifest = JSON.parse(await readFile(resolve(corpusDir, "manifest.json"), "utf8"));
  const token = await loginSession(apiUrl, webUrl, username, password);
  const uploaded = await seedCorpus(manifest, token);
  const expectedColdFiles = uploaded.filter(asset => asset.preview_status === "pending" && !asset.thumb_url).length;
  const browser = await chromium.launch({ headless: true, args: ["--enable-precise-memory-info"] });
  activeBrowser = browser;
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const tracker = createNetworkTracker(page);
  const consoleErrors = [];
  const browserDiagnostics = [];
  page.on("console", message => {
    if (["error", "warning"].includes(message.type())) {
      const raw = message.text();
      if (raw.includes("GL Driver Message")) {
        browserDiagnostics.push({ type: message.type(), text: raw });
        return;
      }
      const sanitized = raw.includes("data:image/")
        ? "Generated thumbnail Blob conversion was blocked by the document CSP"
        : raw;
      consoleErrors.push({ type: message.type(), text: sanitized });
    }
  });
  await installBrowserMetrics(page);

  const cold = await runPhase(page, tracker, "cold", async () => {
    await page.goto(webUrl, { waitUntil: "domcontentloaded" });
    await page.locator('input[autocomplete="username"]').fill(username);
    await page.locator('input[autocomplete="current-password"]').fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.locator('[title="Double-click to open large preview"]').first().waitFor({ timeout: 30_000 });
    await page.locator('[title="Double-click to open large preview"]').nth(manifest.fixture_count - 1).waitFor({ timeout: 30_000 });
  }, expectedColdFiles);

  const assetsResponse = await token.fetch("/assets?limit=1000");
  const persistedAssets = await assetsResponse.json();
  const expectedWarmFiles = persistedAssets.filter(
    asset => ["pending", "retry_requested"].includes(asset.preview_status) && !asset.thumb_url,
  ).length;

  const warm = await runPhase(page, tracker, "warm", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator('[title="Double-click to open large preview"]').nth(manifest.fixture_count - 1).waitFor({ timeout: 30_000 });
  }, expectedWarmFiles);

  const detailAsset = uploaded.find(asset => asset.filename.endsWith("01-small-ascii.stl"));
  if (!detailAsset) throw new Error("Detail-view benchmark asset is missing");
  const detail = await runDetailProbe(page, tracker, detailAsset);
  if (detail.state !== "ready") throw new Error(`Interactive detail preview ended in state: ${detail.state}`);
  const lightburn = await runLightBurnProbe(page, tracker, token);

  await browser.close();
  activeBrowser = null;
  const result = {
    schema: 2,
    capturedAt: new Date().toISOString(),
    corpus: {
      fixtureCount: manifest.fixture_count,
      totalBytes: manifest.total_bytes,
      expectedColdFileParses: expectedColdFiles,
      persistedThumbnailsAfterColdRun: persistedAssets.filter(asset => asset.thumb_url).length,
      expectedWarmFileParses: expectedWarmFiles,
    },
    cold,
    warm,
    detail,
    lightburn,
    consoleErrors,
    browserDiagnostics,
  };
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(`Preview baseline written to ${outputPath}`);
  console.log(JSON.stringify({ corpus: result.corpus, cold: result.cold, warm: result.warm, detail: result.detail, lightburn: result.lightburn }, null, 2));
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(async () => {
  if (activeBrowser) {
    await activeBrowser.close().catch(() => {});
    activeBrowser = null;
  }
});
