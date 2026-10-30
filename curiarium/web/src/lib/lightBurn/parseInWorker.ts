import { PreviewQueue } from "../previewQueue";
import {
  parseLightBurn,
  LightBurnParseError,
  LIGHTBURN_INLINE_FALLBACK_BYTES,
  LIGHTBURN_MAX_BYTES,
  type LightBurnLimits,
  type LightBurnModel,
} from "./parse";

export type WorkerLike = {
  onmessage: ((event: MessageEvent<unknown>) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessageerror: ((event: unknown) => void) | null;
  postMessage(message: unknown, transfer?: Transferable[]): void;
  terminate(): void;
};

export type LightBurnWorkerOptions = {
  createWorker?: () => WorkerLike;
  queue?: PreviewQueue;
  timeoutMs?: number;
};

type PendingRequest = {
  resolve: (model: LightBurnModel) => void;
  reject: (error: unknown) => void;
  timer: ReturnType<typeof setTimeout>;
};

type WorkerResponse =
  | { id: number; ok: true; model: LightBurnModel }
  | { id: number; ok: false; error: string };

export class LightBurnTimeoutError extends Error {
  constructor(message = "LightBurn preview timed out") {
    super(message);
    this.name = "LightBurnTimeoutError";
  }
}

export class LightBurnAbortError extends Error {
  constructor(message = "LightBurn preview was aborted") {
    super(message);
    this.name = "LightBurnAbortError";
  }
}

const DEFAULT_TIMEOUT_MS = 5000;

const defaultQueue = new PreviewQueue({ maxPending: 4, jobBudgetMs: 6000 });

let worker: WorkerLike | null = null;
let nextRequestId = 1;
const pending = new Map<number, PendingRequest>();

function discardWorker(): void {
  const current = worker;
  worker = null;
  if (!current) return;
  current.onmessage = null;
  current.onerror = null;
  current.onmessageerror = null;
  try {
    current.terminate();
  } catch {
    // A worker that already died can reject terminate(); nothing to do.
  }
}

function failAllPending(error: unknown): void {
  const requests = [...pending.values()];
  pending.clear();
  for (const request of requests) {
    clearTimeout(request.timer);
    request.reject(error);
  }
}

function handleWorkerFailure(): void {
  discardWorker();
  failAllPending(new LightBurnParseError("LightBurn worker failed"));
}

function handleWorkerMessage(event: MessageEvent<unknown>): void {
  const data = event.data as WorkerResponse | null;
  if (!data || typeof data.id !== "number") return;
  const request = pending.get(data.id);
  if (!request) return;
  pending.delete(data.id);
  clearTimeout(request.timer);
  if (data.ok) request.resolve(data.model);
  else request.reject(new LightBurnParseError(data.error));
}

function createDefaultWorker(): WorkerLike {
  return new Worker(new URL("./preview.worker.ts", import.meta.url), {
    type: "module",
  }) as unknown as WorkerLike;
}

function getWorker(createWorker: () => WorkerLike): WorkerLike {
  if (worker) return worker;
  const created = createWorker();
  created.onmessage = handleWorkerMessage;
  created.onerror = handleWorkerFailure;
  created.onmessageerror = handleWorkerFailure;
  worker = created;
  return created;
}

function runJob(
  bytes: Uint8Array,
  limits: LightBurnLimits,
  signal: AbortSignal,
  timeoutMs: number,
  createWorker: () => WorkerLike,
): Promise<LightBurnModel> {
  return new Promise<LightBurnModel>((resolve, reject) => {
    if (signal.aborted) {
      reject(new LightBurnAbortError());
      return;
    }

    const target = getWorker(createWorker);
    const id = nextRequestId;
    nextRequestId += 1;
    const copy = bytes.slice();
    const transfer = copy.buffer;

    const onAbort = (): void => {
      pending.delete(id);
      clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      discardWorker();
      reject(new LightBurnAbortError());
    };

    const timer = setTimeout(() => {
      pending.delete(id);
      signal.removeEventListener("abort", onAbort);
      discardWorker();
      reject(new LightBurnTimeoutError(`LightBurn preview timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    pending.set(id, {
      resolve: model => {
        signal.removeEventListener("abort", onAbort);
        resolve(model);
      },
      reject: error => {
        signal.removeEventListener("abort", onAbort);
        reject(error);
      },
      timer,
    });

    signal.addEventListener("abort", onAbort, { once: true });

    try {
      target.postMessage({ id, bytes: transfer, limits }, [transfer]);
    } catch (error) {
      pending.delete(id);
      clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      reject(error);
    }
  });
}

export async function parseLightBurnInWorker(
  bytes: Uint8Array,
  limits: LightBurnLimits,
  options: LightBurnWorkerOptions = {},
): Promise<LightBurnModel> {
  if (bytes.length > LIGHTBURN_MAX_BYTES) {
    throw new LightBurnParseError(
      `LightBurn preview is limited to ${Math.floor(LIGHTBURN_MAX_BYTES / (1024 * 1024))} MB`,
    );
  }

  if (typeof Worker === "undefined") {
    if (bytes.length <= LIGHTBURN_INLINE_FALLBACK_BYTES) {
      return parseLightBurn(bytes, limits);
    }
    throw new LightBurnParseError("Preview requires a Web Worker for files over 2 MB");
  }

  const queue = options.queue ?? defaultQueue;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const createWorker = options.createWorker ?? createDefaultWorker;

  const controller = new AbortController();
  const result = await queue.enqueue({
    signal: controller.signal,
    run: signal => runJob(bytes, limits, signal, timeoutMs, createWorker),
  });

  if (result === null) throw new LightBurnAbortError();
  return result;
}

export function resetLightBurnWorkerForTests(): void {
  discardWorker();
  failAllPending(new LightBurnAbortError("LightBurn worker reset"));
  nextRequestId = 1;
  defaultQueue.reset();
}
