import type { UploadEntry } from "./uploadTree";

export type ZipEntry = {
  path: string;
  size: number;
};

const MIME_BY_EXT: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".bmp": "image/bmp",
  ".svg": "image/svg+xml",
  ".stl": "model/stl",
  ".3mf": "model/3mf",
  ".step": "model/step",
  ".stp": "model/step",
  ".obj": "model/obj",
};

function normalizePath(path: string) {
  return (path || "").replace(/\\/g, "/").replace(/^\/+/, "").replace(/\/+$/, "");
}

export function normalizeZipPath(path: string): string | null {
  const raw = (path || "").replace(/\\/g, "/").replace(/^\/+/, "");
  if (!raw || raw.endsWith("/")) return null;
  const cleaned = normalizePath(raw);
  if (!cleaned) return null;
  const parts = cleaned.split("/").filter(Boolean);
  if (!parts.length || parts.some(part => part === "..")) return null;
  return parts.join("/");
}

export function guessMimeType(name: string) {
  const lower = (name || "").toLowerCase();
  const dot = lower.lastIndexOf(".");
  if (dot === -1) return "";
  const ext = lower.slice(dot);
  return MIME_BY_EXT[ext] || "";
}

export function isZipFile(name: string) {
  return (name || "").toLowerCase().endsWith(".zip");
}

export async function readZipEntries(file: File): Promise<{ entries: ZipEntry[]; data: Record<string, Uint8Array> }> {
  const { unzipSync } = await import("fflate");
  const raw = new Uint8Array(await file.arrayBuffer());
  const zipEntries = unzipSync(raw);
  const data: Record<string, Uint8Array> = {};
  for (const [rawPath, content] of Object.entries(zipEntries)) {
    const normalized = normalizeZipPath(rawPath);
    if (!normalized) continue;
    data[normalized] = content;
  }
  const entries = Object.keys(data)
    .sort((a, b) => a.localeCompare(b))
    .map(path => ({ path, size: data[path].length }));
  return { entries, data };
}

export function buildUploadEntriesFromZip(
  data: Record<string, Uint8Array>,
  selected: string[],
  basePath = ""
): UploadEntry[] {
  const entries: UploadEntry[] = [];
  const normalizedBase = normalizePath(basePath);
  const seen = new Set<string>();
  for (const raw of selected) {
    const path = normalizeZipPath(raw);
    if (!path || seen.has(path)) continue;
    seen.add(path);
    const content = data[path];
    if (!content) continue;
    const parts = path.split("/");
    const filename = parts[parts.length - 1];
    const type = guessMimeType(filename);
    const file = new File([content], filename, type ? { type } : undefined);
    const relativePath = normalizedBase ? `${normalizedBase}/${path}` : path;
    entries.push({ file, relativePath });
  }
  return entries;
}
