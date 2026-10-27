import React, { useEffect, useRef, useState } from "react";

type PreviewState = "waiting" | "idle" | "loading" | "error";

type PreviewPayload = {
  data: Uint8Array;
  mime: string;
};

type LightBurnPreviewProps = {
  url: string;
  assetId?: string;
  filename: string;
  imgClass: string;
};

const previewCache = new Map<string, string>();
const ZIP_HEADER = new Uint8Array([0x50, 0x4b, 0x03, 0x04]);
const ZIP_EOCD_HEADER = new Uint8Array([0x50, 0x4b, 0x05, 0x06]);
const ZIP_SCAN_LIMIT = 64 * 1024 * 1024;
const ZIP_EOCD_SEARCH_LIMIT = 1024 * 1024;
const PNG_HEADER = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const JPEG_HEADER = new Uint8Array([0xff, 0xd8]);
const JPEG_FOOTER = new Uint8Array([0xff, 0xd9]);
const BMP_HEADER = new Uint8Array([0x42, 0x4d]);
const RIFF_HEADER = new Uint8Array([0x52, 0x49, 0x46, 0x46]);
const WEBP_HEADER = new Uint8Array([0x57, 0x45, 0x42, 0x50]);
const GIF_87A_HEADER = new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x37, 0x61]);
const GIF_89A_HEADER = new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61]);
const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"]);
const MAX_TEXT_SCAN = 16 * 1024 * 1024;

const MIME_BY_EXT: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".bmp": "image/bmp",
  ".gif": "image/gif",
};

export default function LightBurnPreview({ url, assetId, filename, imgClass }: LightBurnPreviewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [state, setState] = useState<PreviewState>("waiting");
  const [shouldLoad, setShouldLoad] = useState(false);

  useEffect(() => {
    const cacheKey = assetId ? `asset:${assetId}` : url;
    if (
      previewCache.has(cacheKey) ||
      typeof IntersectionObserver === "undefined" ||
      !containerRef.current
    ) {
      setShouldLoad(true);
      return;
    }
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      setShouldLoad(true);
    }, { rootMargin: "240px" });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [url, assetId]);

  useEffect(() => {
    if (!shouldLoad) return;
    let alive = true;
    const cacheKey = assetId ? `asset:${assetId}` : url;
    const cached = previewCache.get(cacheKey);
    if (cached) {
      setPreview(cached);
      setState("idle");
      return () => {
        alive = false;
      };
    }

    setPreview(null);
    setState("loading");
    (async () => {
      try {
        const res = await fetch(url);
        if (!res.ok) {
          throw new Error(`Preview fetch failed: ${res.status}`);
        }
        const bytes = new Uint8Array(await res.arrayBuffer());
        const payload = await extractLightBurnPreview(bytes);
        if (!payload) {
          throw new Error("Preview not found in LightBurn file");
        }
        const objectUrl = URL.createObjectURL(new Blob([payload.data], { type: payload.mime }));
        previewCache.set(cacheKey, objectUrl);
        if (alive) {
          setPreview(objectUrl);
          setState("idle");
        }
      } catch (err) {
        console.warn("LightBurn preview failed:", err);
        if (alive) {
          setState("error");
        }
      }
    })();

    return () => {
      alive = false;
    };
  }, [url, assetId, shouldLoad]);

  return (
    <div ref={containerRef} className="w-full h-full bg-panel-soft flex items-center justify-center rounded-md overflow-hidden">
      {preview ? (
        <img src={preview} alt={filename} decoding="async" className={imgClass} />
      ) : state === "waiting" ? (
        <span className="text-xs text-muted">Waiting to generate preview...</span>
      ) : state === "loading" ? (
        <span className="text-xs text-muted">Generating preview...</span>
      ) : (
        <span className="text-xs text-muted">Preview unavailable</span>
      )}
    </div>
  );
}

async function extractLightBurnPreview(bytes: Uint8Array): Promise<PreviewPayload | null> {
  const fromZip = await extractFromZip(bytes);
  if (fromZip) return fromZip;
  const embedded = extractEmbeddedImage(bytes);
  if (embedded) return embedded;
  return extractEmbeddedBase64(bytes);
}

