import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { startChromiumProfile, installProfileObservers, probeFolderLocators } from "./chromium-profile.mjs";

async function fixture(event, action) {
  const directory = await mkdtemp(join(tmpdir(), "mv-profile-test-"));
  const session = new EventEmitter();
  const commands = [];
  session.send = async method => {
    commands.push(method);
    if (method === "Profiler.stop") return { profile: { nodes: [] } };
    if (method === "Tracing.end") session.emit("Tracing.tracingComplete", event);
    if (method === "IO.read") return { data: '{"traceEvents":[]}', eof: true };
    return {};
  };
  session.detach = async () => { commands.push("detach"); };
  try {
    const profile = await startChromiumProfile({ context: () => ({ newCDPSession: async () => session }) }, directory);
    await action(profile, directory, commands);
  } finally { await rm(directory, { recursive: true, force: true }); }
}

test("profile completion is single-use and persists complete trace/CPU evidence", async () => {
  await fixture({ stream: "fixture", dataLossOccurred: false }, async (profile, directory, commands) => {
    await Promise.all([profile.finish(), profile.finish()]);
    assert.equal(commands.filter(method => method === "Profiler.stop").length, 1);
    assert.equal(commands.filter(method => method === "detach").length, 1);
    assert.equal(JSON.parse(await readFile(join(directory, "profile-metadata.json"))).status, "complete");
    assert.deepEqual(JSON.parse(await readFile(join(directory, "timeline.json"))), { traceEvents: [] });
  });
});

test("trace data loss cannot be reported as complete", async () => {
  await fixture({ stream: "fixture", dataLossOccurred: true }, async (profile, directory) => {
    await assert.rejects(profile.finish(), /data lost/);
    assert.equal(JSON.parse(await readFile(join(directory, "profile-metadata.json"))).status, "failed");
  });
});

test("missing trace stream fails explicitly and detaches", async () => {
  await fixture({ dataLossOccurred: false }, async (profile, directory, commands) => {
    await assert.rejects(profile.finish(), /Missing trace stream/);
    assert.equal(JSON.parse(await readFile(join(directory, "profile-metadata.json"))).status, "failed");
    assert.equal(commands.at(-1), "detach");
  });
});

test("phase marks retain original state and unavailable frame attribution stays explicit", () => {
  const marks = [];
  const window = {};
  class Observer { static supportedEntryTypes = ["longtask"]; observe() {} }
  const state = { phase: "navigation" };
  runInNewContext(`(${installProfileObservers.toString()})(state)`, {
    state, window, PerformanceObserver: Observer, performance: { now: () => 10, mark: name => marks.push(name) },
  });
  state.phase = "load-more";
  assert.equal(state.phase, "load-more");
  assert.deepEqual(marks, ["mv.phase:navigation", "mv.phase:load-more"]);
  assert.equal(window.__mvProfile.loafAvailable, false);
});

test('locator comparison reads the same label without interaction and rotates sample order', async () => {
  const reads = [], output = [];
  const locator = name => ({ getAttribute: async attribute => {
    assert.equal(attribute, 'aria-label'); reads.push(name); return 'Search folders';
  } });
  const sidebar = { getByLabel: () => locator('label'), getByRole: () => locator('textbox'), locator: () => locator('css') };
  await probeFolderLocators({ locator: () => sidebar, evaluate: async (_fn, value) => { if (Array.isArray(value)) output.push(value); } });
  assert.deepEqual(reads, ['label', 'textbox', 'css', 'css', 'label', 'textbox', 'textbox', 'css', 'label']);
  assert.equal(output[0].length, 9);
  assert(output[0].every(row => row.elapsedMs >= 0));
});

test('locator comparison refuses a mismatched control', async () => {
  const wrong = { getAttribute: async () => 'wrong control' };
  const sidebar = { getByLabel: () => wrong, getByRole: () => wrong, locator: () => wrong };
  await assert.rejects(probeFolderLocators({ locator: () => sidebar, evaluate: async () => {} }), /different control/);
});
