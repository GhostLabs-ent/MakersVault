import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";
import { installFirstVisibleCardProbe } from "./first-visible-card.mjs";

function fixture() {
  let now = 0, nodes = [], notify, frame;
  let disconnected = false;
  const events = {};
  const window = { addEventListener: (name, fn) => { events[name] = fn; }, removeEventListener() {} };
  const document = { querySelectorAll: () => nodes,
    addEventListener: (name, fn) => { events[name] = fn; }, removeEventListener() {} };
  const context = { window, document, innerHeight: 900, innerWidth: 1440,
    performance: { now: () => now },
    MutationObserver: class { constructor(fn) { notify = fn; } observe() {} disconnect() { disconnected = true; } },
    requestAnimationFrame: fn => { frame = fn; return 1; }, cancelAnimationFrame: () => { frame = null; },
    getComputedStyle: card => card.style,
  };
  vm.runInNewContext(`(${installFirstVisibleCardProbe.toString()})()`, context);
  return { result: window.__mvFirstVisibleCard, events,
    show: (style = {}, rect = {}) => { nodes = [{ style: { visibility: "visible", display: "block", opacity: "1", ...style },
      getBoundingClientRect: () => ({ width: 200, height: 200, top: 100, left: 100, bottom: 300, right: 300, ...rect }) }]; notify(); },
    tick: time => { now = time; const callback = frame; frame = null; callback?.(); },
    disconnected: () => disconnected,
  };
}

test("missing cards stay unavailable, never a measured zero", () => {
  const f = fixture(); f.tick(100);
  assert.equal(f.result.atMs, null);
});
test("records the browser frame once, independently of the driver's later wait", () => {
  const f = fixture(); f.tick(200); f.events.submit(); f.show(); f.tick(600);
  assert.equal(f.result.atMs, 600); assert.equal(f.result.submittedAtMs, 200);
  f.tick(1000); assert.equal(f.result.atMs, 600); assert.equal(f.disconnected(), true);
});
test("hidden, transparent and offscreen cards cannot satisfy visibility", () => {
  for (const [style, rect] of [[{ visibility: "hidden" }, {}], [{ opacity: "0" }, {}], [{ display: "none" }, {}],
    [{}, { width: 0 }], [{}, { top: 1000, bottom: 1200 }]]) {
    const f = fixture(); f.show(style, rect); f.tick(100); assert.equal(f.result.atMs, null);
    f.show(); f.tick(300); assert.equal(f.result.atMs, 300);
  }
});
test("navigation cleanup cancels pending observation", () => {
  const f = fixture(); f.show(); f.events.pagehide(); f.tick(500);
  assert.equal(f.disconnected(), true); assert.equal(f.result.atMs, null);
});
test("invalid clock values cannot turn into a passing metric", () => {
  const f = fixture(); f.show(); f.tick(NaN); assert.equal(f.result.atMs, null);
});
