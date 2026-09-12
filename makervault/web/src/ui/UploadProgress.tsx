import React, { useSyncExternalStore } from "react";
import { dismissUpload, getUploadBatches, subscribeUploads, uploadIsActive, uploadPercent, type UploadBatch } from "../lib/uploadProgress";

const labels = {
  preparing: "Preparing upload", uploading: "Uploading", finalizing: "Finalizing on server",
  complete: "Upload complete", partial: "Upload finished with errors", stopped: "Upload stopped",
};

export function UploadProgressItem({ batch }: { batch: UploadBatch }) {
  const percent = uploadPercent(batch);
  return (
    <section className="rounded-lg border border-panel-strong bg-panel-strong p-3 shadow-lg pointer-events-auto" data-upload-phase={batch.phase}>
      <div className="flex items-start justify-between gap-3">
        <div role="status" aria-live="polite" className="min-w-0 text-sm">
          <p className="font-semibold">{labels[batch.phase]}</p>
          <p>{batch.savedFiles} / {batch.totalFiles} files saved{batch.failedFiles ? ` · ${batch.failedFiles} failed` : ""}</p>
        </div>
        {!uploadIsActive(batch) && <button type="button" aria-label="Dismiss upload result"
          className="rounded px-2 py-1 text-sm hover:bg-panel-soft" onClick={() => dismissUpload(batch.id)}>Dismiss</button>}
      </div>
      {batch.currentPath && <p className="mt-1 truncate text-xs text-muted" title={batch.currentPath}>{batch.currentPath}</p>}
      <progress className="mt-2 h-2 w-full accent-accent" aria-label="Upload transfer" max={100} value={percent ?? undefined} />
      <p className="mt-1 text-xs text-muted">{percent === null ? "Transfer progress unavailable" : `${percent}% transferred`}
        {batch.phase === "finalizing" ? " · Waiting for server confirmation" : ""}</p>
    </section>
  );
}

export default function UploadProgress() {
  const batches = useSyncExternalStore(subscribeUploads, getUploadBatches, getUploadBatches);
  if (!batches.length) return null;
  return <section aria-label="Upload progress" className="fixed bottom-4 right-4 z-[60] max-h-[50vh] w-80 max-w-[calc(100vw-2rem)] space-y-2 overflow-y-auto pointer-events-none">
    {batches.map(batch => <UploadProgressItem key={batch.id} batch={batch} />)}
  </section>;
}
