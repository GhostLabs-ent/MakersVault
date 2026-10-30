import { useEffect, useId, useState, type MouseEvent, type ReactElement } from "react";

import { assetFilePreviewUrl, type AssetFile } from "../../lib/api";
import { useFileGrants } from "../../lib/useFileGrants";
import FileDownloadLink from "../FileDownloadLink";
import { extOf } from "./assetGridMeta";
import Markdown from "../Markdown";

const MAX_INLINE_TEXT_BYTES = 1_000_000;

const IMAGE_MIMES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"]);
const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp"]);
const TEXT_EXTS = new Set([
  "txt",
  "md",
  "markdown",
  "csv",
  "log",
  "json",
  "html",
  "htm",
  "xml",
  "yaml",
  "yml",
]);

type PreviewKind = "pdf" | "image" | "text" | "unsupported";

/** Mime first, then the extension: servers often report `application/octet-stream`. */
function previewKind(file: AssetFile): PreviewKind {
  const mime = file.mime.toLowerCase();
  if (mime === "application/pdf") return "pdf";
  if (IMAGE_MIMES.has(mime)) return "image";
  if (
    mime.startsWith("text/") ||
    mime === "application/json" ||
    mime === "application/xml" ||
    mime === "application/yaml" ||
    mime === "application/x-yaml"
  ) {
    return "text";
  }

  const ext = extOf(file.filename);
  if (ext === "pdf") return "pdf";
  if (IMAGE_EXTS.has(ext)) return "image";
  if (TEXT_EXTS.has(ext)) return "text";
  return "unsupported";
}

type Props = {
  assetId: string;
  file: AssetFile;
  onClose: () => void;
};

/**
 * Read-only inline preview for one supporting file. The URL handed to the
 * iframe/image/fetch carries a short-lived file grant, minted by
 * `useFileGrants` before the first request — an unsigned URL would 401.
 */
export default function AssetFilePreview({ assetId, file, onClose }: Props): ReactElement {
  const titleId = useId();
  const kind = previewKind(file);
  const isMarkdown = kind === "text" && ["md", "markdown"].includes(extOf(file.filename));
  const tooLarge = kind === "text" && file.size > MAX_INLINE_TEXT_BYTES;
  // Prime before the fetch/iframe/image goes out, so none of them is unsigned.
  const ready = useFileGrants([file.url]);

  const [text, setText] = useState<string | null>(null);
  const [textError, setTextError] = useState<string | null>(null);
  const [textLoading, setTextLoading] = useState(kind === "text" && !tooLarge);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  useEffect(() => {
    if (kind !== "text" || tooLarge || !ready) return;
    const controller = new AbortController();
    let cancelled = false;
    setTextLoading(true);
    setText(null);
    setTextError(null);
    (async () => {
      try {
        const res = await fetch(assetFilePreviewUrl(file.url), { signal: controller.signal });
        if (!res.ok) throw new Error(`Failed to load preview (HTTP ${res.status})`);
        const body = await res.text();
        if (!cancelled) setText(body);
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        console.error(err);
        setTextError(err instanceof Error ? err.message : "Failed to load preview");
      } finally {
        if (!cancelled) setTextLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [assetId, file.url, kind, tooLarge, ready]);

  const stop = (event: MouseEvent) => event.stopPropagation();

  const renderBody = () => {
    if (kind === "pdf") {
      // No sandbox: Chrome's PDF viewer refuses embedded rendering inside one.
      // The server sends nosniff and refuses SVG, so the iframe stays inert.
      return (
        <iframe
          src={assetFilePreviewUrl(file.url)}
          title={file.filename}
          className="h-[70vh] w-full"
        />
      );
    }
    if (kind === "image") {
      return (
        <img
          src={assetFilePreviewUrl(file.url)}
          alt={file.filename}
          className="max-h-[70vh] max-w-full object-contain"
        />
      );
    }
    if (kind === "unsupported") {
      return <p className="text-sm opacity-70">Preview is not available for this file type.</p>;
    }
    if (tooLarge) {
      return (
        <p className="text-sm opacity-70">
          File is too large to preview inline. Download it instead.
        </p>
      );
    }
    if (textLoading) return <p className="text-sm opacity-70">Loading preview...</p>;
    if (textError) return <p role="alert" className="text-sm text-red-700 dark:text-red-300">{textError}</p>;
    if (text === null) return null;
    if (isMarkdown) {
      return (
        <div className="prose prose-sm max-w-none">
          <Markdown>{text}</Markdown>
        </div>
      );
    }
    return (
      <pre className="whitespace-pre-wrap break-words rounded-md bg-panel px-3 py-2 text-xs">
        {text}
      </pre>
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={onClose}
    >
      <div
        className="bg-panel-strong rounded-lg shadow-2xl w-full max-w-4xl max-h-full overflow-hidden flex flex-col"
        onClick={stop}
      >
        <div className="flex items-start justify-between gap-3 border-b border-panel px-4 py-3">
          <h2 id={titleId} className="min-w-0 break-words text-lg font-semibold">
            {file.filename}
          </h2>
          <div className="flex shrink-0 items-center gap-2">
            <FileDownloadLink
              className="rounded-md border border-panel-strong px-3 py-1 text-sm"
              rel={file.url}
              filename={file.filename}
            >
              Download
            </FileDownloadLink>
            <button
              type="button"
              className="rounded-md border border-panel-strong px-3 py-1 text-sm"
              onClick={onClose}
              autoFocus
            >
              Close
            </button>
          </div>
        </div>
        <div className="flex min-h-0 flex-1 justify-center overflow-auto p-4">
          {ready ? renderBody() : <p className="text-sm opacity-70">Preparing preview...</p>}
        </div>
      </div>
    </div>
  );
}
