import { uploadAsset } from "./api";

export type UploadTaskStatus = "queued" | "uploading" | "done" | "failed" | "cancelled";

/** Structurally identical to `uploadTree.UploadEntry` so this module stays a leaf. */
export type UploadJobEntry = { file: File; relativePath: string };

export type UploadJob = { entry: UploadJobEntry; folderId: string | null };

export type UploadProgress = { loaded: number; total: number };

export type UploadTransport = (
  job: UploadJob,
  ctx: { onProgress: (progress: UploadProgress) => void; signal: AbortSignal },
) => Promise<unknown>;

export type UploadTask = {
  id: number;
  name: string;
  size: number;
  loaded: number;
  status: UploadTaskStatus;
  attempts: number;
  error?: string;
  /** Retained only while a failed row can still be retried. */
  job?: UploadJob;
  transport?: UploadTransport;
};

export type UploadFailure = { entry: UploadJobEntry; message: string; job: UploadJob };

export type UploadRunResult = {
  uploaded: UploadJob[];
  failures: UploadFailure[];
  cancelled: number;
  aborted: boolean;
};

/** Per-run overrides of the queue-level defaults. */
export type UploadTransportOptions = {
  transport?: UploadTransport;
  isUnauthorized?: (err: unknown) => boolean;
  isRetryable?: (err: unknown) => boolean;
};

export type UploadQueueOptions = {
  concurrency?: number;
  maxAttempts?: number;
  backoffMs?: number;
  capBackoffMs?: number;
  sleep?: (ms: number) => Promise<void>;
  transport?: UploadTransport;
  isRetryable?: (err: unknown) => boolean;
  isUnauthorized?: (err: unknown) => boolean;
};

export type UploadQueue = {
  readonly concurrency: number;
  run: (jobs: UploadJob[], options?: UploadTransportOptions) => Promise<UploadRunResult>;
  cancel: () => void;
  getTasks: () => UploadTask[];
  subscribe: (listener: () => void) => () => void;
  clearFinished: () => void;
  removeTask: (id: number) => void;
};

type UploadTransportContext = {
  onProgress: (progress: UploadProgress) => void;
  signal: AbortSignal;
};

type Run = {
  /** True only for a user `cancel()`; an auth abort must never tally as cancelled. */
  userCancelled: boolean;
  /** Set when a 401 aborted this run; survives into `UploadRunResult.aborted`. */
  authAborted: boolean;
  /** Resolved at `run()` time: per-run override, else the queue-level default. */
  isRetryable: (err: unknown) => boolean;
  isUnauthorized: (err: unknown) => boolean;
  uploaded: UploadJob[];
  failures: UploadFailure[];
  cancelledCount: number;
  remaining: number;
  resolve: (result: UploadRunResult) => void;
};

type Task = UploadTask & {
  controller: AbortController;
  run: Run;
  settled: boolean;
};

const DEFAULT_CONCURRENCY = 4;
const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_BACKOFF_MS = 500;
const DEFAULT_CAP_BACKOFF_MS = 8000;

function defaultSleep(ms: number): Promise<void> {
  return new Promise<void>(resolve => setTimeout(resolve, ms));
}

/**
 * `uploadAsset` is referenced at call time, never captured at module load:
 * sibling suites mock `./api` with factories that omit it.
 */
function defaultTransport(job: UploadJob, ctx: UploadTransportContext): Promise<unknown> {
  return uploadAsset(
    job.entry.file,
    { folder_id: job.folderId ?? undefined },
    { onProgress: (loaded, total) => ctx.onProgress({ loaded, total }), signal: ctx.signal },
  );
}

function defaultIsRetryable(err: unknown): boolean {
  return (err as { retryable?: unknown } | null)?.retryable === true;
}

function defaultIsUnauthorized(err: unknown): boolean {
  return (err as { name?: unknown } | null)?.name === "UnauthorizedError";
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message.trim() || "Upload failed" : "Upload failed";
}

