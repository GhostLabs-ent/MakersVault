import React from "react";
import { type Asset, type PreparedPrint, fileUrl } from "../../lib/api";
import { formatBytes } from "../../lib/format";
import type { PreviewSettings, ResolvedTheme } from "../../lib/settings";
import { useFileGrants } from "../../lib/useFileGrants";
import FileDownloadLink from "../FileDownloadLink";
import LightBurnPreview from "../LightBurnPreview";
import TagBadge from "../TagBadge";
import {
  LIGHTBURN_EXTS,
  MODEL_EXTS,
  extOf,
  type PreviewVariant,
} from "./assetGridMeta";

// Three.js is the single largest dependency in the app and only 3D assets need
// it, so the viewer and the snapshot renderer are fetched on demand. Both live
// in `../ModelViewer`; the named export is adapted to `lazy`'s default-export
// contract.
const ModelViewer = React.lazy(() => import("../ModelViewer"));
const ModelSnapshot = React.lazy(() =>
  import("../ModelViewer").then((module) => ({ default: module.ModelSnapshot })),
);

/** Visible stand-in while a lazily loaded 3D chunk is on the wire. */
export function PreviewLoading({ label = "Loading 3D preview…" }: { label?: string }) {
  return <div className="flex h-full w-full items-center justify-center text-xs text-muted">{label}</div>;
}

function formatPreparedDuration(totalSeconds?: number | null) {
  if (!totalSeconds || totalSeconds < 1) return null;
  const roundedMinutes = Math.max(1, Math.round(totalSeconds / 60));
  const days = Math.floor(roundedMinutes / 1440);
  const hours = Math.floor((roundedMinutes % 1440) / 60);
  const minutes = roundedMinutes % 60;
  return [
    days ? `${days}d` : "",
    hours ? `${hours}h` : "",
    minutes ? `${minutes}m` : "",
  ].filter(Boolean).join(" ");
}

/** Mirrors the backend's literal marker for an undetected slicer. */
const UNKNOWN_SLICER = "unknown";

function nonEmptyString(value?: string | null) {
  if (typeof value !== "string") return null;
  return value.trim() || null;
}

function preparedTitle(prepared: PreparedPrint) {
  const printer = nonEmptyString(prepared.printer);
  return printer ? `Prepared for ${printer}` : "Prepared print";
}

function preparedSlicer(prepared: PreparedPrint) {
  const slicer = nonEmptyString(prepared.slicer);
  if (!slicer || slicer === UNKNOWN_SLICER) return "Unknown slicer";
  return slicer;
}

function preparedMaterial(prepared: PreparedPrint) {
  return nonEmptyString(prepared.material) ?? "Unknown material";
}

function preparedNozzle(prepared: PreparedPrint) {
  const nozzle = prepared.nozzle_mm;
  if (typeof nozzle !== "number" || !Number.isFinite(nozzle)) return "Unknown nozzle";
  return `${nozzle} mm`;
}

function preparedTime(prepared: PreparedPrint) {
  return formatPreparedDuration(prepared.estimated_seconds) ?? "Unknown time";
}

export function PreparedPrintSummary({
  prepared,
  onClear,
  clearing = false,
}: {
  prepared: PreparedPrint;
  onClear?: () => void;
  clearing?: boolean;
}) {
  // Fixed four-slot layout: missing facts render as placeholders so the line
  // never reflows when a payload is partially populated.
  const facts = [
    preparedSlicer(prepared),
    preparedMaterial(prepared),
    preparedNozzle(prepared),
    preparedTime(prepared),
  ];
  return (
    <div className="flex items-start justify-between gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-2 text-xs text-emerald-950 dark:text-emerald-100">
      <span>
        <span className="font-semibold">{preparedTitle(prepared)}</span>
        <span> · {facts.join(" · ")}</span>
      </span>
      {onClear && (
        <button type="button" className="shrink-0 underline-offset-2 hover:underline disabled:opacity-60" onClick={onClear} disabled={clearing}>
          {clearing ? "Clearing..." : "Clear"}
        </button>
      )}
    </div>
  );
}