async function extractFromZip(bytes: Uint8Array): Promise<PreviewPayload | null> {
  const zipSlice = findZipSlice(bytes);
  if (!zipSlice) return null;
  const { unzipSync } = await import("fflate");
  let entries: Record<string, Uint8Array>;
  try {
    entries = unzipSync(zipSlice);
  } catch {
    return null;
  }
  const candidates = Object.entries(entries)
    .map(([name, data]) => {
      const ext = extOf(name);
      const detected = detectImageMime(data);
      return { name, data, ext, detected };
    })
    .filter(entry => entry.data?.length && ((entry.ext && IMAGE_EXTS.has(entry.ext)) || entry.detected));
  if (!candidates.length) {
    return extractBase64FromZipEntries(entries);
  }
  const preferred = candidates.filter(entry => /preview|thumb|thumbnail/i.test(entry.name));
  const selection = pickLargest(preferred.length ? preferred : candidates);
  if (!selection) return null;
  const mime = selection.detected || MIME_BY_EXT[selection.ext] || "image/png";
  return { data: selection.data, mime };
}

function extractBase64FromZipEntries(entries: Record<string, Uint8Array>): PreviewPayload | null {
  const values = Object.values(entries);
  for (const data of values) {
    if (!data?.length) continue;
    if (!isLikelyText(data)) continue;
    const payload = extractBase64FromBytes(data);
    if (payload) return payload;
  }
  return null;
}

function extractEmbeddedBase64(bytes: Uint8Array): PreviewPayload | null {
  const payload = extractBase64FromBytes(bytes);
  if (payload) return payload;
  return null;
}

function extractEmbeddedImage(bytes: Uint8Array): PreviewPayload | null {
  const png = extractPng(bytes);
  if (png) return { data: png, mime: "image/png" };
  const jpg = extractJpeg(bytes);
  if (jpg) return { data: jpg, mime: "image/jpeg" };
  const webp = extractWebp(bytes);
  if (webp) return { data: webp, mime: "image/webp" };
  const bmp = extractBmp(bytes);
  if (bmp) return { data: bmp, mime: "image/bmp" };
  return null;
}

function extractPng(bytes: Uint8Array): Uint8Array | null {
  const start = findSequence(bytes, PNG_HEADER);
  if (start === -1) return null;
  let offset = start + PNG_HEADER.length;
  while (offset + 8 <= bytes.length) {
    const length = readUint32BE(bytes, offset);
    const type = readAscii(bytes, offset + 4, 4);
    const next = offset + 8 + length + 4;
    if (next > bytes.length) return null;
    offset = next;
    if (type === "IEND") {
      return bytes.slice(start, offset);
    }
  }
  return null;
}

function extractJpeg(bytes: Uint8Array): Uint8Array | null {
  const start = findSequence(bytes, JPEG_HEADER);
  if (start === -1) return null;
  const end = findSequence(bytes, JPEG_FOOTER, start + JPEG_HEADER.length);
  if (end === -1) return null;
  return bytes.slice(start, end + JPEG_FOOTER.length);
}

function extractWebp(bytes: Uint8Array): Uint8Array | null {
  let start = 0;
  while (start < bytes.length) {
    const idx = findSequence(bytes, RIFF_HEADER, start);
    if (idx === -1) return null;
    if (isWebpAt(bytes, idx)) {
      if (idx + 12 > bytes.length) return null;
      const size = readUint32LE(bytes, idx + 4);
      const total = size + 8;
      if (total > 0 && idx + total <= bytes.length) {
        return bytes.slice(idx, idx + total);
      }
    }
    start = idx + 4;
  }
  return null;
}

function extractBmp(bytes: Uint8Array): Uint8Array | null {
  const start = findSequence(bytes, BMP_HEADER);
  if (start === -1 || start + 6 > bytes.length) return null;
  const size = readUint32LE(bytes, start + 2);
  if (!size || start + size > bytes.length) return null;
  return bytes.slice(start, start + size);
}

