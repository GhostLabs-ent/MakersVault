// Read-only reducer for the five named, disposable September 8 profiling runs.
// Run with the exact input directory mounted read-only; never publish raw traces.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const directory = process.argv[2];
if (!/^\/tmp\/makersvault-g13c-profile-0908[a-e]$/.test(directory || '')) {
  throw new Error('Expected one of the five named diagnostic output directories');
}
const caseDirectory = path.join(directory, 'organization-chromium');
const read = name => JSON.parse(fs.readFileSync(path.join(caseDirectory, name)));
const sha256 = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const summary = JSON.parse(fs.readFileSync(path.join(directory, 'summary.json')));
const baseline = read('baseline.json');
if (summary.cases.length !== 1 || summary.cases[0].case !== 'organization-chromium' ||
    summary.diagnostic_profile !== baseline.diagnosticProfile) throw new Error('Run identity mismatch');
const files = ['baseline.json', 'startup-chromium.json', 'stdout.txt', 'stderr.txt',
  'selection-toolbar-chromium.png'];
const result = {
  run: path.basename(directory), summary,
  baseline: { ...baseline, api: Object.fromEntries(Object.entries(baseline.api)
    .map(([name, value]) => [name, { ...value, path: value.path.split('?')[0] }])) },
  analysis: null,
};
if (baseline.diagnosticProfile) {
  files.push('timeline.json', 'renderer.cpuprofile', 'profile-metadata.json', 'profile-observations.json');
  const trace = read('timeline.json').traceEvents;
  const profile = read('renderer.cpuprofile');
  const metadata = read('profile-metadata.json');
  const observations = read('profile-observations.json');
  if (metadata.status !== 'complete' || metadata.dataLossOccurred !== false ||
      profile.samples.length !== profile.timeDeltas.length) throw new Error('Incomplete profile');
  const marks = trace.filter(e => e.name.startsWith('mv.phase:')).sort((a, b) => a.ts - b.ts);
  if (!marks.length || marks.length !== observations.phases.length ||
      marks.some((m, i) => m.name !== 'mv.phase:' + observations.phases[i].phase)) {
    throw new Error('Missing or mismatched phase marks');
  }
  const { pid, tid } = marks[0];
  // Navigation alignment is approximate: performance.now() was read just after mark().
  const navigationOriginUs = marks[0].ts - observations.phases[0].atMs * 1000;
  const main = trace.filter(e => e.pid === pid && e.tid === tid && e.ph === 'X' && e.dur &&
    e.ts >= profile.startTime && e.ts + e.dur <= profile.endTime);
  const phaseAt = time => marks.filter(e => e.ts <= time).at(-1)?.name.slice(9) || 'before-init';
  const scripts = new Map(metadata.scripts.map(s => [s.scriptId, s]));
  const contexts = new Map(metadata.contexts.map(c => [c.id, c]));
  const nodes = new Map(profile.nodes.map(n => [n.id, n]));
  const parents = new Map();
  for (const node of nodes.values()) for (const child of node.children || []) parents.set(child, node.id);
  let now = profile.startTime;
  const samples = profile.samples.map((id, index) => {
    now += profile.timeDeltas[index]; return { id, at: now };
  });
  // These captures contain signed/nonmonotonic deltas. Keep them visible and do not
  // derive CPU-time percentages or duration weights from overlapping sample intervals.
  function sampleWitnesses(start, end) {
    const counts = new Map();
    for (const sample of samples) if (sample.at >= start && sample.at < end) {
      counts.set(sample.id, (counts.get(sample.id) || 0) + 1);
    }
    return [...counts].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([id, count]) => {
      const stack = []; let parent = id;
      while (parent && stack.length < 6) {
        const call = nodes.get(parent).callFrame;
        const context = contexts.get(scripts.get(call.scriptId)?.executionContextId)?.name || '';
        stack.push({ functionName: call.functionName, path: safePath(call.url),
          lineNumberZeroBased: call.lineNumber, columnNumberZeroBased: call.columnNumber,
          context: context.startsWith('__playwright_utility_world') ? 'playwright-utility' : 'main-or-native' });
        parent = parents.get(parent);
      }
      return { sampleCount: count, stack };
    });
  }
  function safePath(url) {
    if (!url) return '';
    const pathname = new URL(url).pathname;
    return /^\/assets\/[\w.-]+\.js$/.test(pathname) ? pathname : '(other script)';
  }
  function eventSummary(events) {
    const map = new Map();
    for (const event of events) {
      const entry = map.get(event.name) || { count: 0, inclusiveMs: 0, maxMs: 0 };
      entry.count++; entry.inclusiveMs += event.dur / 1000;
      entry.maxMs = Math.max(entry.maxMs, event.dur / 1000); map.set(event.name, entry);
    }
    return Object.fromEntries([...map].sort((a, b) => b[1].inclusiveMs - a[1].inclusiveMs).slice(0, 10));
  }
  result.analysis = {
    diagnosticOnly: true, profileStatus: metadata.status, dataLossOccurred: metadata.dataLossOccurred,
    sampling: { requestedIntervalUs: metadata.samplingIntervalUs, sampleCount: profile.samples.length,
      negativeDeltas: profile.timeDeltas.filter(v => v < 0).length,
      minimumDeltaUs: Math.min(...profile.timeDeltas), interpretation: 'Stack witnesses only, not CPU-time weights' },
    phaseAlignment: 'Approximate navigation clock, performance.now read immediately after matching phase mark',
    phases: observations.phases, pageLongTasks: observations.longTasks,
    domSnapshots: observations.domSnapshots || null,
    countersBefore: metadata.countersBefore || null, countersAfter: metadata.countersAfter || null,
    initialResources: observations.resources.filter(e => e.startTime < baseline.browser.firstCardsMs),
    longAnimationFramesAvailable: observations.loafAvailable,
    longAnimationFrames: observations.frames.map(f => ({ ...f, scripts: f.scripts.map(s => ({
      duration: s.duration, executionStart: s.executionStart, path: safePath(s.sourceURL),
      functionName: s.sourceFunctionName, sourceCharPosition: s.sourceCharPosition,
      invokerType: s.invokerType, forcedStyleAndLayoutDuration: s.forcedStyleAndLayoutDuration,
      pauseDuration: s.pauseDuration,
    })) })),
    // >=45 ms retains nearby observations for diagnosis, not a new performance threshold.
    rendererTasksAtLeast45Ms: main.filter(e => e.name === 'RunTask' && e.dur >= 45000).map(task => {
      const nested = main.filter(e => e !== task && e.ts >= task.ts && e.ts + e.dur <= task.ts + task.dur + 5);
      return { phase: phaseAt(task.ts), approximateNavigationStartMs: (task.ts - navigationOriginUs) / 1000,
        wallMs: task.dur / 1000, threadCpuMs: typeof task.tdur === 'number' ? task.tdur / 1000 : null,
        nestedInclusiveEvents: eventSummary(nested),
        calls: nested.filter(e => ['FunctionCall', 'EvaluateScript', 'Layout', 'UpdateLayoutTree'].includes(e.name) && e.dur > 5000)
          .sort((a, b) => b.dur - a.dur).slice(0, 5).map(e => ({ name: e.name, wallMs: e.dur / 1000,
            functionName: e.args?.data?.functionName || '', path: safePath(e.args?.data?.url) })),
        sampleWitnesses: sampleWitnesses(task.ts, task.ts + task.dur),
      };
    }),
  };
}
result.rawArtifactHashes = Object.fromEntries(files.map(name => [name, sha256(path.join(caseDirectory, name))]));
result.rawArtifactHashes['../summary.json'] = sha256(path.join(directory, 'summary.json'));
result.reducerSha256 = sha256(__filename);
console.log(JSON.stringify(result, null, 2));
