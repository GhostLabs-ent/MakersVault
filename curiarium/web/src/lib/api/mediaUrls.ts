// Browser-loadable file URLs. An `<img>` or `<a download>` cannot send an
// `Authorization` header, so these join `apiBase()` with a cached grant when one
// exists and fall back to the plain path otherwise.

import { grantedFileUrl } from "../fileGrants";
import { apiBase } from "./baseUrl";

/**
 * Joins an API-relative path with the API base. A path whose grant is cached
 * (`primeGrants` minted it) uses the signed URL, because a browser `<img>` or
 * `<a download>` cannot send an `Authorization` header. There is never a
 * session token in the URL: an ungranted path falls back to the plain join and
 * the server answers 401, which is the honest outcome.
 */
export function fileUrl(rel: string) {
  if (!rel) return rel;
  const granted = grantedFileUrl(rel);
  return `${apiBase()}${granted ?? rel}`;
}

/**
 * Inline-display variant of `fileUrl`: the server answers with `Content-Disposition:
 * inline` (and 415 for types it refuses to preview), so iframes/images can load it.
 * `inline=1` is part of what the grant is signed for, so the lookup is for the
 * inline rel itself.
 */
export function assetFilePreviewUrl(rel: string): string {
  return fileUrl(rel + (rel.includes("?") ? "&" : "?") + "inline=1");
}

/**
 * Same join as `fileUrl`, with the same-origin `/api` prefix that nginx proxies
 * to the API, and stable enough to be written into project content.
 *
 * A grant lives 60 seconds and `getApiBase()` is always absolute (the shipped
 * compose defaults it to `http://localhost:8000`), so neither can be persisted;
 * and baking an origin into a description would be dead for every remote
 * viewer. Use this for URLs that get persisted — a markdown image reference in
 * a project description (Mf-dhtm); `useGrantedFileUrl` resolves it per viewer
 * at render time.
 */
export function stableFileUrl(rel: string): string {
  if (!rel) return rel;
  return `/api${rel}`;
}