export function renderPreviewContent(
  asset: Asset,
  variant: PreviewVariant,
  theme: ResolvedTheme,
  previewMode: PreviewSettings["mode"] = "automatic"
) {
  const ext = extOf(asset.filename);
  const assetUrl = fileUrl(asset.url);
  const thumbUrl = asset.thumb_url ? fileUrl(asset.thumb_url) : null;
  const imgClass =
    variant === "card"
      ? "w-full h-full object-cover"
      : "w-full h-full object-contain bg-panel-strong";
  const is3d = MODEL_EXTS.has(ext);
  const isLightBurn = LIGHTBURN_EXTS.has(ext);

  if (variant === "card") {
    if (thumbUrl) {
      return <img src={thumbUrl} alt={asset.filename} loading="lazy" decoding="async" className={imgClass} />;
    }
    if (ext === "svg") {
      return <img src={assetUrl} alt={asset.filename} loading="lazy" decoding="async" className={imgClass} />;
    }
    if (is3d) {
      if (previewMode === "disabled") {
        return <div className="flex h-full w-full items-center justify-center text-xs text-muted">Preview generation disabled</div>;
      }
      return (
        <React.Suspense fallback={<PreviewLoading />}>
          <ModelSnapshot url={assetUrl} ext={ext} assetId={asset.id} theme={theme} mode={previewMode} />
        </React.Suspense>
      );
    }
    if (isLightBurn) {
      return (
        <LightBurnPreview
          url={assetUrl}
          assetId={asset.id}
          filename={asset.filename}
          imgClass={imgClass}
          size={asset.size}
          variant="card"
          mode={previewMode}
        />
      );
    }
    return (
      <div className="flex items-center justify-center w-full h-full text-sm opacity-60">
        No preview
      </div>
    );
  }

  if (is3d) {
    return (
      <React.Suspense fallback={<PreviewLoading />}>
        <ModelViewer key={`${variant}-${asset.id}`} url={assetUrl} ext={ext} assetId={asset.id} theme={theme} />
      </React.Suspense>
    );
  }
  if (thumbUrl || ext === "svg") {
    const src = thumbUrl || assetUrl;
    return <img src={src} alt={asset.filename} decoding="async" className={imgClass} />;
  }
  if (isLightBurn) {
    return (
      <LightBurnPreview
        url={assetUrl}
        assetId={asset.id}
        filename={asset.filename}
        imgClass={imgClass}
        size={asset.size}
        variant="modal"
      />
    );
  }
  return (
    <div className="flex items-center justify-center w-full h-full text-sm opacity-60">
      Preview unavailable
    </div>
  );
}

export function AssetPreviewModal({ asset, theme, onClose }: { asset: Asset; theme: ResolvedTheme; onClose: () => void }) {
  // Prime the preview's grants on open: a cold modal would otherwise fire an
  // unsigned <img>/<iframe>/model request and 401.
  const ready = useFileGrants([asset.url, asset.thumb_url]);
  const stop = (e: React.MouseEvent) => e.stopPropagation();
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="bg-panel-strong rounded-lg shadow-2xl max-w-5xl w-full max-h-full overflow-hidden flex flex-col"
        onClick={stop}
      >
        <div className="flex items-center justify-between border-b border-panel px-4 py-3">
          <div>
            <h2 className="text-lg font-semibold">{asset.name}</h2>
            <p className="text-sm opacity-70">
              {asset.filename} · {formatBytes(asset.size)}
            </p>
            {(asset.creator || asset.collection) && (
              <p className="text-xs text-muted">
                {[
                  asset.creator ? `By ${asset.creator}` : null,
                  asset.collection ? `Collection (legacy): ${asset.collection}` : null,
                ].filter(Boolean).join(" · ")}
              </p>
            )}
            {asset.prepared_print && (
              <div className="mt-2"><PreparedPrintSummary prepared={asset.prepared_print} /></div>
            )}
          </div>
          <button
            className="px-3 py-1 rounded-md border border-panel-strong text-sm"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        <div className="p-4 space-y-4 overflow-auto">
          <div className="w-full h-[70vh] min-h-[400px]">
            <div className="w-full h-full rounded-lg bg-panel-soft flex items-center justify-center overflow-hidden">
              {ready ? renderPreviewContent(asset, "modal", theme) : <p className="text-sm opacity-70">Preparing preview...</p>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {asset.tags.length ? (
              asset.tags.map(tag => <TagBadge key={tag} tag={tag} />)
            ) : (
              <span className="text-xs opacity-60">No tags</span>
            )}
          </div>
          {asset.notes && (
            <div className="text-sm border border-dashed border-panel-strong rounded-md p-3 whitespace-pre-wrap">
              {asset.notes}
            </div>
          )}
          <div className="flex gap-3">
            <FileDownloadLink
              className="px-3 py-2 rounded-md bg-accent text-sm"
              rel={asset.url}
              filename={asset.filename}
            >
              Download
            </FileDownloadLink>
            <button
              className="px-3 py-2 rounded-md border border-panel-strong text-sm"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
