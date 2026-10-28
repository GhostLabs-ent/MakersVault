import { useState } from "react";
import type { Asset } from "../lib/api";
import { formatBytes } from "../lib/format";

/** Per-asset failure the dialog lists instead of claiming a clean delete. */
export type AssetDeleteFailure = { id: string; message: string };

type Props = {
  /** The targets the user asked for: one gets the typed gate, several the stepped one. */
  assets: Asset[];
  /**
   * Runs the delete. The parent owns the request, the grid's optimistic update
   * and the refresh, and answers with whatever failed.
   */
  onDelete: (assets: Asset[]) => Promise<{ failed: AssetDeleteFailure[] }>;
  /** The user dismissed the dialog without deleting anything. */
  onCancel: () => void;
  /** The dialog is finished (deleted, or closed after failures); drop the target state. */
  onClosed: () => void;
};

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message.trim()) return err.message;
  return fallback;
}

function assetLabel(asset: Asset): string {
  return asset.filename || asset.name || asset.id;
}

/** A tracked asset is its primary file plus every supporting file; a mounted
 * reference owns no bytes of its own, so it counts as none. */
function fileCount(asset: Asset): number {
  if (asset.is_reference) return 0;
  return 1 + (asset.supporting_file_count || 0);
}

function totalFiles(assets: Asset[]): number {
  return assets.reduce((sum, asset) => sum + fileCount(asset), 0);
}

function totalBytes(assets: Asset[]): number {
  // A mounted reference's bytes are not ours to move, so they never appear here.
  return assets.reduce((sum, asset) => sum + (asset.is_reference ? 0 : asset.size || 0), 0);
}

function dialogTitle(assets: Asset[]): string {
  if (assets.length > 1) return `Delete ${assets.length} selected items?`;
  const [asset] = assets;
  if (asset.missing_since) return `Forget “${assetLabel(asset)}”?`;
  return `Delete “${assetLabel(asset)}”?`;
}

function confirmLabel(assets: Asset[]): string {
  if (assets.length > 1) return `Delete ${assets.length} items`;
  return assets[0].missing_since ? "Forget entry" : "Delete asset";
}

function busyLabel(assets: Asset[]): string {
  if (assets.length > 1) return "Deleting…";
  return assets[0].missing_since ? "Forgetting…" : "Deleting…";
}

/**
 * The one confirmation for every asset delete: a single asset needs its file
 * name typed (the server rejects a mismatch), a selection is confirmed with a
 * step instead of N names. Both shapes say what actually happens — the files
 * move to the server's `.trash` and are only freed by "Empty trash".
 */
