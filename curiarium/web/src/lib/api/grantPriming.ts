// Pre-mints file grants for a freshly fetched list via `primeListGrants`, so the
// first render of a thumbnail or file link already carries a signed URL.

import { isGrantable, primeGrants } from "../fileGrants";

/**
 * The file-shaped fields a list response may carry. Everything else — a foreign
 * absolute URL, an unknown path shape — is dropped by `isGrantable`, because the
 * server 400s the whole batch for one path it will not sign.
 */
export function collectFilePaths(rows: unknown): string[] {
  if (!Array.isArray(rows)) return [];
  const paths: string[] = [];
  for (const row of rows) {
    if (typeof row !== "object" || row === null) continue;
    const record = row as Record<string, unknown>;
    const prepared = typeof record.prepared_print === "object" && record.prepared_print !== null
      ? (record.prepared_print as Record<string, unknown>)
      : null;
    for (const candidate of [
      record.url,
      record.thumb_url,
      record.slicer_url,
      record.cover_thumb_url,
      prepared?.url,
    ]) {
      if (typeof candidate === "string" && isGrantable(candidate)) paths.push(candidate);
    }
  }
  return paths;
}

/**
 * Mints grants for a freshly fetched list before it is returned, so the first
 * render of a thumbnail or file link already carries a signed URL. This is one
 * extra round trip per fetch (grants live 60 s and are cached per path, so a
 * refresh within a minute re-mints nothing), and an empty or grant-less list
 * costs no request at all.
 */
export async function primeListGrants(rows: unknown): Promise<void> {
  const paths = collectFilePaths(rows);
  if (!paths.length) return;
  await primeGrants(paths);
}
