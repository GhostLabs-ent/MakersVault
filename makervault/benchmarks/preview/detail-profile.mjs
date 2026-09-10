import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { startChromiumProfile, installProfileObservers } from "../organization/chromium-profile.mjs";

// Diagnostic-only observation; forwards the original receiver, arguments, result
// and exceptions. No application code, renderer settings or worker policy changes.
export function installContextProbe() {
  const original = HTMLCanvasElement.prototype.getContext;
  const calls = window.__mvContextCalls = [];
  const wrapper = function (...args) {
    const startTime = performance.now();
    let succeeded = false;
    try {
      const value = Reflect.apply(original, this, args);
      succeeded = Boolean(value);
      return value;
    } finally {
      try {
        if (calls.length < 2000) calls.push({ kind: typeof args[0] === 'string' ? args[0] : '(non-string)', startTime,
          duration: performance.now() - startTime, succeeded,
          attachedToDetailViewer: Boolean(this?.closest?.('[data-detail-preview-state]')) });
      } catch {} // Observation must not replace the native return value/exception.
    }
  };
  HTMLCanvasElement.prototype.getContext = wrapper;
  window.__mvRestoreContextProbe = () => {
    if (HTMLCanvasElement.prototype.getContext === wrapper) HTMLCanvasElement.prototype.getContext = original;
  };
}

export function markDetailPhase(phase) {
  performance.mark('mv.phase:' + phase);
  window.__mvProfile.phases.push({ phase, atMs: performance.now() });
}

export async function startDetailProfile(page, directory) {
  const profile = await startChromiumProfile(page, directory);
  await page.evaluate(installProfileObservers, { phase: 'warm-metric-collection' });
  await page.evaluate(installContextProbe);
  let completion;
  return {
    mark: phase => page.evaluate(markDetailPhase, phase),
    finish() {
      if (completion) return completion;
      completion = (async () => {
        try {
          const observations = await page.evaluate(() => {
            window.__mvRestoreContextProbe?.();
            return { ...window.__mvProfile, contextCalls: window.__mvContextCalls,
              timeOrigin: performance.timeOrigin,
              resources: performance.getEntriesByType('resource').map(entry => ({
                path: new URL(entry.name).pathname, initiatorType: entry.initiatorType,
                startTime: entry.startTime, duration: entry.duration,
                responseStart: entry.responseStart, responseEnd: entry.responseEnd,
                transferSize: entry.transferSize,
              })) };
          });
          await writeFile(resolve(directory, 'profile-observations.json'), JSON.stringify(observations, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
        } finally { await profile.finish(); }
      })();
      return completion;
    },
  };
}
