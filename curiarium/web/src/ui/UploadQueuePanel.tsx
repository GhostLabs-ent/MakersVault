import type { ReactElement } from "react";
import { useSyncExternalStore } from "react";

import {
  clearFinishedUploads,
  getUploadTasks,
  subscribeUploadTasks,
  uploadQueue,
  type UploadTask,
  type UploadTaskStatus,
} from "../lib/uploadQueue";

export type UploadQueuePanelProps = {
  /** Called when a retry from the panel actually uploaded something. */
  onUploaded?: () => void;
  /** Called when a retry aborted on a 401. */
  onUnauthorized?: () => void;
};

const STATUS_LABELS: Record<UploadTaskStatus, string> = {
  queued: "Queued",
  uploading: "Uploading",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

type UploadSummary = {
  total: number;
  active: number;
  done: number;
  failed: number;
  cancelled: number;
  loadedBytes: number;
  totalBytes: number;
};

function isActive(task: UploadTask): boolean {
  return task.status === "queued" || task.status === "uploading";
}

/** A zero-byte batch has no ratio to speak of; treat it as complete. */
function percentOf(loaded: number, total: number): number {
  // XHR reports the multipart body length as `total`, which is larger than the
  // file, so a tiny file can overshoot its own size; never show more than 100%.
  return total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : 100;
}

function summarize(tasks: UploadTask[]): UploadSummary {
  const summary: UploadSummary = {
    total: tasks.length,
    active: 0,
    done: 0,
    failed: 0,
    cancelled: 0,
    loadedBytes: 0,
    totalBytes: 0,
  };

  for (const task of tasks) {
    if (isActive(task)) summary.active += 1;
    else if (task.status === "done") summary.done += 1;
    else if (task.status === "failed") summary.failed += 1;
    else summary.cancelled += 1;
    summary.loadedBytes += task.loaded;
    summary.totalBytes += task.size;
  }

  return summary;
}

function statusLine(summary: UploadSummary): string {
  if (summary.active > 0) {
    const finished = summary.total - summary.active;
    return `Uploading ${finished} of ${summary.total} · ${percentOf(summary.loadedBytes, summary.totalBytes)}%`;
  }

  let line = `${summary.done} of ${summary.total} uploaded`;
  if (summary.failed > 0) line += ` · ${summary.failed} failed`;
  if (summary.cancelled > 0) line += ` · ${summary.cancelled} cancelled`;
  return line;
}

/**
 * App-level progress panel over the global upload queue.
 *
 * Sits bottom-left because `Toaster` owns `fixed bottom-4 right-4 z-[60]`.
 * Fixed positioning keeps it out of the App layout flow entirely.
 */
export default function UploadQueuePanel({
  onUploaded,
  onUnauthorized,
}: UploadQueuePanelProps): ReactElement | null {
  const tasks = useSyncExternalStore(subscribeUploadTasks, getUploadTasks);

  if (tasks.length === 0) return null;

  const summary = summarize(tasks);
  const hasActive = summary.active > 0;

  const retry = async (task: UploadTask): Promise<void> => {
    if (!task.job) return;
    // Drop the stale failed row first: the retry publishes a fresh row of its own.
    uploadQueue.removeTask(task.id);
    const result = await uploadQueue.run([task.job], { transport: task.transport });
    if (result.aborted) onUnauthorized?.();
    // A failed retry needs no extra reporting: its new row already shows the failure.
    if (result.uploaded.length > 0) onUploaded?.();
  };

  // Cancel covers only work the queue already holds. A zip prompt that is
  // currently open stays open: confirming it later is fresh user intent and
  // simply starts a new run.
  const cancelAll = (): void => uploadQueue.cancel();

  return (
    <section
      data-testid="upload-queue"
      aria-live="polite"
      className="fixed bottom-4 left-4 z-[55] flex w-80 max-w-sm flex-col gap-2 rounded-md border border-panel-strong bg-panel-soft p-3 text-sm shadow-lg"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-medium">Uploads</h2>
        {hasActive ? (
          <button
            type="button"
            onClick={cancelAll}
            className="px-2 py-1 rounded-md border border-panel-strong"
          >
            Cancel
          </button>
        ) : (
          <button
            type="button"
            onClick={() => clearFinishedUploads()}
            className="px-2 py-1 rounded-md border border-panel-strong"
          >
            Dismiss
          </button>
        )}
      </div>

      <p data-testid="upload-queue-status" className="text-muted">
        {statusLine(summary)}
      </p>

      <progress
        value={summary.loadedBytes}
        max={summary.totalBytes || 1}
        aria-label="Overall upload progress"
        className="w-full"
      />

      <ul className="flex max-h-64 flex-col gap-2 overflow-auto">
        {tasks.map(task => {
          const percent = percentOf(task.loaded, task.size);
          return (
            <li key={task.id} className="flex flex-col gap-1">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate" title={task.name}>
                  {task.name}
                </span>
                <span className="shrink-0">{STATUS_LABELS[task.status]}</span>
              </div>

              <div className="flex items-center gap-2">
                <progress
                  value={task.loaded}
                  max={task.size || 1}
                  aria-label={`${task.name} progress`}
                  className="w-full"
                />
                {task.status === "uploading" && <span className="shrink-0">{percent}%</span>}
              </div>

              {task.status === "failed" && task.error && (
                <span className="text-red-700 dark:text-red-300">{task.error}</span>
              )}

              {task.status === "failed" && task.job && (
                <button
                  type="button"
                  aria-label={`Retry ${task.name}`}
                  onClick={() => void retry(task)}
                  className="self-start px-2 py-1 rounded-md border border-panel-strong"
                >
                  Retry
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
