import { useEffect, useRef, type KeyboardEvent, type ReactElement } from "react";
import { X } from "lucide-react";

import { fileUrl, type Asset } from "../../lib/api";
import { isImageAsset } from "../../lib/assetKinds";

const FOCUS_VISIBLE =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const BUTTON_ICON = `inline-flex items-center justify-center rounded-md border border-panel-strong p-1.5 text-muted transition-colors hover:bg-panel-soft hover:text-foreground disabled:opacity-60 ${FOCUS_VISIBLE}`;
const BUTTON_SECONDARY = `inline-flex items-center gap-1.5 rounded-md border border-panel-strong px-3 py-2 text-sm transition-colors hover:bg-panel-soft disabled:opacity-60 ${FOCUS_VISIBLE}`;

type Props = {
  images: Asset[];
  onInsert: (asset: Asset) => void;
  onClose: () => void;
};

/**
 * Picks one of the project's image members for the description. Same shape as
 * the add-files picker in `ProjectLanding`: an inline, non-portaled overlay
 * that owns Escape and hands focus straight to the first action.
 */
export default function ImagePickerDialog({ images, onInsert, onClose }: Props): ReactElement {
  const panelRef = useRef<HTMLDivElement | null>(null);

  // The editor passes the project's image members, but filtering here keeps the
  // dialog honest if a caller forwards every member instead.
  const insertable = images.filter(isImageAsset);

  useEffect(() => {
    const target =
      panelRef.current?.querySelector<HTMLButtonElement>("[data-image-insert]") ??
      panelRef.current?.querySelector<HTMLButtonElement>("[data-image-close]");
    target?.focus();
  }, []);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="insert-image-title"
      onKeyDown={handleKeyDown}
    >
      <div
        ref={panelRef}
        className="flex max-h-full w-full max-w-lg flex-col rounded-lg bg-panel-strong shadow-2xl"
      >
        <div className="flex items-center justify-between gap-2 border-b border-panel px-4 py-3">
          <h2 id="insert-image-title" className="truncate text-lg font-semibold">
            Insert an image
          </h2>
          <button
            type="button"
            aria-label="Close"
            data-image-close=""
            className={BUTTON_ICON}
            onClick={onClose}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
          {insertable.length === 0 ? (
            <div className="py-6 text-center">
              <p className="text-sm text-muted">This project has no image members yet.</p>
              <p className="mt-1 text-xs text-muted">
                Files you add to the project appear here.
              </p>
            </div>
          ) : (
            <ul className="flex flex-col">
              {insertable.map(asset => (
                <li key={asset.id} className="flex min-w-0 items-center gap-3 py-2">
                  <img
                    src={fileUrl(asset.thumb_url || asset.url)}
                    alt=""
                    loading="lazy"
                    className="h-10 w-10 shrink-0 rounded-md border border-panel object-cover"
                  />
                  <span className="min-w-0 flex-1 truncate text-sm">{asset.name}</span>
                  <button
                    type="button"
                    data-image-insert=""
                    className={`shrink-0 ${BUTTON_SECONDARY}`}
                    onClick={() => onInsert(asset)}
                  >
                    Insert {asset.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