function extractBase64FromBytes(bytes: Uint8Array): PreviewPayload | null {
  if (!isLikelyText(bytes)) return null;
  const view = bytes.length > MAX_TEXT_SCAN ? bytes.slice(0, MAX_TEXT_SCAN) : bytes;
  const text = decodeText(view);
  if (!text) return null;
  const dataUrl = extractDataUrlImage(text);
  if (dataUrl) return dataUrl;
  return extractBase64SignatureImage(text);
}

function decodeText(bytes: Uint8Array): string {
  try {
    return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
  } catch {
    return "";
  }
}

function isLikelyText(bytes: Uint8Array): boolean {
  const sample = bytes.length > 2048 ? bytes.slice(0, 2048) : bytes;
  if (!sample.length) return false;
  let printable = 0;
  for (let i = 0; i < sample.length; i += 1) {
    const b = sample[i];
    if (b === 0) return false;
    if (b === 9 || b === 10 || b === 13) {
      printable += 1;
      continue;
    }
    if (b >= 32 && b <= 126) printable += 1;
  }
  return printable / sample.length > 0.7;
}

function extractDataUrlImage(text: string): PreviewPayload | null {
  const needle = "data:image/";
  const start = text.indexOf(needle);
  if (start === -1) return null;
  const metaStart = start + "data:".length;
  const metaEnd = text.indexOf("base64,", metaStart);
  if (metaEnd === -1) return null;
  const mime = text.slice(metaStart, metaEnd - 1).trim().toLowerCase();
  const dataStart = metaEnd + "base64,".length;
  const dataEnd = readBase64End(text, dataStart);
  if (dataEnd <= dataStart) return null;
  const chunk = text.slice(dataStart, dataEnd);
  const bytes = decodeBase64(chunk);
  if (!bytes) return null;
  return { data: bytes, mime: normalizeMime(mime) };
}

function extractBase64SignatureImage(text: string): PreviewPayload | null {
  const signatures = [
    { prefix: "iVBORw0KGgo", mime: "image/png" },
    { prefix: "/9j/", mime: "image/jpeg" },
    { prefix: "UklGR", mime: "image/webp" },
    { prefix: "Qk", mime: "image/bmp" },
    { prefix: "R0lGOD", mime: "image/gif" },
  ];
  for (const sig of signatures) {
    const idx = text.indexOf(sig.prefix);
    if (idx === -1) continue;
    const end = readBase64End(text, idx);
    if (end <= idx) continue;
    const chunk = text.slice(idx, end);
    const bytes = decodeBase64(chunk);
    if (!bytes) continue;
    return { data: bytes, mime: sig.mime };
  }
  return null;
}

function readBase64End(text: string, start: number): number {
  let end = start;
  for (; end < text.length; end += 1) {
    const code = text.charCodeAt(end);
    const isAlphaNum =
      (code >= 48 && code <= 57) ||
      (code >= 65 && code <= 90) ||
      (code >= 97 && code <= 122);
    if (isAlphaNum || code === 43 || code === 47 || code === 61) {
      continue;
    }
    break;
  }
  return end;
}

function decodeBase64(chunk: string): Uint8Array | null {
  try {
    const binary = atob(chunk);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  } catch {
    return null;
  }
}

function normalizeMime(mime: string): string {
  if (mime === "image/jpg") return "image/jpeg";
  return mime || "image/png";
}

function pickLargest<T extends { data: Uint8Array }>(entries: T[]): T | null {
  if (!entries.length) return null;
  return entries.reduce((best, entry) => (entry.data.length > best.data.length ? entry : best), entries[0]);
}

function extOf(name: string) {
  const lower = (name || "").toLowerCase();
  const dot = lower.lastIndexOf(".");
  return dot === -1 ? "" : lower.slice(dot);
}

