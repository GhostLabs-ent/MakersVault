import { useEffect, useState } from "react";
import { RefreshCw, Trash2 } from "lucide-react";
import {
  UnauthorizedError,
  getTrash,
  purgeTrash,
  type TrashList,
  type TrashPurgeResult,
} from "../lib/api";
import { formatBytes } from "../lib/format";
import { useStableCallback } from "../lib/useStableCallback";

type Props = {
  onUnauthorized?: () => void;
};

function errorMessage(err: unknown, fallback: string) {
  if (err instanceof Error && err.message.trim()) return err.message;
  return fallback;
}

export default function TrashCard({ onUnauthorized }: Props) {
  const [trash, setTrash] = useState<TrashList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [purging, setPurging] = useState(false);
  const [purgeResult, setPurgeResult] = useState<TrashPurgeResult | null>(null);

  const handleUnauthorized = useStableCallback(() => onUnauthorized?.());

  const load = useStableCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTrash(await getTrash());
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        handleUnauthorized();
        return;
      }
      setError(errorMessage(err, "Unable to load the trash."));
    } finally {
      setLoading(false);
    }
  });

  useEffect(() => { void load(); }, [load]);

  const purge = async () => {
    setPurging(true);
    setError(null);
    try {
      const result = await purgeTrash();
      setPurgeResult(result);
      setConfirming(false);
      await load();
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        handleUnauthorized();
        return;
      }
      setError(errorMessage(err, "Failed to empty the trash."));
    } finally {
      setPurging(false);
    }
  };

  const entries = trash?.entries || [];
  const totalSize = trash?.total_size || 0;

  return (
    <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-lg font-semibold">Trash</div>
          <p className="text-sm opacity-70">
            Deleted folders wait here before they are purged. Deleting a folder never frees
            its bytes — only emptying the trash does. Restoring is file-level: move an entry
            back into the storage folder, then rescan the library.
          </p>
        </div>
        <button
          type="button"
          className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
          onClick={() => void load()}
          disabled={loading}
        >
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {loading && <p className="text-sm opacity-70">Loading trash…</p>}

      {!loading && trash && entries.length === 0 && (
        <p className="text-sm opacity-70">
          The trash is empty. Folders you delete will appear here until the trash is emptied.
        </p>
      )}

      {entries.length > 0 && (
        <ul className="flex flex-col divide-y divide-panel rounded-md border border-panel-strong">
          {entries.map(entry => (
            <li key={entry.path} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <div className="min-w-0">
                <div className="truncate font-medium" title={entry.path}>{entry.name}</div>
                <div className="text-xs opacity-60">
                  {new Date(entry.mtime).toLocaleString()}
                </div>
              </div>
              <span className="shrink-0 text-xs opacity-80">{formatBytes(entry.size)}</span>
            </li>
          ))}
        </ul>
      )}

      {!loading && trash && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-sm opacity-80">
            {entries.length} {entries.length === 1 ? "entry" : "entries"} · {formatBytes(totalSize)}
          </span>
          <button
            type="button"
            className="text-sm px-3 py-2 rounded-md bg-red-600 text-white disabled:opacity-60"
            onClick={() => setConfirming(true)}
            disabled={entries.length === 0}
          >
            Empty trash
          </button>
        </div>
      )}

      {purgeResult && (
        <div className="rounded-md border border-panel-strong p-3 text-sm">
          <div>
            {purgeResult.purged} {purgeResult.purged === 1 ? "entry" : "entries"} removed (
            {formatBytes(purgeResult.bytes)})
          </div>
          {purgeResult.failed.length > 0 && (
            <div className="mt-1 text-xs text-red-400">
              {purgeResult.failed.map((message, index) => (
                <div key={index} className="break-all">{message}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {confirming && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="trash-purge-title"
        >
          <div className="bg-panel-strong rounded-lg shadow-2xl w-full max-w-md flex flex-col">
            <div className="border-b border-panel px-4 py-3">
              <h2 id="trash-purge-title" className="text-lg font-semibold">Empty the trash?</h2>
            </div>
            <div className="px-4 py-3 flex flex-col gap-2 text-sm">
              <p>
                This permanently deletes {entries.length} {entries.length === 1 ? "entry" : "entries"}{" "}
                ({formatBytes(totalSize)}) from the server. It cannot be undone and nothing can be
                restored afterwards.
              </p>
              <p className="opacity-70">
                Only the contents of the trash folder are removed; your library is not touched.
              </p>
              {error && <p className="text-red-400">{error}</p>}
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-panel px-4 py-3">
              <button
                type="button"
                className="px-3 py-2 rounded-md border border-panel-strong text-sm disabled:opacity-60"
                onClick={() => setConfirming(false)}
                disabled={purging}
              >
                Cancel
              </button>
              <button
                type="button"
                className="flex items-center gap-1.5 px-3 py-2 rounded-md bg-red-600 text-white text-sm disabled:opacity-60"
                onClick={() => void purge()}
                disabled={purging}
              >
                <Trash2 className="h-3.5 w-3.5" />
                {purging ? "Emptying…" : "Empty trash permanently"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
