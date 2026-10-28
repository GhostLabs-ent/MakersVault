/**
 * Shared "save a downloaded Response to disk" plumbing (Mf-6cxs).
 *
 * The asset grid and the folder sidebar used to carry identical copies of this
 * logic; the project landing page downloads files the same way, so it lives
 * here once.
 */

/** `filename*=UTF-8''Name%20with%20spaces.zip`; charset/language are optional. */
const EXTENDED_FILENAME = /filename\*\s*=\s*([^;]+)/i;
/** Plain `filename="name.zip"` (quotes optional, wins only without `filename*`). */
const QUOTED_FILENAME = /filename\s*=\s*"?([^";]+)"?/i;

/** Decodes an RFC 5987 extended value, falling back to the raw text if malformed. */
function decodeExtendedValue(raw: string): string | null {
  const value = raw.trim().replace(/^"|"$/g, "");
  const parts = value.split("'");
  const encoded = parts.length >= 3 ? parts.slice(2).join("'") : value;
  if (!encoded) return null;
  try {
    return decodeURIComponent(encoded);
  } catch {
    return encoded;
  }
}

/**
 * The download filename advertised by a response, else `fallback`, else
 * `"download"`. RFC 5987 (`filename*=`) wins over the plain parameter.
 */
export function filenameFromDisposition(res: Response, fallback: string): string {
  const disposition = res.headers.get("content-disposition") || "";
  const extended = disposition.match(EXTENDED_FILENAME);
  const quoted = disposition.match(QUOTED_FILENAME);
  const filename = (extended && decodeExtendedValue(extended[1])) || (quoted && quoted[1]) || fallback;
  return filename || "download";
}

/** Saves the response body to disk via a blob object URL and a synthetic link. */
export async function saveResponseToDisk(res: Response, fallback: string): Promise<void> {
  const filename = filenameFromDisposition(res, fallback);
  const blob = await res.blob();
  const blobUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(blobUrl);
}