function detectImageMime(data: Uint8Array): string {
  if (matchesHeader(data, PNG_HEADER)) return "image/png";
  if (matchesHeader(data, JPEG_HEADER)) return "image/jpeg";
  if (matchesHeader(data, BMP_HEADER)) return "image/bmp";
  if (isWebp(data)) return "image/webp";
  if (matchesHeader(data, GIF_89A_HEADER) || matchesHeader(data, GIF_87A_HEADER)) return "image/gif";
  return "";
}

function matchesHeader(bytes: Uint8Array, header: Uint8Array): boolean {
  return matchesHeaderAt(bytes, header, 0);
}

function matchesHeaderAt(bytes: Uint8Array, header: Uint8Array, offset: number): boolean {
  if (offset < 0 || bytes.length < offset + header.length) return false;
  for (let i = 0; i < header.length; i += 1) {
    if (bytes[offset + i] !== header[i]) return false;
  }
  return true;
}

function isWebp(bytes: Uint8Array): boolean {
  return isWebpAt(bytes, 0);
}

function isWebpAt(bytes: Uint8Array, offset: number): boolean {
  return matchesHeaderAt(bytes, RIFF_HEADER, offset) && matchesHeaderAt(bytes, WEBP_HEADER, offset + 8);
}

function findZipSlice(bytes: Uint8Array): Uint8Array | null {
  if (matchesHeader(bytes, ZIP_HEADER)) return bytes;
  const eocdIndex = findSequenceReverse(bytes, ZIP_EOCD_HEADER, ZIP_EOCD_SEARCH_LIMIT);
  if (eocdIndex !== -1 && eocdIndex + 22 <= bytes.length) {
    const centralSize = readUint32LE(bytes, eocdIndex + 12);
    const centralOffset = readUint32LE(bytes, eocdIndex + 16);
    if (centralSize !== 0xffffffff && centralOffset !== 0xffffffff) {
      const zipStart = eocdIndex - (centralOffset + centralSize);
      if (zipStart >= 0 && matchesHeaderAt(bytes, ZIP_HEADER, zipStart)) {
        return bytes.slice(zipStart);
      }
    }
  }
  const headerIndex = findSequence(bytes, ZIP_HEADER, 0, ZIP_SCAN_LIMIT);
  if (headerIndex === -1) return null;
  return bytes.slice(headerIndex);
}

function readUint32LE(bytes: Uint8Array, offset: number) {
  return (
    (bytes[offset] |
      (bytes[offset + 1] << 8) |
      (bytes[offset + 2] << 16) |
      (bytes[offset + 3] << 24)) >>> 0
  );
}

function readUint32BE(bytes: Uint8Array, offset: number) {
  return (
    ((bytes[offset] << 24) >>> 0) +
    (bytes[offset + 1] << 16) +
    (bytes[offset + 2] << 8) +
    bytes[offset + 3]
  );
}

function readAscii(bytes: Uint8Array, offset: number, length: number) {
  let out = "";
  for (let i = 0; i < length; i += 1) {
    out += String.fromCharCode(bytes[offset + i]);
  }
  return out;
}

function findSequence(bytes: Uint8Array, pattern: Uint8Array, start = 0, limit?: number) {
  const maxStart = bytes.length - pattern.length;
  const cappedStart = Math.max(0, start);
  const end = Math.min(maxStart, limit === undefined ? maxStart : cappedStart + limit);
  for (let i = cappedStart; i <= end; i += 1) {
    let match = true;
    for (let j = 0; j < pattern.length; j += 1) {
      if (bytes[i + j] !== pattern[j]) {
        match = false;
        break;
      }
    }
    if (match) return i;
  }
  return -1;
}

function findSequenceReverse(bytes: Uint8Array, pattern: Uint8Array, limit?: number) {
  const start = bytes.length - pattern.length;
  if (start < 0) return -1;
  const min = Math.max(0, limit === undefined ? 0 : start - limit);
  for (let i = start; i >= min; i -= 1) {
    let match = true;
    for (let j = 0; j < pattern.length; j += 1) {
      if (bytes[i + j] !== pattern[j]) {
        match = false;
        break;
      }
    }
    if (match) return i;
  }
  return -1;
}
