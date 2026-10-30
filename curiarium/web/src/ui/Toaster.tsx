import type { ReactElement } from "react";
import { useSyncExternalStore } from "react";
import { X } from "lucide-react";

import { dismissToast, getToasts, subscribeToasts, type Toast } from "../lib/toast";

const ERROR_CARD_CLASSES =
  "rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/40 dark:text-red-300";
const INFO_CARD_CLASSES =
  "rounded-md border border-panel-strong bg-panel-strong px-3 py-2 text-sm shadow-lg";

function ToastCard({ toast }: { toast: Toast }) {
  const isError = toast.tone === "error";

  return (
    <div
      role={isError ? "alert" : "status"}
      className={`flex items-start justify-between gap-2 ${isError ? ERROR_CARD_CLASSES : INFO_CARD_CLASSES}`}
    >
      <div className="flex min-w-0 flex-col gap-1">
        <span>{toast.message}</span>

        {toast.details && toast.details.length > 0 && (
          <ul className="list-disc pl-4 opacity-80">
            {toast.details.map((detail, index) => (
              <li key={index}>{detail}</li>
            ))}
          </ul>
        )}

        {toast.actions && toast.actions.length > 0 && (
          <div className="flex gap-2 pt-1">
            {toast.actions.map(action => (
              <button
                key={action.label}
                type="button"
                className="underline-offset-2 hover:underline"
                onClick={() => void action.run()}
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <button
        type="button"
        aria-label="Dismiss"
        className="shrink-0 underline-offset-2 hover:underline"
        onClick={() => dismissToast(toast.id)}
      >
        <X size={14} />
      </button>
    </div>
  );
}

export default function Toaster(): ReactElement | null {
  const toasts = useSyncExternalStore(subscribeToasts, getToasts);

  if (toasts.length === 0) return null;

  return (
    <div
      data-testid="toaster"
      aria-live="polite"
      className="fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2"
    >
      {toasts.map(toast => (
        <ToastCard key={toast.id} toast={toast} />
      ))}
    </div>
  );
}
