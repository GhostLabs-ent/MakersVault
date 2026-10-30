import { formatBytes } from "../format";
import { PreviewQueue } from "../previewQueue";
import {
  STEP_INLINE_FALLBACK_BYTES,
  STEP_MAX_BYTES,
  StepParseError,
  type StepGeometryPayload,
  type StepWorkerRequest,
  type StepWorkerResponse,
} from "./protocol";
import { resetStepBudgetsForTests, resolveStepBudgets } from "./stepConfig";

export type WorkerLike = {
  onmessage: ((event: MessageEvent<unknown>) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessageerror: ((event: unknown) => void) | null;
  postMessage(message: unknown, transfer?: Transferable[]): void;
  terminate(): void;
};

export type StepWorkerOptions = {
  createWorker?: () => WorkerLike;
  queue?: PreviewQueue;
  signal?: AbortSignal;
};

export class StepAbortError extends Error {
  constructor(message = "STEP preview was aborted") {
    super(message);
    this.name = "StepAbortError";
  }
}

export class StepTimeoutError extends Error {
  constructor(message = "STEP preview timed out") {
    super(message);
    this.name = "StepTimeoutError";
  }
}

type PendingRequest = {
  resolve: (geometry: StepGeometryPayload) => void;
  reject: (error: unknown) => void;
};

/**
 * STEP gets its own queue rather than sharing `previewQueue`: a single occt
 * parse can hold the worker for a minute or more, and letting that block the
 * shared preview lanes would starve every cheap STL/OBJ/thumbnail job.
 *
 * Built on first use from the resolved budgets, so a build-time `VITE_STEP_*`
 * override is what the first STEP preview actually gets, and no queue exists
 * in a session that never opens a STEP file.
 */
let defaultQueue: PreviewQueue | null = null;

function getDefaultQueue(): PreviewQueue {
  if (defaultQueue) return defaultQueue;
  const budgets = resolveStepBudgets();
  defaultQueue = new PreviewQueue({
    maxPending: budgets.maxPending,
    jobBudgetMs: budgets.jobBudgetMs,
    sessionBudgetMs: budgets.sessionBudgetMs,
  });
  return defaultQueue;
}

/**
 * Test-only handle on the default queue: its stats are how a build-time budget
 * override becomes observable, since nothing else exposes the queue.
 */
export function getDefaultStepQueueForTests(): PreviewQueue {
  return getDefaultQueue();
}

let worker: WorkerLike | null = null;
let nextRequestId = 1;
const pending = new Map<number, PendingRequest>();

/**
 * Session-level marker for "the worker crashed". Once set we never spawn
 * another one: a WASM module that traps tends to trap again, so a respawn
 * would only turn one bad file into an endless crash loop.
 */
let brokenReason: string | null = null;

function discardWorker(reason: Error = new StepAbortError()): void {
  const current = worker;
  // Null it first so a second discard (abort plus reset, say) cannot terminate
  // the same worker twice or resurrect it.
  worker = null;
  // Every request still waiting lost its reply along with the worker, so it
  // fails now instead of hanging until its own budget runs out.
  failAllPending(reason);
  if (!current) return;
  current.onmessage = null;
  current.onerror = null;
  current.onmessageerror = null;
  try {
    current.terminate();
  } catch {
    // A worker that already died can reject terminate(); nothing left to do.
  }
}

function failAllPending(error: unknown): void {
  const requests = [...pending.values()];
  pending.clear();
  for (const request of requests) request.reject(error);
}

function describeFailure(event: unknown): string {
  if (event && typeof event === "object" && "message" in event) {
    const message = (event as { message?: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  if (event instanceof Error) return event.message;
  return "STEP worker failed";
}

function markWorkerBroken(event: unknown): void {
  // Set the reason before the discard: a respawn on the way out would turn one
  // bad file into an endless crash loop.
  brokenReason = describeFailure(event);
  discardWorker(new StepParseError(brokenReason));
}

function handleWorkerMessage(event: MessageEvent<unknown>): void {
  const data = event.data as StepWorkerResponse | null;
  if (!data || typeof data.id !== "number") return;
  const request = pending.get(data.id);
  if (!request) return;
  pending.delete(data.id);
  if (data.ok) request.resolve(data.geometry);
  else request.reject(new StepParseError(data.error));
}

function createDefaultWorker(): WorkerLike {
  return new Worker(new URL("./step.worker.ts", import.meta.url), {
    type: "module",
  }) as unknown as WorkerLike;
}

function getWorker(createWorker: () => WorkerLike): WorkerLike {
  if (worker) return worker;
  const created = createWorker();
  created.onmessage = handleWorkerMessage;
  created.onerror = markWorkerBroken;
  created.onmessageerror = markWorkerBroken;
  worker = created;
  return created;
}

/**
 * The queue hands `run` a signal that fires for both caller aborts and the
 * job budget. Which error the caller sees depends on the caller's own signal,
 * so the abort reason is derived from that signal, never from the queue.
 */
function abortReason(callerSignal: AbortSignal | undefined): Error {
  if (callerSignal?.aborted) return new StepAbortError();
  return new StepTimeoutError();
}

/**
 * The inline fallback is the only route from the main thread to occt, so the
 * import stays dynamic: a static one would put the whole WASM module in the
 * entry bundle for readers who never open a STEP file.
 */
async function readStepInline(bytes: Uint8Array): Promise<StepGeometryPayload> {
  const { readStepMeshes } = await import("./readStep");
  return await readStepMeshes(bytes);
}

function runJob(
  bytes: Uint8Array,
  signal: AbortSignal,
  callerSignal: AbortSignal | undefined,
  createWorker: () => WorkerLike,
): Promise<StepGeometryPayload> {
  return new Promise<StepGeometryPayload>((resolve, reject) => {
    if (signal.aborted) {
      reject(abortReason(callerSignal));
      return;
    }

    const target = getWorker(createWorker);
    const id = nextRequestId;
    nextRequestId += 1;

    // Copy before posting: the caller keeps ownership of its own buffer, and
    // transferring a live view would detach the bytes out from under it.
    const copy = bytes.slice();
    const transfer = copy.buffer as ArrayBuffer;
    const request: StepWorkerRequest = { id, bytes: transfer };

    const onAbort = (): void => {
      // Drop our own entry before the discard so the failure below is what
      // carries this caller's precision (caller abort, or its own job budget),
      // while every other waiter gets the generic abort from the discard.
      pending.delete(id);
      // The job is already inside the worker, so the only way to stop it is to
      // drop the worker; the next request pays one cold start.
      discardWorker();
      reject(abortReason(callerSignal));
    };

    pending.set(id, {
      resolve: geometry => {
        signal.removeEventListener("abort", onAbort);
        resolve(geometry);
      },
      reject: error => {
        signal.removeEventListener("abort", onAbort);
        reject(error);
      },
    });

    signal.addEventListener("abort", onAbort, { once: true });

    try {
      target.postMessage(request, [transfer]);
    } catch (error) {
      pending.delete(id);
      signal.removeEventListener("abort", onAbort);
      reject(error);
    }
  });
}

export function stepSizeNotice(
  bytes: number,
  warnBytes: number = resolveStepBudgets().sizeWarnBytes,
): string | null {
  if (bytes <= warnBytes) return null;
  return `Large STEP file (${formatBytes(bytes)}) - parsing may take a moment`;
}

/**
 * Parse a STEP file off the main thread, falling back to inline parsing when
 * the worker cannot be used (no Worker support, or a worker that already
 * crashed this session) and the file is small enough to risk blocking on.
 */
export async function parseStepInWorker(
  bytes: Uint8Array,
  options: StepWorkerOptions = {},
): Promise<StepGeometryPayload> {
  if (bytes.length > STEP_MAX_BYTES) {
    throw new StepParseError(
      `STEP preview is limited to ${Math.floor(STEP_MAX_BYTES / (1024 * 1024))} MB`,
    );
  }

  if (brokenReason) {
    if (bytes.length <= STEP_INLINE_FALLBACK_BYTES) return await readStepInline(bytes);
    throw new StepParseError(
      `STEP preview is unavailable (${brokenReason}) and this file is too large to parse inline`,
    );
  }

  if (typeof Worker === "undefined" && !options.createWorker) {
    if (bytes.length <= STEP_INLINE_FALLBACK_BYTES) return await readStepInline(bytes);
    throw new StepParseError("STEP preview requires a Web Worker for files over 4 MB");
  }

  const queue = options.queue ?? getDefaultQueue();
  const createWorker = options.createWorker ?? createDefaultWorker;
  const callerSignal = options.signal;

  const result = await queue.enqueue({
    signal: callerSignal ?? new AbortController().signal,
    run: signal => runJob(bytes, signal, callerSignal, createWorker),
  });

  // `null` means nothing will ever be delivered: either the caller gave up or
  // the job outlived its budget. The caller's signal is the tiebreaker.
  if (result === null) throw abortReason(callerSignal);
  return result;
}

export function resetStepWorkerForTests(): void {
  discardWorker(new StepParseError("STEP worker reset"));
  nextRequestId = 1;
  brokenReason = null;
  // `reset()` settles queued-but-never-started jobs, then both the queue and
  // the budget memo behind it are dropped so the next build reads the test's
  // own `VITE_STEP_*` values instead of the previous test's.
  const dropped = defaultQueue;
  defaultQueue = null;
  dropped?.reset();
  resetStepBudgetsForTests();
}
