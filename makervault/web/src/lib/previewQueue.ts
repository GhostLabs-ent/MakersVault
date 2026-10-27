/**
 * Bounded, single-flight scheduler for preview generation work.
 *
 * Honest cancellation boundary: preview work is mostly not preemptible.
 * `occt-import-js` WASM parsing (`ReadStepFile`), `THREE.WebGLRenderer.render`,
 * `canvas.toDataURL()` and the three.js `STLLoader`/`OBJLoader` XHR loads
 * cannot be interrupted once they have been entered. Aborting a job therefore
 * never stops a call that is already running inside one of those.
 *
 * What aborting a job actually does:
 *  - (a) refuses to start queued jobs whose owner (card) is gone;
 *  - (b) aborts at await boundaries: the `fetch()` for STEP/3MF downloads and a
 *        job waiting in this queue observe the abort signal where the platform
 *        allows. The preview-renderer lock in ModelViewer does not: it is a
 *        plain promise chain whose wait is not interruptible, so the signal is
 *        only checked immediately before and after acquisition — a cancelled
 *        waiter still acquires the lock, then releases a freshly built
 *        renderer without rendering anything;
 *  - (c) discards results whose owner unmounted — they are never delivered;
 *  - (d) refuses new submissions once the per-session time budget is spent.
 *        Jobs already queued or running when the budget trips are not
 *        retro-denied;
 *  - (e) drops new submissions while `maxPending` slots are full (the
 *        `dropped` counter). For a card that is still visible this is not
 *        terminal: ModelSnapshot retries a bounded number of times
 *        (`PREVIEW_MAX_ATTEMPTS`), then shows an error state.
 *
 * Because a non-preemptible call cannot be stopped, the single active slot is
 * held after its caller aborts or times out, until the underlying `run()`
 * promise actually settles. Only then does the next queued job start, so at
 * most one preview job is ever doing real work.
 */

export const PREVIEW_SETTLE_MS = 120;
export const PREVIEW_MAX_PENDING = 8;
export const PREVIEW_JOB_BUDGET_MS = 6000;
export const PREVIEW_SESSION_BUDGET_MS = 30000;
export const PREVIEW_RETRY_MS = 400;
export const PREVIEW_MAX_ATTEMPTS = 3;

export type PreviewQueueStats = {
  active: number;
  queued: number;
  started: number;
  completed: number;
  aborted: number;
  timedOut: number;
  dropped: number;
  budgetDenied: number;
  spentMs: number;
  budgetMs: number;
  exhausted: boolean;
};

export type PreviewQueueConfig = {
  maxPending: number;
  sessionBudgetMs: number;
  jobBudgetMs: number;
};

export type PreviewJob<T> = {
  signal: AbortSignal;
  run: (signal: AbortSignal) => Promise<T>;
};

type Counters = {
  started: number;
  completed: number;
  aborted: number;
  timedOut: number;
  dropped: number;
  budgetDenied: number;
  spentMs: number;
};

type QueueEntry = {
  signal: AbortSignal;
  run: (signal: AbortSignal) => Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (error: unknown) => void;
  onAbort: () => void;
  settled: boolean;
  started: boolean;
};

function createCounters(): Counters {
  return {
    started: 0,
    completed: 0,
    aborted: 0,
    timedOut: 0,
    dropped: 0,
    budgetDenied: 0,
    spentMs: 0,
  };
}

function now(): number {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}

export class PreviewQueue {
  private readonly config: PreviewQueueConfig;
  private readonly pending: QueueEntry[] = [];
  private active: QueueEntry | null = null;
  private counters: Counters = createCounters();
  private exhaustionLogged = false;

  constructor(config: Partial<PreviewQueueConfig> = {}) {
    this.config = {
      maxPending: config.maxPending ?? PREVIEW_MAX_PENDING,
      sessionBudgetMs: config.sessionBudgetMs ?? PREVIEW_SESSION_BUDGET_MS,
      jobBudgetMs: config.jobBudgetMs ?? PREVIEW_JOB_BUDGET_MS,
    };
  }

