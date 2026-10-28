import React, { useState } from "react";

import type { BatchFailure } from "../lib/api";

export type BulkActionBarProps = {
  count: number;
  folderOptions: { id: string | null; name: string }[];
  /** Project mode hides the move control: projects have no folders. */
  showFolderControls?: boolean;
  busy: { label: string; count: number } | null;
  failures: BatchFailure[] | null;
  failureLabels: { id: string; label: string; message: string }[];
  /** Request-level (not per-asset) error, e.g. the network died mid-bulk. */
  requestError?: string | null;
  onMove: (folderId: string | null) => void;
  onAddTags: (tags: string[]) => void;
  onRemoveTags: (tags: string[]) => void;
  /** Opens the project picker for the whole selection. */
  onAddToProject: () => void;
  onDownload: () => void;
  onDelete: () => void;
  onClear: () => void;
  onSelectAll: () => void;
  onDismissFailures: () => void;
};

/** Normalises a comma-separated tag draft the same way `TagInput` does. */
function parseTagList(raw: string): string[] {
  const out: string[] = [];
  for (const part of raw.split(",")) {
    const tag = part.trim().replace(/\s+/g, " ");
    if (!tag) continue;
    if (out.some(existing => existing.toLowerCase() === tag.toLowerCase())) continue;
    out.push(tag);
  }
  return out;
}

/**
 * Sticky bar for actions that apply to exactly the current selection.
 *
 * Presentational only: every action delegates to a caller-provided callback,
 * and the parent owns busy/error state. Delete delegates straight to
 * `onDelete`, which opens the caller's confirmation dialog: the stepped confirm
 * (and the typed name on the single-asset path) lives there, never in the bar.
 */
export default function BulkActionBar({
  count,
  folderOptions,
  showFolderControls = true,
  busy,
  failures,
  failureLabels,
  requestError,
  onMove,
  onAddTags,
  onRemoveTags,
  onAddToProject,
  onDownload,
  onDelete,
  onClear,
  onSelectAll,
  onDismissFailures,
}: BulkActionBarProps) {
  const [moveTarget, setMoveTarget] = useState("");
  const [tagDraft, setTagDraft] = useState("");

  const disabled = busy !== null;

  if (count <= 0) return null;

  const tags = parseTagList(tagDraft);

  const submitTags = (apply: (tags: string[]) => void) => {
    if (!tags.length) return;
    apply(tags);
    setTagDraft("");
  };

  return (
    <div
      data-testid="bulk-action-bar"
      className="sticky top-0 z-30 flex flex-col gap-3 rounded-lg border border-panel-strong bg-panel p-3 shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="font-medium">{count} selected</span>
        <span className="text-muted">
          These actions apply to exactly the {count} selected item{count === 1 ? "" : "s"}.
        </span>
        {busy && (
          <span role="status" className="text-accent">
            {busy.label} {busy.count} items…
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        {showFolderControls && (
          <>
            <select
              aria-label="Target folder"
              value={moveTarget}
              onChange={e => setMoveTarget(e.target.value)}
              disabled={disabled}
              className="px-2 py-1 rounded-md border border-panel-strong bg-panel-soft disabled:opacity-60"
            >
              {folderOptions.map(option => (
                <option key={option.id || "none"} value={option.id || ""}>
                  {option.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => onMove(moveTarget || null)}
              disabled={disabled}
              className="px-3 py-1 rounded-md border border-panel-strong disabled:opacity-60"
            >
              Move
            </button>
          </>
        )}

        <input
          aria-label="Tags"
          value={tagDraft}
          onChange={e => setTagDraft(e.target.value)}
          placeholder="tag-a, tag-b"
          disabled={disabled}
          className="px-2 py-1 rounded-md border border-panel-strong bg-panel-soft disabled:opacity-60"
        />
        <button
          type="button"
          onClick={() => submitTags(onAddTags)}
          disabled={disabled || !tags.length}
          className="px-3 py-1 rounded-md border border-panel-strong disabled:opacity-60"
        >
          Add tags
        </button>
        <button
          type="button"
          onClick={() => submitTags(onRemoveTags)}
          disabled={disabled || !tags.length}
          className="px-3 py-1 rounded-md border border-panel-strong disabled:opacity-60"
        >
          Remove tags
        </button>

        <button
          type="button"
          onClick={onAddToProject}
          disabled={disabled}
          className="px-3 py-1 rounded-md border border-panel-strong disabled:opacity-60"
        >
          Add to project…
        </button>

        <button
          type="button"
          onClick={onDownload}
          disabled={disabled}
          className="px-3 py-1 rounded-md border border-panel-strong disabled:opacity-60"
        >
          Download zip
        </button>

        <button
          type="button"
          onClick={onDelete}
          disabled={disabled}
          className="px-3 py-1 rounded-md border border-red-300 text-red-700 dark:text-red-300 disabled:opacity-60"
        >
          Delete
        </button>

        <button
          type="button"
          onClick={onSelectAll}
          disabled={disabled}
          className="px-3 py-1 rounded-md border border-panel-strong disabled:opacity-60"
        >
          Select all
        </button>
        <button
          type="button"
          onClick={onClear}
          disabled={disabled}
          className="px-3 py-1 rounded-md border border-panel-strong disabled:opacity-60"
        >
          Clear
        </button>
      </div>

      {requestError && (
        <div className="flex items-start justify-between gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
          <span role="alert">{requestError}</span>
          <button
            type="button"
            onClick={onDismissFailures}
            className="shrink-0 underline-offset-2 hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {failures && failures.length > 0 && (
        <div className="flex flex-col gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300">
          <div className="flex items-start justify-between gap-2">
            <span>The successful items were applied; nothing was retried.</span>
            <button
              type="button"
              onClick={onDismissFailures}
              className="shrink-0 underline-offset-2 hover:underline"
            >
              Dismiss
            </button>
          </div>
          <ul data-testid="bulk-failures" className="flex flex-col gap-1">
            {failures.map(failure => {
              const line = failureLabels.find(entry => entry.id === failure.id);
              return (
                <li key={failure.id} data-failed-id={failure.id}>
                  {line?.label ?? failure.id} — {line?.message ?? failure.error}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
