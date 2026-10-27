import type { KeyboardEvent, ReactElement } from "react";

/**
 * A deferred confirmation: the grid stores one of these and renders a single
 * `<ConfirmDialog>` for it, so cards never own dialog state of their own.
 */
export type ConfirmRequest = {
  title: string;
  body?: string;
  confirmLabel?: string;
  danger?: boolean;
  run: () => void | Promise<void>;
};

type Props = {
  title: string;
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export default function ConfirmDialog({
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: Props): ReactElement {
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.key !== "Escape" || busy) return;
    onCancel();
  };

  const confirmClasses = danger
    ? "bg-red-600 text-white"
    : "bg-accent hover:bg-accent-strong";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      onKeyDown={handleKeyDown}
    >
      <div className="bg-panel-strong rounded-lg shadow-2xl w-full max-w-lg flex flex-col">
        <div className="border-b border-panel px-4 py-3">
          <h2 id="confirm-dialog-title" className="text-lg font-semibold">
            {title}
          </h2>
        </div>

        {body && (
          <div className="px-4 py-3 text-sm">
            <p>{body}</p>
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-panel px-4 py-3">
          <button
            type="button"
            className="px-3 py-2 rounded-md border border-panel-strong text-sm disabled:opacity-60"
            onClick={onCancel}
            disabled={busy}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`px-3 py-2 rounded-md text-sm disabled:opacity-60 ${confirmClasses}`}
            onClick={onConfirm}
            disabled={busy}
            autoFocus
          >
            {busy ? "Working..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
