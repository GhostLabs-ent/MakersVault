import { getPreviewPolicy, PreviewPolicy } from "./api";

export type PreviewReason =
  | "archive_entries"
  | "archive_expanded"
  | "browser_unsupported"
  | "cancelled"
  | "file_too_large"
  | "invalid_geometry"
  | "malformed_3mf"
  | "malformed_lightburn"
  | "malformed_obj"
  | "malformed_step"
  | "malformed_stl"
  | "memory_budget"
  | "step_manual_only"
  | "timeout"
  | "too_many_triangles"
  | "unsupported_type";

export class PreviewJobError extends Error {
  reason: PreviewReason;
  skipped: boolean;

  constructor(reason: PreviewReason, message: string, skipped = false) {
    super(message);
    this.name = "PreviewJobError";
    this.reason = reason;
    this.skipped = skipped;
  }
}

export class PreviewQueueFullError extends Error {}

type Limits = {
  maxBytes: number;
  maxTriangles: number;
  maxExpandedBytes: number;
  maxEntries: number;
  maxMemoryBytes: number;
  timeoutMs: number;
};

type WorkerResult = {
  id: string;
  ok: boolean;
  blob?: Blob;
  geometry?: { positions: Float32Array; indices: Uint32Array; normals: Float32Array; triangleCount: number };
  reason?: PreviewReason;
  detail?: string;
};

export type PreviewGeometry = NonNullable<WorkerResult["geometry"]>;

type JobRecord<T> = {
  start: () => Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
  cancelled: boolean;
  priority: boolean;
};

let active = false;
const queue: JobRecord<unknown>[] = [];

function limitsFor(policy: PreviewPolicy, detail: boolean): Limits {
  return detail ? {
    maxBytes: policy.detail_max_bytes,
    maxTriangles: policy.detail_max_triangles,
    maxExpandedBytes: policy.detail_3mf_expanded_bytes,
    maxEntries: policy.detail_3mf_entries,
    maxMemoryBytes: policy.detail_memory_bytes,
    timeoutMs: policy.detail_timeout_seconds * 1000,
  } : {
    maxBytes: policy.automatic_max_bytes,
    maxTriangles: policy.automatic_max_triangles,
    maxExpandedBytes: policy.automatic_3mf_expanded_bytes,
    maxEntries: policy.automatic_3mf_entries,
    maxMemoryBytes: policy.automatic_memory_bytes,
    timeoutMs: policy.automatic_timeout_seconds * 1000,
  };
}

function drainQueue() {
  if (active) return;
  const record = queue.shift();
  if (!record) return;
  if (record.cancelled) {
    record.reject(new PreviewJobError("cancelled", "Preview was cancelled"));
    drainQueue();
    return;
  }
  active = true;
  record.start().then(record.resolve, record.reject).finally(() => {
    active = false;
    drainQueue();
  });
}

function runWorker(
  url: string,
  ext: string,
  width: number,
  height: number,
  limits: Limits,
  mode: "thumbnail" | "geometry",
  controller: AbortController,
  workerRef: { current: Worker | null },
) {
  return new Promise<WorkerResult>(async (resolve, reject) => {
    const id = crypto.randomUUID();
    let timer = 0;
    try {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`Preview fetch failed: ${response.status}`);
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength > limits.maxBytes) {
        throw new PreviewJobError("file_too_large", "Model exceeds the preview file-size budget", true);
      }
      const worker = new Worker(new URL("./previewWorker.ts", import.meta.url), { type: "module" });
      workerRef.current = worker;
      let onAbort = () => {};
      const cleanup = () => {
        window.clearTimeout(timer);
        controller.signal.removeEventListener("abort", onAbort);
        worker.terminate();
        workerRef.current = null;
      };
      onAbort = () => {
        cleanup();
        reject(new PreviewJobError("cancelled", "Preview was cancelled"));
      };
      controller.signal.addEventListener("abort", onAbort, { once: true });
      worker.onmessage = (event: MessageEvent<WorkerResult>) => {
        if (event.data.id !== id) return;
        cleanup();
        if (!event.data.ok) {
          const reason = event.data.reason || "invalid_geometry";
          const skipped = ["file_too_large", "too_many_triangles", "archive_entries", "archive_expanded", "memory_budget"].includes(reason);
          reject(new PreviewJobError(reason, event.data.detail || "Preview generation failed", skipped));
          return;
        }
        resolve(event.data);
      };
      worker.onerror = event => {
        cleanup();
        reject(new PreviewJobError("invalid_geometry", event.message || "Preview worker failed"));
      };
      timer = window.setTimeout(() => {
        cleanup();
        reject(new PreviewJobError("timeout", "Preview generation timed out"));
      }, limits.timeoutMs);
      worker.postMessage({ id, buffer, ext, width, height, limits, mode }, [buffer]);
    } catch (error) {
      if (controller.signal.aborted) {
        reject(new PreviewJobError("cancelled", "Preview was cancelled"));
      } else {
        reject(error);
      }
    }
  });
}

export type PreviewJobHandle<T> = { promise: Promise<T>; cancel: () => void };

