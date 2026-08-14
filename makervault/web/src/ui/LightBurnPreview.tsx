import React, { useEffect, useRef, useState } from "react";
import {
  Asset,
  requestPreviewRetry,
  updatePreviewState,
  uploadGeneratedThumbnail,
} from "../lib/api";
import {
  PreviewJobError,
  PreviewQueueFullError,
  createLightBurnPreviewJob,
  type PreviewJobHandle,
} from "../lib/previewJobs";

type PreviewState = "idle" | "queued" | "loading" | "failed" | "skipped";

type LightBurnPreviewProps = {
  url: string;
  assetId?: string;
  byteSize?: number;
  filename: string;
  imgClass: string;
  mode?: "automatic" | "on-demand";
  previewStatus?: Asset["preview_status"];
  previewReason?: string | null;
  onAssetChanged?: (asset: Asset) => void;
};

const previewCache = new Map<string, string>();

const reasonLabel = (reason?: string | null) => {
  if (reason === "file_too_large") {
    return "This file is too large for an automatic preview.";
  }
  if (reason === "archive_entries" || reason === "archive_expanded") {
    return "This LightBurn archive is too complex for an automatic preview.";
  }
  if (reason === "timeout") return "LightBurn preview generation timed out.";
  return "MakersVault could not read this LightBurn preview.";
};

export default function LightBurnPreview({
  url,
  assetId,
  byteSize,
  filename,
  imgClass,
  mode = "automatic",
  previewStatus = "pending",
  previewReason,
  onAssetChanged,
}: LightBurnPreviewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [state, setState] = useState<PreviewState>(
    previewStatus === "failed"
      ? "failed"
      : previewStatus === "skipped_policy"
        ? "skipped"
        : "idle",
  );
  const [reason, setReason] = useState(previewReason || null);
  const [requested, setRequested] = useState(
    previewStatus === "retry_requested" || (mode === "automatic" && previewStatus === "pending"),
  );
  const [queueAttempt, setQueueAttempt] = useState(0);

  useEffect(() => {
    setReason(previewReason || null);
    if (previewStatus === "failed") {
      setState("failed");
      setRequested(false);
    } else if (previewStatus === "skipped_policy") {
      setState("skipped");
      setRequested(false);
    } else if (previewStatus === "retry_requested" || (mode === "automatic" && previewStatus === "pending")) {
      setRequested(true);
    }
  }, [mode, previewStatus, previewReason]);

  useEffect(() => {
    let disposed = false;
    let observer: IntersectionObserver | null = null;
    let retryTimer = 0;
    let job: PreviewJobHandle<Blob> | null = null;
    const cacheKey = assetId ? `asset:${assetId}` : url;
    const cached = previewCache.get(cacheKey);
    if (cached) {
      setPreview(cached);
      setState("idle");
      return;
    }

    const load = async () => {
      setState("queued");
      try {
        job = await createLightBurnPreviewJob({
          url,
          byteSize,
          onStart: async () => {
            if (disposed) return;
            setState("loading");
            if (!assetId) return;
            try {
              onAssetChanged?.(await updatePreviewState(assetId, { status: "pending" }));
            } catch (error) {
              console.warn("LightBurn preview start state could not be persisted:", error);
            }
          },
        });
        if (disposed) {
          job.cancel();
          return;
        }
        const blob = await job.promise;
        if (disposed) return;
        const objectUrl = URL.createObjectURL(blob);
        previewCache.set(cacheKey, objectUrl);
        setPreview(objectUrl);
        setState("idle");
        setReason(null);
        if (assetId) {
          try {
            onAssetChanged?.(await uploadGeneratedThumbnail(assetId, blob));
          } catch (error) {
            console.warn("Generated LightBurn preview could not be persisted:", error);
          }
        }
      } catch (error) {
        if (disposed) return;
        if (error instanceof PreviewQueueFullError) {
          retryTimer = window.setTimeout(() => setQueueAttempt(value => value + 1), 350);
          return;
        }
        if (error instanceof PreviewJobError && error.reason === "cancelled") return;
        const previewError = error instanceof PreviewJobError
          ? error
          : new PreviewJobError("malformed_lightburn", "LightBurn preview generation failed");
        setState(previewError.skipped ? "skipped" : "failed");
        setReason(previewError.reason);
        setRequested(false);
        if (assetId) {
          try {
            onAssetChanged?.(await updatePreviewState(assetId, {
              status: previewError.skipped ? "skipped_policy" : "failed",
              reason: previewError.reason,
            }));
          } catch (stateError) {
            console.warn("LightBurn preview state could not be persisted:", stateError);
          }
        }
      }
    };

    if (!requested || previewStatus === "failed" || previewStatus === "skipped_policy") return;
    if (typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(entries => {
        if (!entries.some(entry => entry.isIntersecting)) return;
        observer?.disconnect();
        void load();
      }, { rootMargin: "240px" });
      if (containerRef.current) observer.observe(containerRef.current);
    } else {
      void load();
    }

    return () => {
      disposed = true;
      observer?.disconnect();
      window.clearTimeout(retryTimer);
      job?.cancel();
    };
  }, [url, assetId, byteSize, previewStatus, requested, queueAttempt, onAssetChanged]);

  const retry = async (event: React.MouseEvent) => {
    event.stopPropagation();
    if (assetId) {
      try {
        onAssetChanged?.(await requestPreviewRetry(assetId));
      } catch (error) {
        console.warn("LightBurn preview retry could not be requested:", error);
        return;
      }
    }
    setReason(null);
    setRequested(true);
    setQueueAttempt(value => value + 1);
  };

  return (
    <div
      ref={containerRef}
      data-preview-state={preview ? "ready" : state}
      className="w-full h-full bg-panel-soft flex items-center justify-center rounded-md overflow-hidden"
    >
      {preview ? (
        <img src={preview} alt={filename} className={imgClass} />
      ) : state === "loading" ? (
        <span className="text-xs text-muted">Generating preview...</span>
      ) : state === "queued" ? (
        <span className="text-xs text-muted">Preview queued</span>
      ) : state === "skipped" ? (
        <div className="px-4 text-center text-xs text-muted">
          <div className="font-semibold text-primary">Preview paused</div>
          <div className="mt-1">{reasonLabel(reason)}</div>
        </div>
      ) : state === "failed" ? (
        <div className="px-4 text-center text-xs text-muted">
          <div className="font-semibold text-primary">Preview unavailable</div>
          <div className="mt-1">{reasonLabel(reason)}</div>
          <button type="button" className="mt-2 underline underline-offset-2" onClick={retry}>
            Retry preview
          </button>
        </div>
      ) : mode === "on-demand" && !requested ? (
        <button
          type="button"
          className="rounded-md border border-panel-strong px-3 py-2 text-xs font-medium hover:bg-panel-strong"
          onClick={event => {
            event.stopPropagation();
            setRequested(true);
          }}
        >
          Generate preview
        </button>
      ) : (
        <span className="text-xs text-muted">Preview unavailable</span>
      )}
    </div>
  );
}