export default function AssetDeleteDialog({ assets, onDelete, onCancel, onClosed }: Props) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [failed, setFailed] = useState<AssetDeleteFailure[]>([]);

  const single = assets.length === 1 ? assets[0] : null;
  const singleIsReference = single !== null && Boolean(single.is_reference);
  const singleIsMissing = single !== null && Boolean(single.missing_since);
  const referenceCount = assets.filter(asset => Boolean(asset.is_reference)).length;
  const missingCount = assets.filter(asset => Boolean(asset.missing_since)).length;
  const files = totalFiles(assets);
  const bytes = totalBytes(assets);
  // The single shape gates on the exact file name the server compares against.
  const canDelete = !busy && (single === null || typed === single.filename);

  const confirmDelete = async () => {
    if (!canDelete) return;
    setBusy(true);
    setError(null);
    setFailed([]);
    try {
      const result = await onDelete(assets);
      if (result.failed.length) {
        // Never close on a partial result: the un-deleted rows are still there.
        setFailed(result.failed);
        return;
      }
      onClosed();
    } catch (err) {
      setError(errorMessage(err, "Failed to delete the selection."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="asset-delete-title"
    >
      <div className="bg-panel-strong rounded-lg shadow-2xl w-full max-w-lg flex flex-col">
        <div className="border-b border-panel px-4 py-3">
          <h2 id="asset-delete-title" className="text-lg font-semibold">
            {dialogTitle(assets)}
          </h2>
        </div>

        <div className="px-4 py-3 flex flex-col gap-3 text-sm">
          <p>
            {single
              ? "This removes the asset's library entry, its thumbnail and its sidecar files."
              : `This removes ${assets.length} library entries, their thumbnails and their sidecar files.`}
          </p>
          <p className="opacity-80">
            The files are first moved to the server&apos;s <code>.trash</code> folder, so
            nothing is freed yet. Bytes are only deleted for good when someone runs
            <strong> Empty trash</strong> in Settings → Storage.
          </p>
          <p className="opacity-80">
            Restoring is file-level only: move the file back out of <code>.trash</code> by
            hand and rescan the storage folder. The file comes back; its metadata (names,
            tags, notes, prepared-print details) does not.
          </p>

          {singleIsReference && (
            <p className="opacity-80">
              This asset is a mounted reference: only its library record is removed. The
              file on disk is never touched.
            </p>
          )}
          {!single && referenceCount > 0 && (
            <p className="opacity-80">
              {referenceCount} of these are mounted references: those rows only lose their
              library record, and the files on disk are never touched.
            </p>
          )}

          {singleIsMissing && (
            <p className="text-red-400">
              Its file is already missing from storage, so nothing moves to{" "}
              <code>.trash</code>: only the library record, thumbnail and sidecars go.
            </p>
          )}
          {!single && missingCount > 0 && (
            <p className="text-red-400">
              {missingCount} of these have files missing from storage: nothing moves to{" "}
              <code>.trash</code> for those, only their library records go.
            </p>
          )}

          <div className="rounded-md border border-dashed border-panel-strong p-3 text-xs">
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <span>
                {files} file{files === 1 ? "" : "s"}
              </span>
              <span>{formatBytes(bytes)}</span>
              {!single && <span>{assets.length} tracked assets</span>}
            </div>
            <p className="mt-2 opacity-70">
              Counts include supporting files. Nothing is freed until the trash is emptied.
            </p>
          </div>

          {single ? (
            <label className="flex flex-col gap-1">
              <span>
                Type <strong>{single.filename}</strong> to confirm
              </span>
              <input
                aria-label="Type the file name to confirm"
                className="px-3 py-2 rounded-md border border-panel-strong bg-panel-soft disabled:opacity-60"
                value={typed}
                onChange={e => setTyped(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter") void confirmDelete();
                }}
                disabled={busy || failed.length > 0}
                autoFocus
              />
            </label>
          ) : (
            <p className="opacity-80">
              Nothing has been deleted yet: confirming removes all {assets.length} selected
              items.
            </p>
          )}

          {error && <p className="text-red-400">{error}</p>}

          {failed.length > 0 && (
            <div role="alert" className="flex flex-col gap-1 rounded-md border border-red-400 p-3">
              <p className="text-red-400">
                {failed.length} of {assets.length} could not be deleted. Their library
                entries are unchanged.
              </p>
              <ul data-testid="asset-delete-failures" className="flex flex-col gap-1 text-xs">
                {failed.map(failure => {
                  const asset = assets.find(item => item.id === failure.id);
                  return (
                    <li key={failure.id} data-failed-id={failure.id}>
                      {asset ? assetLabel(asset) : failure.id} — {failure.message}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-panel px-4 py-3">
          {failed.length > 0 ? (
            <button
              type="button"
              className="px-3 py-2 rounded-md border border-panel-strong text-sm"
              onClick={onClosed}
            >
              Close
            </button>
          ) : (
            <>
              <button
                type="button"
                className="px-3 py-2 rounded-md border border-panel-strong text-sm disabled:opacity-60"
                onClick={onCancel}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                type="button"
                className="px-3 py-2 rounded-md bg-red-600 text-white text-sm disabled:opacity-60"
                onClick={() => void confirmDelete()}
                disabled={!canDelete}
              >
                {busy ? busyLabel(assets) : confirmLabel(assets)}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
