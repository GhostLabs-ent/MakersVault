import { open, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

// Opt-in, private disposable-fixture diagnostics. Never a production/browser bypass.
export async function startChromiumProfile(page, directory) {
  const session = await page.context().newCDPSession(page);
  const scripts = [];
  const contexts = [];
  session.on("Runtime.executionContextCreated", ({ context }) => contexts.push({
    id: context.id, name: context.name, origin: context.origin, auxData: context.auxData,
  }));
  session.on("Debugger.scriptParsed", event => scripts.push({
    scriptId: event.scriptId, url: event.url, hash: event.hash,
    executionContextId: event.executionContextId, startLine: event.startLine,
    startColumn: event.startColumn, endLine: event.endLine, endColumn: event.endColumn,
  }));
  await session.send("Runtime.enable");
  await session.send("Debugger.enable");
  await session.send("Profiler.enable");
  await session.send("Profiler.setSamplingInterval", { interval: 1000 });
  await session.send("Tracing.start", {
    transferMode: "ReturnAsStream", streamFormat: "json",
    traceConfig: { recordMode: "recordUntilFull", traceBufferSizeInKb: 65536,
      includedCategories: ["toplevel", "devtools.timeline", "disabled-by-default-devtools.timeline",
        "disabled-by-default-devtools.timeline.stack", "v8", "v8.execute", "blink.user_timing", "loading"] },
  });
  await session.send("Profiler.start");
  let completion;
  return { finish() {
    if (completion) return completion;
    completion = (async () => {
      const metadata = { schema: 1, diagnosticOnly: true, samplingIntervalUs: 1000,
        status: "in_progress", contexts, scripts };
      try {
        const { profile } = await session.send("Profiler.stop");
        await writeFile(resolve(directory, "renderer.cpuprofile"), JSON.stringify(profile), { flag: "wx", mode: 0o600 });
        let timer;
        const ended = new Promise((accept, reject) => {
          timer = setTimeout(() => reject(new Error("Trace completion timed out")), 10000);
          session.once("Tracing.tracingComplete", accept);
        });
        let event;
        try { await session.send("Tracing.end"); event = await ended; }
        finally { clearTimeout(timer); }
        metadata.dataLossOccurred = event.dataLossOccurred;
        if (!event.stream) throw new Error("Missing trace stream");
        const file = await open(resolve(directory, "timeline.json"), "wx", 0o600);
        let total = 0;
        try {
          while (true) {
            const chunk = await session.send("IO.read", { handle: event.stream, size: 1024 * 1024 });
            const bytes = Buffer.from(chunk.data, chunk.base64Encoded ? "base64" : "utf8");
            total += bytes.length;
            if (total > 128 * 1024 * 1024) throw new Error("Trace exceeds private artifact budget");
            await file.write(bytes);
            if (chunk.eof) break;
          }
        } finally { await file.close(); await session.send("IO.close", { handle: event.stream }); }
        metadata.traceBytes = total;
        if (event.dataLossOccurred !== false) throw new Error("Trace loss status missing or data lost");
        metadata.status = "complete";
      } catch (error) {
        metadata.status = "failed"; metadata.error = error.message;
        throw error;
      } finally {
        await writeFile(resolve(directory, "profile-metadata.json"), JSON.stringify(metadata, null, 2) + "\n", { flag: "wx", mode: 0o600 });
        await session.detach().catch(() => {});
      }
    })();
    return completion;
  } };
}

// Called in the benchmark's existing init script, never injected into app sources.
export function installProfileObservers(state) {
  const output = window.__mvProfile = { phases: [], longTasks: [], frames: [], loafAvailable: false };
  let phase = state.phase;
  const mark = value => {
    const name = "mv.phase:" + value;
    performance.mark(name);
    output.phases.push({ phase: value, atMs: performance.now() });
  };
  Object.defineProperty(state, "phase", { get: () => phase, set: value => { phase = value; mark(value); } });
  mark(phase);
  new PerformanceObserver(list => {
    for (const task of list.getEntries()) output.longTasks.push({ startTime: task.startTime, duration: task.duration });
  }).observe({ type: "longtask", buffered: true });
  if (PerformanceObserver.supportedEntryTypes.includes("long-animation-frame")) {
    output.loafAvailable = true;
    new PerformanceObserver(list => {
      for (const frame of list.getEntries()) output.frames.push({
        startTime: frame.startTime, duration: frame.duration, blockingDuration: frame.blockingDuration,
        renderStart: frame.renderStart, styleAndLayoutStart: frame.styleAndLayoutStart,
        scripts: frame.scripts.map(script => ({ duration: script.duration, executionStart: script.executionStart,
          sourceURL: script.sourceURL, sourceFunctionName: script.sourceFunctionName,
          sourceCharPosition: script.sourceCharPosition, invoker: script.invoker, invokerType: script.invokerType,
          forcedStyleAndLayoutDuration: script.forcedStyleAndLayoutDuration, pauseDuration: script.pauseDuration })),
      });
    }).observe({ type: "long-animation-frame", buffered: true });
  }
}
