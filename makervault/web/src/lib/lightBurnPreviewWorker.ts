import { unzipSync } from "fflate";

type Limits = {
  maxExpandedBytes: number;
  maxEntries: number;
  maxMemoryBytes: number;
};

type RequestMessage = { id: string; buffer: ArrayBuffer; limits: Limits };
type PreviewPayload = { data: Uint8Array; mime: string };

class LightBurnParseError extends Error {
  constructor(public reason: string, message: string) {
    super(message);
  }
}

const signature = (value: number) => new Uint8Array([
  value & 0xff,
  (value >>> 8) & 0xff,
  (value >>> 16) & 0xff,
  (value >>> 24) & 0xff,
]);
const ZIP_LOCAL = signature(0x04034b50);
const ZIP_CENTRAL = signature(0x02014b50);
const ZIP_EOCD = signature(0x06054b50);
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const JPEG = new Uint8Array([0xff, 0xd8]);
const JPEG_END = new Uint8Array([0xff, 0xd9]);
const RIFF = new Uint8Array([0x52, 0x49, 0x46, 0x46]);
const WEBP = new Uint8Array([0x57, 0x45, 0x42, 0x50]);
const BMP = new Uint8Array([0x42, 0x4d]);
const GIF87 = new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x37, 0x61]);
const GIF89 = new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61]);

const read16 = (bytes: Uint8Array, offset: number) => bytes[offset] | (bytes[offset + 1] << 8);
const read32 = (bytes: Uint8Array, offset: number) => (
  bytes[offset] | (bytes[offset + 1] << 8) | (bytes[offset + 2] << 16) | (bytes[offset + 3] << 24)
) >>> 0;

function matches(bytes: Uint8Array, pattern: Uint8Array, offset = 0) {
  if (offset < 0 || offset + pattern.length > bytes.length) return false;
  for (let index = 0; index < pattern.length; index += 1) {
    if (bytes[offset + index] !== pattern[index]) return false;
  }
  return true;
}

function find(bytes: Uint8Array, pattern: Uint8Array, start = 0) {
  for (let offset = Math.max(0, start); offset <= bytes.length - pattern.length; offset += 1) {
    if (matches(bytes, pattern, offset)) return offset;
  }
  return -1;
}

function findReverse(bytes: Uint8Array, pattern: Uint8Array, maxSearch = 1024 * 1024) {
  const start = bytes.length - pattern.length;
  const minimum = Math.max(0, start - maxSearch);
  for (let offset = start; offset >= minimum; offset -= 1) {
    if (matches(bytes, pattern, offset)) return offset;
  }
  return -1;
}

function zipSlice(bytes: Uint8Array) {
  if (matches(bytes, ZIP_LOCAL)) return bytes;
  const eocd = findReverse(bytes, ZIP_EOCD);
  if (eocd >= 0 && eocd + 22 <= bytes.length) {
    const centralSize = read32(bytes, eocd + 12);
    const centralOffset = read32(bytes, eocd + 16);
    const start = eocd - centralSize - centralOffset;
    if (start >= 0 && matches(bytes, ZIP_LOCAL, start)) return bytes.slice(start);
  }
  const start = find(bytes, ZIP_LOCAL);
  return start >= 0 ? bytes.slice(start) : null;
}

function validateArchive(bytes: Uint8Array, limits: Limits) {
  const eocd = findReverse(bytes, ZIP_EOCD);
  if (eocd < 0 || eocd + 22 > bytes.length) {
    throw new LightBurnParseError("malformed_lightburn", "LightBurn ZIP directory is missing");
  }
  const entries = read16(bytes, eocd + 10);
  const centralOffset = read32(bytes, eocd + 16);
  if (entries === 0xffff || centralOffset === 0xffffffff) {
    throw new LightBurnParseError("archive_entries", "ZIP64 LightBurn previews are not automatic");
  }
  if (entries > limits.maxEntries) {
    throw new LightBurnParseError("archive_entries", "LightBurn archive exceeds the entry budget");
  }
  let offset = centralOffset;
  let expanded = 0;
  for (let entry = 0; entry < entries; entry += 1) {
    if (!matches(bytes, ZIP_CENTRAL, offset) || offset + 46 > bytes.length) {
      throw new LightBurnParseError("malformed_lightburn", "LightBurn ZIP directory is malformed");
    }
    const size = read32(bytes, offset + 24);
    if (size === 0xffffffff) {
      throw new LightBurnParseError("archive_expanded", "ZIP64 LightBurn previews are not automatic");
    }
    expanded += size;
    if (expanded > limits.maxExpandedBytes || expanded > limits.maxMemoryBytes) {
      throw new LightBurnParseError("archive_expanded", "LightBurn archive exceeds the expansion budget");
    }
    offset += 46 + read16(bytes, offset + 28) + read16(bytes, offset + 30) + read16(bytes, offset + 32);
  }
}

function imageMime(bytes: Uint8Array) {
  if (matches(bytes, PNG)) return "image/png";
  if (matches(bytes, JPEG)) return "image/jpeg";
  if (matches(bytes, BMP)) return "image/bmp";
  if (matches(bytes, GIF87) || matches(bytes, GIF89)) return "image/gif";
  if (matches(bytes, RIFF) && matches(bytes, WEBP, 8)) return "image/webp";
  return "";
}

