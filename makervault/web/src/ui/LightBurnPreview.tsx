import { useEffect, useRef, useState } from "react";

import { formatBytes } from "../lib/format";
import {
  DEFAULT_LIGHTBURN_LIMITS,
  LIGHTBURN_MAX_BYTES,
  LIGHTBURN_WARN_BYTES,
  REDUCED_LIGHTBURN_LIMITS,
  type LightBurnModel,
} from "../lib/lightBurn/parse";
import { parseLightBurnInWorker } from "../lib/lightBurn/parseInWorker";
import { lightBurnUrlCache } from "../lib/lightBurn/urlCache";
import type { PreviewSettings } from "../lib/settings";

type LightBurnPreviewProps = {
  url: string;
  assetId?: string;
  filename: string;
  imgClass: string;
  size?: number;
  variant?: "card" | "modal";
  mode?: PreviewSettings["mode"];
};

type PreviewState = "waiting" | "loading" | "blocked" | "disabled" | "error" | "ready";

const MODEL_CACHE_LIMIT = 8;
const FALLBACK_LAYER_COLOR = "#9CA3AF";

/**
 * Parsed models only. Object URLs live exclusively in `lightBurnUrlCache` so a
 * cache eviction can never leave a dangling blob URL in memory.
 */
const modelCache = new Map<string, LightBurnModel>();

function readModel(key: string): LightBurnModel | undefined {
  const model = modelCache.get(key);
  if (!model) return undefined;
  // Touch so the oldest untouched entry is evicted first.
  modelCache.delete(key);
  modelCache.set(key, model);
  return model;
}

function writeModel(key: string, model: LightBurnModel): void {
  if (modelCache.has(key)) modelCache.delete(key);
  modelCache.set(key, model);
  while (modelCache.size > MODEL_CACHE_LIMIT) {
    const oldest = modelCache.keys().next().value;
    if (oldest === undefined) break;
    modelCache.delete(oldest);
  }
}

export function clearLightBurnModelCacheForTests(): void {
  modelCache.clear();
}

function cacheKeyFor(url: string, assetId?: string): string {
  return assetId ? `asset:${assetId}` : url;
}

