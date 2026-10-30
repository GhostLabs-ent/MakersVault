import { useState } from "react";

import type { BatchMetaChange } from "../lib/api";
import { normaliseCreator, normaliseNotes } from "../lib/metadataValidation";

type Props = {
  open: boolean;
  /** How many selected rows the change applies to. */
  count: number;
  busy: boolean;
  /** Request-level failure (network, sign-out); per-asset failures stay in the bar. */
  requestError?: string | null;
  onCancel: () => void;
  onSubmit: (change: BatchMetaChange) => void;
};

/**
 * In-app batch creator/notes editor. Every field starts "leave unchanged":
 * only fields the user actually edited (or explicitly cleared) appear in the
 * payload, so an absent key can never overwrite a value the user did not see.
 */
export default function BulkMetaDialog({
  open,
  count,
  busy,
  requestError,
  onCancel,
  onSubmit,
}: Props) {
  const [creatorValue, setCreatorValue] = useState("");
  const [notesValue, setNotesValue] = useState("");
  const [creatorTouched, setCreatorTouched] = useState(false);
  const [notesTouched, setNotesTouched] = useState(false);
  const [clearCreator, setClearCreator] = useState(false);
  const [clearNotes, setClearNotes] = useState(false);

  if (!open) return null;

  const creator = normaliseCreator(creatorValue);
  const notes = normaliseNotes(notesValue);
  const creatorError = !clearCreator && creatorTouched ? creator.error : null;
  const notesError = !clearNotes && notesTouched ? notes.error : null;

  const creatorChanged = clearCreator || (creatorTouched && creator.value !== null);
  const notesChanged = clearNotes || (notesTouched && notes.value !== null);
  const canSave = !busy && (creatorChanged || notesChanged) && !creatorError && !notesError;

  const submit = () => {
    if (!canSave) return;
    const change: BatchMetaChange = {};
    if (clearCreator) change.creator = null;
    else if (creatorChanged) change.creator = creator.value;
    if (clearNotes) change.notes = null;
    else if (notesChanged) change.notes = notes.value;
    onSubmit(change);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="bulk-meta-title"
    >
      <div className="bg-panel-strong rounded-lg shadow-2xl w-full max-w-lg flex flex-col">
        <div className="border-b border-panel px-4 py-3">
          <h2 id="bulk-meta-title" className="text-lg font-semibold">
            Edit metadata for {count} selected item{count === 1 ? "" : "s"}
          </h2>
        </div>

        <div className="px-4 py-3 flex flex-col gap-3 text-sm">
          <p className="opacity-80">
            Leave a field blank to leave it unchanged. Tick &quot;Clear&quot; to remove the
            stored value.
          </p>

          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-muted">Creator</span>
            <input
              aria-label="Creator"
              value={creatorValue}
              onChange={e => {
                setCreatorValue(e.target.value);
                setCreatorTouched(true);
              }}
              disabled={busy || clearCreator}
              placeholder="Designer or source"
              className="w-full rounded-md border border-panel-strong bg-panel-soft px-2 py-1.5 disabled:opacity-60"
            />
            {creatorError && (
              <p role="alert" className="text-xs text-red-700 dark:text-red-300">
                {creatorError}
              </p>
            )}
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={clearCreator}
              onChange={e => setClearCreator(e.target.checked)}
              disabled={busy}
              className="w-4 h-4"
            />
            <span>Clear creator</span>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-muted">Notes</span>
            <textarea
              aria-label="Notes"
              value={notesValue}
              onChange={e => {
                setNotesValue(e.target.value);
                setNotesTouched(true);
              }}
              disabled={busy || clearNotes}
              placeholder="Add some details about these assets"
              className="w-full min-h-[80px] rounded-md border border-panel-strong bg-panel-soft p-2 disabled:opacity-60"
            />
            {notesError && (
              <p role="alert" className="text-xs text-red-700 dark:text-red-300">
                {notesError}
              </p>
            )}
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={clearNotes}
              onChange={e => setClearNotes(e.target.checked)}
              disabled={busy}
              className="w-4 h-4"
            />
            <span>Clear notes</span>
          </label>

          {requestError && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-300">
              {requestError}
            </p>
          )}
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
            className="px-3 py-2 rounded-md bg-accent text-sm disabled:opacity-60"
            onClick={submit}
            disabled={!canSave}
          >
            {busy ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
