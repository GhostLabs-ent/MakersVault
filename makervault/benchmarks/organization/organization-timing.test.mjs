import assert from "node:assert/strict";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { installOrganizationTiming, readOrganizationTiming } from "./organization-timing.mjs";
import { installProfileObservers } from "./chromium-profile.mjs";

function fixture(available = true) {
  let now = 0, callback, pending = [];
  const window = {};
  class Observer {
    static supportedEntryTypes = available ? ["longtask"] : [];
    constructor(fn) { callback = fn; }
    observe() {}
    takeRecords() { const records = pending; pending = []; return records; }
  }
  const context = { window, PerformanceObserver: Observer, performance: { now: () => now, mark() {} } };
  runInNewContext(`(${installOrganizationTiming.toString()})()`, context);
  return { context, phase(value, at) { now = at; window.__mvOrganizationBenchmark.phase = value; },
    deliver(entries) { callback({ getEntries: () => entries }); },
    queue(entries) { pending = entries; },
    read() { return runInNewContext(`(${readOrganizationTiming.toString()})()`, context); } };
}

test("delayed observer uses entry start time and preserves legacy attribution", () => {
  const f = fixture(); f.phase("trash", 100); f.phase("folder-navigation", 220);
  f.deliver([{ startTime: 120, duration: 60 }]);
  const result = f.read();
  assert.equal(result.longTasks.byPhase.trash.maxMs, 60);
  assert.equal(result.legacyLongTasks.byPhase["folder-navigation"].maxMs, 60);
  assert.equal(result.maxInteractionLongTaskMs, 60);
});
test("legacy interaction failure cannot disappear after timestamp correction", () => {
  const f = fixture(); f.phase("search", 200); f.deliver([{ startTime: 10, duration: 60 }]);
  assert.equal(f.read().longTasks.byPhase.navigation.maxMs, 60);
  assert.equal(f.read().maxInteractionLongTaskMs, 60);
});
test("tasks crossing from excluded into interactive phases still count", () => {
  const f = fixture(); f.phase("search", 100); f.phase("evidence-screenshot", 150);
  f.deliver([{ startTime: 80, duration: 90 }]);
  assert.equal(f.read().maxInteractionLongTaskMs, 90);
});
test("unavailable is null, not an invented pass; available empty is zero", () => {
  assert.equal(fixture(false).read().maxInteractionLongTaskMs, null);
  assert.equal(fixture(false).read().longTasks, null);
  assert.equal(fixture().read().maxInteractionLongTaskMs, 0);
});
test("queued records are drained once at the measurement boundary", () => {
  const f = fixture(); f.phase("load-more", 100); f.queue([{ startTime: 110, duration: 55 }]);
  assert.equal(f.read().longTasks.count, 1);
  assert.equal(f.read().longTasks.count, 1);
});
test("opt-in profile observer composes with the benchmark phase history", () => {
  const f = fixture();
  runInNewContext(`(${installProfileObservers.toString()})(window.__mvOrganizationBenchmark)`, f.context);
  f.phase("load-more", 100);
  assert.equal(f.context.window.__mvOrganizationBenchmark.phases.at(-1).phase, "load-more");
  assert.equal(f.context.window.__mvProfile.phases.at(-1).phase, "load-more");
});
test("profile installed before the timing init script also retains both phase histories", () => {
  const f = fixture();
  let state;
  Object.defineProperty(f.context.window, "__mvOrganizationBenchmark", { configurable: true,
    get: () => state, set: next => {
      state = next;
      runInNewContext(`(${installProfileObservers.toString()})(state)`, { ...f.context, state });
    },
  });
  runInNewContext(`(${installOrganizationTiming.toString()})()`, f.context);
  f.phase("load-more", 100);
  assert.equal(state.phases.length, 2);
  assert.equal(f.context.window.__mvProfile.phases.length, 2);
  assert.equal(f.context.window.__mvProfile.phases[0].phase, "navigation");
  assert.equal(f.context.window.__mvProfile.phases[1].phase, "load-more");
});