function contentLengthOf(response: Response): number | null {
  const header = response.headers?.get("content-length");
  if (!header) return null;
  const parsed = Number.parseInt(header, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

export default function LightBurnPreview({
  url,
  assetId,
  filename,
  imgClass,
  size,
  variant = "card",
  mode = "automatic",
}: LightBurnPreviewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cacheKey = cacheKeyFor(url, assetId);
  const isModal = variant === "modal";
  const sizeTooLarge = size != null && size > LIGHTBURN_MAX_BYTES;
  const sizeWarns = size != null && size > LIGHTBURN_WARN_BYTES && !sizeTooLarge;
  const modeDisabled = !isModal && mode === "disabled";
  const onDemand = !isModal && mode === "on-demand";

  const [shouldLoad, setShouldLoad] = useState(false);
  const [state, setState] = useState<PreviewState>("waiting");
  const [model, setModel] = useState<LightBurnModel | null>(null);
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null);
  const [largeFromBytes, setLargeFromBytes] = useState(false);
  const [hiddenLayers, setHiddenLayers] = useState<Set<number>>(() => new Set());

  const largeFile = sizeWarns || largeFromBytes;

  // Lazy gate: cards honour the 3D preview mode, modals always auto-load.
  useEffect(() => {
    if (sizeTooLarge || modeDisabled || onDemand) {
      setShouldLoad(false);
      return;
    }
    if (readModel(cacheKey)) {
      setShouldLoad(true);
      return;
    }
    if (isModal || typeof IntersectionObserver === "undefined" || !containerRef.current) {
      setShouldLoad(true);
      return;
    }
    const observer = new IntersectionObserver(
      entries => {
        if (!entries.some(entry => entry.isIntersecting)) return;
        observer.disconnect();
        setShouldLoad(true);
      },
      { rootMargin: "240px" },
    );
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [cacheKey, sizeTooLarge, modeDisabled, onDemand, isModal]);

  // Fetch and parse once, then reuse the model across remounts.
  useEffect(() => {
    if (!shouldLoad) return;
    let alive = true;

    const cached = readModel(cacheKey);
    if (cached) {
      setModel(cached);
      setState("ready");
      return () => {
        alive = false;
      };
    }

    setModel(null);
    setThumbnailUrl(null);
    setLargeFromBytes(false);
    setState("loading");

    void (async () => {
      try {
        const response = await fetch(url);
        if (!alive) return;
        if (!response.ok) {
          throw new Error(`Preview fetch failed: ${response.status}`);
        }

        const declaredLength = contentLengthOf(response);
        if (declaredLength !== null && declaredLength > LIGHTBURN_MAX_BYTES) {
          setState("blocked");
          return;
        }

        const bytes = new Uint8Array(await response.arrayBuffer());
        if (!alive) return;
        if (bytes.length > LIGHTBURN_MAX_BYTES) {
          setState("blocked");
          return;
        }

        const large = sizeWarns || bytes.length > LIGHTBURN_WARN_BYTES;
        if (large) setLargeFromBytes(true);

        const parsed = await parseLightBurnInWorker(
          bytes,
          large ? REDUCED_LIGHTBURN_LIMITS : DEFAULT_LIGHTBURN_LIMITS,
        );
        if (!alive) return;

        writeModel(cacheKey, parsed);
        setModel(parsed);
        setState("ready");
      } catch (err) {
        if (!alive) return;
        console.warn("LightBurn preview failed:", err);
        setState("error");
      }
    })();

    return () => {
      alive = false;
    };
  }, [shouldLoad, cacheKey, url, sizeWarns]);

  // The file's own hidden flags seed the layer toggles.
  useEffect(() => {
    if (!model) {
      setHiddenLayers(new Set());
      return;
    }
    setHiddenLayers(new Set(model.layers.filter(layer => layer.isHidden).map(layer => layer.index)));
  }, [model]);

  // Only the raster fallback needs an object URL; release it on unmount. A
  // vector render never allocates one, even when a thumbnail is present.
  const usesVectorPreview = Boolean(model && model.paths.length > 0 && model.bounds);
  useEffect(() => {
    const thumbnail = model?.thumbnail;
    if (!thumbnail || usesVectorPreview) {
      setThumbnailUrl(null);
      return;
    }
    const handle = lightBurnUrlCache.acquire(`${cacheKey}:thumb`, () =>
      URL.createObjectURL(new Blob([thumbnail.data], { type: thumbnail.mime })),
    );
    setThumbnailUrl(handle.url);
    return () => {
      handle.release();
    };
  }, [model, cacheKey, usesVectorPreview]);

  let displayState: PreviewState = state;
  if (sizeTooLarge || state === "blocked") displayState = "blocked";
  else if (modeDisabled) displayState = "disabled";
  else if (model) displayState = "ready";

  const showOnDemandButton = onDemand && !shouldLoad && !sizeTooLarge && !modeDisabled;
  const visiblePaths = model
    ? model.paths.filter(path => !hiddenLayers.has(path.layer))
    : [];

  function toggleLayer(index: number) {
    setHiddenLayers(previous => {
      const next = new Set(previous);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function renderPreview() {
    if (displayState === "blocked") {
      const label = size != null
        ? `File is too large to preview (${formatBytes(size)}).`
        : "File is too large to preview.";
      return <span className="px-3 text-center text-xs text-muted">{label} Download it instead.</span>;
    }
    if (displayState === "disabled") {
      return <span className="text-xs text-muted">Preview generation disabled</span>;
    }
    if (model) {
      if (model.paths.length > 0 && model.bounds) {
        const { minX, minY, maxX, maxY } = model.bounds;
        const width = Math.max(0.001, maxX - minX);
        const height = Math.max(0.001, maxY - minY);
        const colors = new Map(model.layers.map(layer => [layer.index, layer.color]));
        return (
          <svg
            viewBox={`${minX} ${minY} ${width} ${height}`}
            preserveAspectRatio="xMidYMid meet"
            className="h-full w-full"
            role="img"
            aria-label={filename}
          >
            {visiblePaths.map((path, index) => (
              <path
                key={`${path.layer}-${index}`}
                d={path.d}
                fill="none"
                stroke={colors.get(path.layer) ?? FALLBACK_LAYER_COLOR}
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
                strokeLinejoin="round"
                data-layer={path.layer}
              />
            ))}
          </svg>
        );
      }
      if (model.thumbnail && thumbnailUrl) {
        return (
          <img
            src={thumbnailUrl}
            alt={filename}
            decoding="async"
            className={imgClass}
          />
        );
      }
      return <span className="text-xs text-muted">Preview unavailable</span>;
    }
    if (showOnDemandButton) {
      return (
        <button
          type="button"
          className="rounded-md border border-panel-strong px-3 py-2 text-xs font-medium hover:bg-panel-strong"
          onClick={event => {
            event.stopPropagation();
            setShouldLoad(true);
          }}
        >
          Generate preview
        </button>
      );
    }
    if (displayState === "loading") {
      return <span className="text-xs text-muted">Generating preview...</span>;
    }
    if (displayState === "error") {
      return <span className="text-xs text-muted">Preview unavailable</span>;
    }
    return <span className="text-xs text-muted">Waiting to generate preview...</span>;
  }

  const showPanel = isModal && !sizeTooLarge && (largeFile || model?.truncated || Boolean(model?.layers.length));

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full bg-panel-soft flex flex-col overflow-hidden rounded-md"
    >
      <div className="relative flex-1 min-h-0 flex items-center justify-center overflow-hidden">
        {renderPreview()}
        {largeFile && !isModal && (
          <span className="absolute right-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white">
            Large file ({size != null ? formatBytes(size) : "this file"}) — showing a simplified preview
          </span>
        )}
      </div>
      {showPanel && (
        <div className="border-t border-panel px-3 py-2 text-xs">
          {largeFile && (
            <p className="mb-1 text-muted">
              Large file ({size != null ? formatBytes(size) : "this file"}) — showing a simplified preview
            </p>
          )}
          {model?.truncated && (
            <p className="mb-1 text-muted">Preview simplified to keep the UI responsive.</p>
          )}
          {model && model.layers.length > 0 && (
            <ul className="flex flex-wrap gap-x-4 gap-y-1">
              {[...model.layers]
                .sort((a, b) => a.index - b.index)
                .map(layer => {
                  const visible = !hiddenLayers.has(layer.index);
                  return (
                    <li key={layer.index}>
                      <label className="flex items-center gap-1.5">
                        <input
                          type="checkbox"
                          className="accent-accent"
                          checked={visible}
                          aria-label={layer.name}
                          onChange={() => toggleLayer(layer.index)}
                        />
                        <span
                          className="h-3 w-3 shrink-0 rounded-sm border border-panel-strong"
                          style={{ backgroundColor: layer.color }}
                        />
                        <span className="truncate">{layer.name}</span>
                        <span className="text-muted">{layer.kind}</span>
                        {layer.isTool && (
                          <span className="rounded bg-accent px-1 text-[10px] text-white">Tool</span>
                        )}
                      </label>
                    </li>
                  );
                })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
