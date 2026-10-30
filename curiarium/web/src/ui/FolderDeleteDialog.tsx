import { useEffect, useState } from "react";
import {
  UnauthorizedError,
  deleteFolder,
  getFolderDeletePreview,
  type FolderDeletePreview,
  type FolderDeleteResult,
} from "../lib/api";
import { formatBytes } from "../lib/format";

type Props = {
  folder: { id: string; name: string };
  onCancel: () => void;
  onDeleted: (result: FolderDeleteResult) => void;
  onUnauthorized?: () => void;
};

function errorMessage(err: unknown, fallback: string) {
  if (err instanceof Error && err.message.trim()) return err.message;
  return fallback;
}

export default function FolderDeleteDialog({ folder, onCancel, onDeleted, onUnauthorized }: Props) {
  const [preview, setPreview] = useState<FolderDeletePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setPreviewError(null);
    getFolderDeletePreview(folder.id)
      .then(data => {
        if (active) setPreview(data);
      })
      .catch(err => {
        if (!active) return;
        if (err instanceof UnauthorizedError) {
          onUnauthorized?.();
          return;
        }
        setPreviewError(errorMessage(err, "Unable to load what would be deleted."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [folder.id, onUnauthorized]);

  const notice = preview?.snapshot ?? null;
  const canDelete = !busy
    && !loading
    && !previewError
    && preview !== null
    && !preview.in_trash
    && notice?.action !== "refuse"
    && typed.trim() === folder.name;

  const confirmDelete = async () => {
    if (!canDelete) return;
    setBusy(true);
    setError(null);
    try {
      const result = await deleteFolder(folder.id, folder.name);
      onDeleted(result);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      // The server rejects a missing/wrong confirm_name with a 400; show it here.
      setError(errorMessage(err, "Failed to delete folder."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="folder-delete-title"
    >
      <div className="bg-panel-strong rounded-lg shadow-2xl w-full max-w-lg flex flex-col">
        <div className="border-b border-panel px-4 py-3">
          <h2 id="folder-delete-title" className="text-lg font-semibold">
            Delete folder “{folder.name}”?
          </h2>
        </div>

        <div className="px-4 py-3 flex flex-col gap-3 text-sm">
          <p>
            This permanently removes the folder and everything inside it: its subfolders
            and their files, plus every asset recorded in the library for this subtree.
          </p>
          <p className="opacity-80">
            The files are first moved to the server&apos;s <code>.trash</code> folder, so
            nothing is freed yet. Bytes are only deleted for good when someone runs
            <strong> Empty trash</strong> in Settings → Storage.
          </p>
          <p className="opacity-80">
            Restoring is file-level only: move the folder back from <code>.trash</code> by
            hand and rescan the storage folder. The files come back; their metadata (names,
            tags, notes, prepared-print details) does not.
          </p>

          {loading && <p className="opacity-70">Checking what would be deleted…</p>}

          {preview && (
            <div className="rounded-md border border-dashed border-panel-strong p-3 text-xs">
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <span>{preview.folders} folder{preview.folders === 1 ? "" : "s"}</span>
                <span>{preview.assets} tracked asset{preview.assets === 1 ? "" : "s"}</span>
                <span>{preview.files} file{preview.files === 1 ? "" : "s"}</span>
                <span>{formatBytes(preview.bytes)}</span>
              </div>
              <p className="mt-2 opacity-70">
                Untracked files sitting in this directory are moved with it and are not
                counted here.
              </p>
            </div>
          )}

          {preview?.in_trash && (
            <p className="text-red-400">This folder is already in the trash.</p>
          )}

          {notice?.action === "snapshot" && (
            <p className="opacity-80">
              A filesystem snapshot of this folder is taken before it moves, named like{" "}
              <code>{notice.pattern}</code>. The exact name is recorded in the audit log.
              {notice.policy === "strict"
                ? " If the snapshot cannot be taken, the delete is refused and nothing is removed."
                : " If the snapshot cannot be taken, the delete goes ahead without one and the miss is recorded in the audit log."}
            </p>
          )}
          {notice?.action === "proceed_without" && (
            <p className="opacity-80">
              No snapshot can be taken on this storage volume{notice.detail ? `, because ${notice.detail}` : ""}.
              {" The delete still goes ahead and the missed snapshot is recorded in the audit log."}
            </p>
          )}
          {notice?.action === "refuse" && (
            <p className="text-red-400">
              This storage volume cannot take snapshots, and this deployment refuses a folder
              delete without one. Nothing will be deleted.
            </p>
          )}

          {previewError && <p className="text-red-400">{previewError}</p>}
          {error && <p className="text-red-400">{error}</p>}

          <label className="flex flex-col gap-1">
            <span>
              Type <strong>{folder.name}</strong> to confirm
            </span>
            <input
              aria-label="Type the folder name to confirm"
              className="px-3 py-2 rounded-md border border-panel-strong bg-panel-soft disabled:opacity-60"
              value={typed}
              onChange={e => setTyped(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter") void confirmDelete();
              }}
              disabled={busy || loading || !preview || preview.in_trash}
              autoFocus
            />
          </label>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-panel px-4 py-3">
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
            {busy ? "Deleting…" : "Delete folder"}
          </button>
        </div>
      </div>
    </div>
  );
}
