// Functions are self-contained for serialization into the measured page.
export function installOrganizationTiming() {
  const state = {
    longTasks: [], longTasksAvailable: false, phases: [{ phase: "navigation", atMs: 0 }],
  };
  let phase = "navigation";
  Object.defineProperty(state, "phase", { configurable: true,
    get: () => phase, set: next => { phase = next; state.phases.push({ phase: next, atMs: performance.now() }); },
  });
  // Publish only after the accessor exists: an earlier profile init script may
  // wrap this assignment and must compose with, not be replaced by, that accessor.
  window.__mvOrganizationBenchmark = state;
  try {
    if (!PerformanceObserver.supportedEntryTypes.includes("longtask")) return;
    const consume = entries => {
      for (const entry of entries) state.longTasks.push({ duration: entry.duration,
        startTime: entry.startTime, legacyPhase: state.phase });
    };
    const observer = new PerformanceObserver(list => consume(list.getEntries()));
    observer.observe({ type: "longtask", buffered: true });
    state.flush = () => consume(observer.takeRecords());
    state.longTasksAvailable = true;
  } catch {}
}

export function readOrganizationTiming() {
  const state = window.__mvOrganizationBenchmark;
  state?.flush?.();
  const available = state?.longTasksAvailable === true;
  const phases = state?.phases || [];
  const excluded = phase => ["navigation", "evidence-screenshot"].includes(phase);
  const entries = (state?.longTasks || []).map(task => {
    const phase = phases.filter(mark => mark.atMs <= task.startTime).at(-1)?.phase || "navigation";
    const overlapsInteraction = phases.some((mark, index) => !excluded(mark.phase)
      && task.startTime < (phases[index + 1]?.atMs ?? Infinity)
      && task.startTime + task.duration > mark.atMs);
    return { ...task, phase, overlapsInteraction };
  });
  const summarize = field => {
    const byPhase = {};
    for (const task of entries) {
      const phase = task[field];
      const bucket = byPhase[phase] ||= { count: 0, totalMs: 0, maxMs: 0 };
      bucket.count++; bucket.totalMs += task.duration; bucket.maxMs = Math.max(bucket.maxMs, task.duration);
    }
    return { count: entries.length, totalMs: entries.reduce((sum, task) => sum + task.duration, 0),
      maxMs: Math.max(0, ...entries.map(task => task.duration)), byPhase };
  };
  const legacyMax = Math.max(0, ...entries.filter(task => !excluded(task.legacyPhase)).map(task => task.duration));
  // Preserve the old guard as well as start-time/cross-phase attribution. A delayed
  // observer or relabelled phase cannot turn a former interaction failure into a pass.
  const guardedMax = Math.max(legacyMax, ...entries.filter(task => !excluded(task.phase) || task.overlapsInteraction).map(task => task.duration));
  return { longTaskAttributionSchema: 2, longTasksAvailable: available,
    longTasks: available ? summarize("phase") : null,
    legacyLongTasks: available ? summarize("legacyPhase") : null,
    legacyMaxInteractionLongTaskMs: available ? legacyMax : null,
    maxInteractionLongTaskMs: available ? guardedMax : null,
    longTaskEntries: available ? entries : null,
  };
}

export function readFolderControlDom(folderIds) {
  const ids = new Set(folderIds);
  const cards = [...document.querySelectorAll('[title="Double-click to open large preview"]')];
  const selects = cards.flatMap(card => [...card.parentElement.querySelectorAll("select")]);
  const folderSelects = selects.filter(select => [...select.options].some(option => ids.has(option.value)));
  return { cards: cards.length, elements: document.querySelectorAll("*").length,
    options: document.querySelectorAll("option").length, cardFolderSelects: folderSelects.length,
    cardFolderOptions: folderSelects.reduce((sum, select) => sum + select.options.length, 0),
    openDialogs: document.querySelectorAll("dialog[open]").length };
}