  /**
   * Queue one preview job. Resolves with `null` when no result will ever be
   * delivered (the owner aborted, the queue dropped the job, the session
   * budget is spent, or the job exceeded its wall-clock budget). Rejects only
   * with a genuine failure from `run()`.
   */
  enqueue<T>(job: PreviewJob<T>): Promise<T | null> {
    return new Promise<T | null>((resolve, reject) => {
      if (job.signal.aborted) {
        this.counters.aborted += 1;
        this.emitCounter();
        resolve(null);
        return;
      }
      if (this.isExhausted()) {
        this.denyForBudget();
        resolve(null);
        return;
      }
      if (this.pending.length >= this.config.maxPending) {
        // Defence in depth: cards normally abort instead of piling up.
        this.counters.dropped += 1;
        this.emitCounter();
        resolve(null);
        return;
      }
      const entry: QueueEntry = {
        signal: job.signal,
        run: job.run,
        resolve: value => resolve(value as T | null),
        reject: error => reject(error),
        onAbort: () => undefined,
        settled: false,
        started: false,
      };
      entry.onAbort = () => this.handleAbort(entry);
      entry.signal.addEventListener("abort", entry.onAbort, { once: true });
      this.pending.push(entry);
      this.pump();
    });
  }

  getStats(): PreviewQueueStats {
    return {
      active: this.active ? 1 : 0,
      queued: this.pending.length,
      started: this.counters.started,
      completed: this.counters.completed,
      aborted: this.counters.aborted,
      timedOut: this.counters.timedOut,
      dropped: this.counters.dropped,
      budgetDenied: this.counters.budgetDenied,
      spentMs: this.counters.spentMs,
      budgetMs: this.config.sessionBudgetMs,
      exhausted: this.isExhausted(),
    };
  }

  /** Clears queued jobs and counters. An in-flight run is never preemptible. */
  reset(): void {
    const pending = this.pending.splice(0, this.pending.length);
    for (const entry of pending) {
      entry.settled = true;
      entry.signal.removeEventListener("abort", entry.onAbort);
      entry.resolve(null);
    }
    this.counters = createCounters();
    this.exhaustionLogged = false;
  }

  private isExhausted(): boolean {
    return this.counters.spentMs >= this.config.sessionBudgetMs;
  }

  private denyForBudget(): void {
    this.counters.budgetDenied += 1;
    if (this.exhaustionLogged) return;
    this.exhaustionLogged = true;
    console.warn(
      `[preview] session budget exhausted after ${Math.round(this.counters.spentMs)}ms/${this.config.sessionBudgetMs}ms; further previews are skipped`,
    );
  }

  private handleAbort(entry: QueueEntry): void {
    if (entry.settled) return;
    this.counters.aborted += 1;
    if (!entry.started) {
      const index = this.pending.indexOf(entry);
      if (index !== -1) this.pending.splice(index, 1);
    }
    entry.settled = true;
    entry.signal.removeEventListener("abort", entry.onAbort);
    entry.resolve(null);
    // An active run keeps the slot until it unwinds; its settle emits the counter.
    if (!entry.started) this.emitCounter();
  }

  private pump(): void {
    if (this.active) return;
    while (this.pending.length > 0) {
      const entry = this.pending.shift()!;
      if (entry.settled) continue;
      void this.runEntry(entry);
      return;
    }
  }

  private async runEntry(entry: QueueEntry): Promise<void> {
    this.active = entry;
    entry.started = true;
    this.counters.started += 1;

    const controller = new AbortController();
    const forwardAbort = () => controller.abort();
    const startedAt = now();
    const timer = setTimeout(() => {
      // The owner may have aborted already; then there is nothing left to time out.
      if (entry.settled) return;
      this.counters.timedOut += 1;
      controller.abort();
      entry.settled = true;
      entry.signal.removeEventListener("abort", entry.onAbort);
      entry.resolve(null);
    }, this.config.jobBudgetMs);

    if (entry.signal.aborted) {
      controller.abort();
    } else {
      entry.signal.addEventListener("abort", forwardAbort, { once: true });
    }

    try {
      const value = await entry.run(controller.signal);
      if (!entry.settled) {
        entry.settled = true;
        entry.resolve(value);
        this.counters.completed += 1;
      }
    } catch (error) {
      if (!entry.settled) {
        entry.settled = true;
        entry.reject(error);
      }
    } finally {
      clearTimeout(timer);
      entry.signal.removeEventListener("abort", forwardAbort);
      entry.signal.removeEventListener("abort", entry.onAbort);
      this.counters.spentMs += Math.max(0, now() - startedAt);
      if (this.active === entry) this.active = null;
      this.emitCounter();
      this.pump();
    }
  }

  private emitCounter(): void {
    const stats = this.getStats();
    console.info(
      `[preview] started=${stats.started} done=${stats.completed} aborted=${stats.aborted} timedOut=${stats.timedOut} dropped=${stats.dropped} denied=${stats.budgetDenied} spent=${Math.round(stats.spentMs)}ms/${stats.budgetMs}ms queued=${stats.queued}`,
    );
  }
}

export const previewQueue = new PreviewQueue();