export async function createPreviewJob<T extends "thumbnail" | "geometry">(options: {
  url: string;
  ext: string;
  width: number;
  height: number;
  mode: T;
  detail?: boolean;
  byteSize?: number;
  onStart?: () => void | Promise<void>;
}): Promise<PreviewJobHandle<T extends "thumbnail" ? Blob : PreviewGeometry>> {
  const policy = await getPreviewPolicy();
  const selectedLimits = limitsFor(policy, Boolean(options.detail));
  if (!options.detail && ["step", "stp"].includes(options.ext.toLowerCase())) {
    throw new PreviewJobError("step_manual_only", "STEP previews are detail-only", true);
  }
  if (typeof options.byteSize === "number" && options.byteSize > selectedLimits.maxBytes) {
    throw new PreviewJobError("file_too_large", "Model exceeds the preview file-size budget", true);
  }
  if (queue.length >= policy.queue_limit) throw new PreviewQueueFullError("Preview queue is full");
  const controller = new AbortController();
  const workerRef = { current: null as Worker | null };
  let record: JobRecord<unknown>;
  const promise = new Promise<unknown>((resolve, reject) => {
    record = {
      cancelled: false,
      priority: Boolean(options.detail),
      resolve,
      reject,
      start: async () => {
        await options.onStart?.();
        const result = await runWorker(
          options.url,
          options.ext,
          options.width,
          options.height,
          selectedLimits,
          options.mode,
          controller,
          workerRef,
        );
        return options.mode === "thumbnail" ? result.blob! : result.geometry!;
      },
    };
    if (record.priority) queue.unshift(record); else queue.push(record);
    drainQueue();
  });
  return {
    promise: promise as Promise<T extends "thumbnail" ? Blob : PreviewGeometry>,
    cancel: () => {
      record!.cancelled = true;
      controller.abort();
      workerRef.current?.terminate();
      const index = queue.indexOf(record!);
      if (index >= 0) {
        queue.splice(index, 1);
        record!.reject(new PreviewJobError("cancelled", "Preview was cancelled"));
      }
    },
  };
}

type LightBurnWorkerResult = {
  id: string;
  ok: boolean;
  blob?: Blob;
  reason?: PreviewReason;
  detail?: string;
};

function runLightBurnWorker(
  url: string,
  limits: Limits,
  controller: AbortController,
  workerRef: { current: Worker | null },
) {
  return new Promise<Blob>(async (resolve, reject) => {
    const id = crypto.randomUUID();
    let timer = 0;
    try {
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error(`Preview fetch failed: ${response.status}`);
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength > limits.maxBytes) {
        throw new PreviewJobError("file_too_large", "LightBurn file exceeds the preview budget", true);
      }
      const worker = new Worker(new URL("./lightBurnPreviewWorker.ts", import.meta.url), { type: "module" });
      workerRef.current = worker;
      let onAbort = () => {};
      const cleanup = () => {
        window.clearTimeout(timer);
        controller.signal.removeEventListener("abort", onAbort);
        worker.terminate();
        workerRef.current = null;
      };
      onAbort = () => {
        cleanup();
        reject(new PreviewJobError("cancelled", "Preview was cancelled"));
      };
      controller.signal.addEventListener("abort", onAbort, { once: true });
      worker.onmessage = (event: MessageEvent<LightBurnWorkerResult>) => {
        if (event.data.id !== id) return;
        cleanup();
        if (!event.data.ok || !event.data.blob) {
          const reason = event.data.reason || "invalid_geometry";
          const skipped = ["archive_entries", "archive_expanded", "memory_budget"].includes(reason);
          reject(new PreviewJobError(reason, event.data.detail || "LightBurn preview generation failed", skipped));
          return;
        }
        resolve(event.data.blob);
      };
      worker.onerror = event => {
        cleanup();
        reject(new PreviewJobError("invalid_geometry", event.message || "LightBurn preview worker failed"));
      };
      timer = window.setTimeout(() => {
        cleanup();
        reject(new PreviewJobError("timeout", "LightBurn preview generation timed out"));
      }, limits.timeoutMs);
      worker.postMessage({ id, buffer, limits }, [buffer]);
    } catch (error) {
      if (controller.signal.aborted) reject(new PreviewJobError("cancelled", "Preview was cancelled"));
      else reject(error);
    }
  });
}

export async function createLightBurnPreviewJob(options: {
  url: string;
  byteSize?: number;
  onStart?: () => void | Promise<void>;
}): Promise<PreviewJobHandle<Blob>> {
  const policy = await getPreviewPolicy();
  const limits = limitsFor(policy, false);
  if (typeof options.byteSize === "number" && options.byteSize > limits.maxBytes) {
    throw new PreviewJobError("file_too_large", "LightBurn file exceeds the preview budget", true);
  }
  if (queue.length >= policy.queue_limit) throw new PreviewQueueFullError("Preview queue is full");
  const controller = new AbortController();
  const workerRef = { current: null as Worker | null };
  let record: JobRecord<unknown>;
  const promise = new Promise<Blob>((resolve, reject) => {
    record = {
      cancelled: false,
      priority: false,
      resolve: value => resolve(value as Blob),
      reject,
      start: async () => {
        await options.onStart?.();
        return runLightBurnWorker(options.url, limits, controller, workerRef);
      },
    };
    queue.push(record);
    drainQueue();
  });
  return {
    promise,
    cancel: () => {
      record!.cancelled = true;
      controller.abort();
      workerRef.current?.terminate();
      const index = queue.indexOf(record!);
      if (index >= 0) {
        queue.splice(index, 1);
        record!.reject(new PreviewJobError("cancelled", "Preview was cancelled"));
      }
    },
  };
}