function fromArchive(bytes: Uint8Array, limits: Limits): PreviewPayload | null {
  const archive = zipSlice(bytes);
  if (!archive) return null;
  validateArchive(archive, limits);
  let entries: Record<string, Uint8Array>;
  try {
    entries = unzipSync(archive);
  } catch {
    throw new LightBurnParseError("malformed_lightburn", "LightBurn archive could not be read");
  }
  const images = Object.entries(entries)
    .map(([name, data]) => ({ name, data, mime: imageMime(data) }))
    .filter(entry => entry.mime);
  if (!images.length) return null;
  const preferred = images.filter(entry => /preview|thumb|thumbnail/i.test(entry.name));
  const candidates = preferred.length ? preferred : images;
  const selected = candidates.reduce((best, entry) => entry.data.length > best.data.length ? entry : best);
  if (selected.data.length > limits.maxMemoryBytes) {
    throw new LightBurnParseError("memory_budget", "Embedded LightBurn image exceeds the preview memory budget");
  }
  return { data: selected.data, mime: selected.mime };
}

function directImage(bytes: Uint8Array, limits: Limits): PreviewPayload | null {
  const pngStart = find(bytes, PNG);
  if (pngStart >= 0) {
    let offset = pngStart + PNG.length;
    while (offset + 12 <= bytes.length) {
      const length = ((bytes[offset] << 24) >>> 0) + (bytes[offset + 1] << 16) + (bytes[offset + 2] << 8) + bytes[offset + 3];
      const end = offset + 12 + length;
      if (end > bytes.length) break;
      const type = String.fromCharCode(...bytes.slice(offset + 4, offset + 8));
      offset = end;
      if (type === "IEND") return { data: bytes.slice(pngStart, offset), mime: "image/png" };
    }
  }
  const jpegStart = find(bytes, JPEG);
  const jpegEnd = jpegStart >= 0 ? find(bytes, JPEG_END, jpegStart + 2) : -1;
  if (jpegStart >= 0 && jpegEnd >= 0) {
    const data = bytes.slice(jpegStart, jpegEnd + 2);
    if (data.length <= limits.maxMemoryBytes) return { data, mime: "image/jpeg" };
  }
  const webpStart = find(bytes, RIFF);
  if (webpStart >= 0 && matches(bytes, WEBP, webpStart + 8) && webpStart + 12 <= bytes.length) {
    const size = read32(bytes, webpStart + 4) + 8;
    if (size > 0 && size <= limits.maxMemoryBytes && webpStart + size <= bytes.length) {
      return { data: bytes.slice(webpStart, webpStart + size), mime: "image/webp" };
    }
  }
  const bmpStart = find(bytes, BMP);
  if (bmpStart >= 0 && bmpStart + 6 <= bytes.length) {
    const size = read32(bytes, bmpStart + 2);
    if (size > 0 && size <= limits.maxMemoryBytes && bmpStart + size <= bytes.length) {
      return { data: bytes.slice(bmpStart, bmpStart + size), mime: "image/bmp" };
    }
  }
  return null;
}

function decodeBase64(encoded: string, mime: string, limits: Limits): PreviewPayload | null {
  if (encoded.length > limits.maxMemoryBytes * 2) return null;
  try {
    const binary = atob(encoded);
    if (binary.length > limits.maxMemoryBytes) return null;
    const data = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) data[index] = binary.charCodeAt(index);
    return { data, mime: mime.toLowerCase().replace("image/jpg", "image/jpeg") };
  } catch {
    return null;
  }
}

function base64Image(bytes: Uint8Array, limits: Limits): PreviewPayload | null {
  const text = new TextDecoder().decode(bytes);
  const match = /data:(image\/(?:png|jpeg|jpg|webp|bmp|gif));base64,([a-z\d+/=]+)/i.exec(text);
  if (match) return decodeBase64(match[2], match[1], limits);
  for (const candidate of [
    { prefix: "iVBORw0KGgo", mime: "image/png" },
    { prefix: "/9j/", mime: "image/jpeg" },
    { prefix: "UklGR", mime: "image/webp" },
    { prefix: "Qk", mime: "image/bmp" },
    { prefix: "R0lGOD", mime: "image/gif" },
  ]) {
    const start = text.indexOf(candidate.prefix);
    if (start < 0) continue;
    const encoded = /^[a-z\d+/=]+/i.exec(text.slice(start))?.[0];
    if (!encoded) continue;
    const payload = decodeBase64(encoded, candidate.mime, limits);
    if (payload) return payload;
  }
  return null;
}

self.onmessage = (event: MessageEvent<RequestMessage>) => {
  const { id, buffer, limits } = event.data;
  try {
    const bytes = new Uint8Array(buffer);
    const payload = fromArchive(bytes, limits) || directImage(bytes, limits) || base64Image(bytes, limits);
    if (!payload) throw new LightBurnParseError("malformed_lightburn", "No readable LightBurn preview image was found");
    self.postMessage({ id, ok: true, blob: new Blob([payload.data], { type: payload.mime }) });
  } catch (error) {
    self.postMessage({
      id,
      ok: false,
      reason: error instanceof LightBurnParseError ? error.reason : "malformed_lightburn",
      detail: error instanceof Error ? error.message : "LightBurn preview failed",
    });
  }
};
