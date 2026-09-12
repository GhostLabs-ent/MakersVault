import type { UploadTransfer } from "./uploadRequest";

export type UploadPhase = "preparing" | "uploading" | "finalizing" | "complete" | "partial" | "stopped";
export type UploadBatch = {
  id: number;
  totalFiles: number;
  totalBytes: number;
  transferredBytes: number;
  savedFiles: number;
  failedFiles: number;
  currentPath: string;
  phase: UploadPhase;
  measurable: boolean;
};

let sequence = 0;
let batches: readonly UploadBatch[] = [];
const listeners = new Set<() => void>();
const controllers = new Map<number, AbortController>();
export const uploadIsActive = (batch: UploadBatch) => ["preparing", "uploading", "finalizing"].includes(batch.phase);
export const uploadPercent = (batch: UploadBatch): number | null => batch.phase === "complete" ? 100
  : batch.measurable && batch.totalBytes > 0 ? Math.min(100, Math.floor(100 * batch.transferredBytes / batch.totalBytes)) : null;
export const getUploadBatches = () => batches;
export function subscribeUploads(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
function publish(next: readonly UploadBatch[]) {
  const recent = next.filter(batch => !uploadIsActive(batch)).slice(-3);
  batches = next.filter(batch => uploadIsActive(batch) || recent.includes(batch));
  listeners.forEach(listener => listener());
}
export function dismissUpload(id: number) {
  publish(batches.filter(batch => batch.id !== id || uploadIsActive(batch)));
}
export function clearUploads() {
  // Stop old-account requests/queues before another account can sign in.
  const active = [...controllers.values()];
  controllers.clear();
  publish([]);
  active.forEach(controller => controller.abort());
}

export function startUploadBatch(files: readonly { size: number }[]) {
  const sizeOf = (value: number) => Number.isFinite(value) && value > 0 ? value : 0;
  const controller = new AbortController();
  let state: UploadBatch = { id: ++sequence, totalFiles: files.length,
    totalBytes: files.reduce((sum, file) => sum + sizeOf(file.size), 0), transferredBytes: 0,
    savedFiles: 0, failedFiles: 0, currentPath: "", phase: "preparing", measurable: true };
  controllers.set(state.id, controller);
  publish([...batches, state]);
  let settledBytes = 0;
  let currentBytes = 0;
  let currentSize = 0;
  const update = (changes: Partial<UploadBatch>) => {
    state = { ...state, ...changes };
    if (!controller.signal.aborted) publish(batches.map(batch => batch.id === state.id ? state : batch));
  };
  return {
    signal: controller.signal,
    beginFile(path: string, size: number) {
      currentBytes = 0;
      currentSize = sizeOf(size);
      update({ currentPath: path, phase: "preparing", measurable: true });
    },
    transfer({ fraction, phase }: UploadTransfer) {
      if (fraction !== null && Number.isFinite(fraction)) {
        currentBytes = Math.max(currentBytes, currentSize * Math.max(0, Math.min(1, fraction)));
      }
      const next = { ...state, transferredBytes: settledBytes + currentBytes, phase, measurable: fraction !== null };
      // Browser events can be frequent; render only percentage/phase changes.
      if (uploadPercent(next) !== uploadPercent(state) || phase !== state.phase || next.measurable !== state.measurable) update(next);
    },
    saved() {
      settledBytes += currentSize;
      update({ savedFiles: state.savedFiles + 1, transferredBytes: settledBytes, measurable: true });
    },
    failed() {
      settledBytes += currentBytes;
      update({ failedFiles: state.failedFiles + 1, transferredBytes: settledBytes });
    },
    finish(stopped = false) {
      update({ phase: stopped ? "stopped" : state.savedFiles === state.totalFiles ? "complete" : "partial", currentPath: "" });
      controllers.delete(state.id);
    },
  };
}