export function createUploadQueue(options: UploadQueueOptions = {}): UploadQueue {
  const concurrency = Math.max(1, options.concurrency ?? DEFAULT_CONCURRENCY);
  const maxAttempts = Math.max(1, options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS);
  const backoffMs = options.backoffMs ?? DEFAULT_BACKOFF_MS;
  const capBackoffMs = options.capBackoffMs ?? DEFAULT_CAP_BACKOFF_MS;
  const sleep = options.sleep ?? defaultSleep;
  const queueTransport = options.transport ?? defaultTransport;
  const isRetryable = options.isRetryable ?? defaultIsRetryable;
  const isUnauthorized = options.isUnauthorized ?? defaultIsUnauthorized;

  // One scheduler for the whole queue: a task holds an `inFlight` slot for its
  // entire lifetime, including retry backoff, so the cap is global and retries
  // can never push the queue past it.
  const pending: Task[] = [];
  const inFlight = new Set<Task>();
  const activeRuns = new Set<Run>();
  const listeners = new Set<() => void>();

  let nextId = 1;

  // The published array is replaced wholesale on every change instead of being
  // mutated in place: `useSyncExternalStore` compares snapshots by reference and
  // at most `concurrency` streams emit progress, so no throttling is needed.
  let tasks: UploadTask[] = [];

  function publish(): void {
    tasks = [...tasks];
    for (const listener of listeners) listener();
  }

  function isStopped(task: Task): boolean {
    return task.run.userCancelled || task.run.authAborted || task.controller.signal.aborted;
  }

  function countCancellation(run: Run): void {
    // Only user-initiated cancellation is tallied; an auth abort adds 0.
    if (run.userCancelled) run.cancelledCount += 1;
  }

  function finishRun(run: Run): void {
    activeRuns.delete(run);
    run.resolve({
      uploaded: run.uploaded,
      failures: run.failures,
      cancelled: run.cancelledCount,
      aborted: run.authAborted,
    });
  }

  function settleTask(task: Task, status: UploadTaskStatus, error?: string): void {
    if (task.settled) return;
    task.settled = true;
    task.status = status;
    if (error !== undefined) task.error = error;
    if (status === "failed" && task.job) {
      // Handles stay on the row so a failed upload can still be retried by the UI.
      task.run.failures.push({ entry: task.job.entry, message: error ?? "", job: task.job });
    }
    publish();
    task.run.remaining -= 1;
    if (task.run.remaining === 0) finishRun(task.run);
  }

  /** Settles and frees a slot in one step: the task is terminal, its transport moot. */
  function cancelTask(task: Task): void {
    task.controller.abort();
    countCancellation(task.run);
    settleTask(task, "cancelled");
    inFlight.delete(task);
  }

  /** Cancels everything of `run` that is still running, releasing their slots. */
  function cancelRunTasks(run: Run): void {
    for (const task of [...inFlight]) {
      if (task.run === run) cancelTask(task);
    }
  }

  function pump(): void {
    while (inFlight.size < concurrency && pending.length > 0) {
      const task = pending.shift();
      if (!task) return;
      if (isStopped(task)) {
        countCancellation(task.run);
        settleTask(task, "cancelled");
        continue;
      }
      void startTask(task);
    }
  }

  async function startTask(task: Task): Promise<void> {
    inFlight.add(task);
    const run = task.run;
    const job = task.job;
    const transport = task.transport;

    try {
      if (!job || !transport) {
        settleTask(task, "failed", "Upload failed");
        return;
      }

      while (true) {
        if (isStopped(task)) {
          cancelTask(task);
          return;
        }

        task.attempts += 1;
        task.status = "uploading";
        task.error = undefined;
        publish();

        try {
          await transport(job, {
            onProgress: progress => {
              task.loaded = Math.min(progress.loaded, progress.total || task.size);
              publish();
            },
            signal: task.controller.signal,
          });
        } catch (err) {
          // A cancel settled this task already; its transport is irrelevant now.
          if (task.settled) return;
          if (run.isUnauthorized(err)) {
            run.authAborted = true;
            cancelRunTasks(run);
            return;
          }
          if (isStopped(task)) {
            cancelTask(task);
            return;
          }
          if (run.isRetryable(err) && task.attempts < maxAttempts) {
            const delay = Math.min(backoffMs * 2 ** (task.attempts - 1), capBackoffMs);
            await sleep(delay);
            // A cancel may have landed during the backoff: never re-attempt after it.
            if (task.settled) return;
            if (isStopped(task)) {
              cancelTask(task);
              return;
            }
            continue;
          }
          settleTask(task, "failed", errorMessage(err));
          return;
        }

        if (task.settled) return;
        task.job = undefined;
        task.transport = undefined;
        run.uploaded.push(job);
        settleTask(task, "done");
        return;
      }
    } finally {
      inFlight.delete(task);
      pump();
    }
  }

  function createTask(job: UploadJob, run: Run, transport: UploadTransport): Task {
    return {
      id: nextId++,
      name: job.entry.file.name,
      size: job.entry.file.size,
      loaded: 0,
      status: "queued",
      attempts: 0,
      job,
      transport,
      controller: new AbortController(),
      run,
      settled: false,
    };
  }

  function run(
    jobs: UploadJob[],
    runOptions: UploadTransportOptions = {},
  ): Promise<UploadRunResult> {
    const transport = runOptions.transport ?? queueTransport;
    let resolveRun: (result: UploadRunResult) => void = () => {};
    const result = new Promise<UploadRunResult>(resolve => {
      resolveRun = resolve;
    });
    const state: Run = {
      userCancelled: false,
      authAborted: false,
      isRetryable: runOptions.isRetryable ?? isRetryable,
      isUnauthorized: runOptions.isUnauthorized ?? isUnauthorized,
      uploaded: [],
      failures: [],
      cancelledCount: 0,
      remaining: 0,
      resolve: resolveRun,
    };

    const created = jobs.map(job => createTask(job, state, transport));
    state.remaining = created.length;

    tasks = [...tasks, ...created];
    pending.push(...created);
    publish();

    if (created.length === 0) {
      finishRun(state);
      return result;
    }

    activeRuns.add(state);
    pump();
    return result;
  }

  function cancel(): void {
    // Cancellation is per-run and never sticky: a `run()` started afterwards is clean.
    for (const runState of activeRuns) {
      runState.userCancelled = true;
      cancelRunTasks(runState);
    }
    pump();
  }

  function getTasks(): UploadTask[] {
    return tasks;
  }

  function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }

  function clearFinished(): void {
    const next = tasks.filter(task => task.status === "queued" || task.status === "uploading");
    if (next.length === tasks.length) return;
    tasks = next;
    publish();
  }

  /**
   * Drops one terminal row. The upload panel calls this before retrying a failed
   * file: the retry starts a fresh task, so the stale failed row must go.
   */
  function removeTask(id: number): void {
    const task = tasks.find(entry => entry.id === id);
    if (!task || task.status === "queued" || task.status === "uploading") return;
    tasks = tasks.filter(entry => entry.id !== id);
    publish();
  }

  return { concurrency, run, cancel, getTasks, subscribe, clearFinished, removeTask };
}

export const uploadQueue: UploadQueue = createUploadQueue({ concurrency: 4 });

export function getUploadTasks(): UploadTask[] {
  return uploadQueue.getTasks();
}

export function subscribeUploadTasks(listener: () => void): () => void {
  return uploadQueue.subscribe(listener);
}

export function clearFinishedUploads(): void {
  uploadQueue.clearFinished();
}
