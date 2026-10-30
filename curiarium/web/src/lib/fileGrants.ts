import { useEffect, useState } from "react";

import { getApiBase } from "./api/baseUrl";

/**
 * File/handoff URLs are resolved through short-lived, file-scoped, read-only
 * grants.
 *
 * A browser `<img>`, an `<a download>` or an OS deep-link handler cannot attach
 * an `Authorization` header, and the session JWT must never be put into a URL
 * again: it leaked a 15-minute, all-routes credential into browser history,
 * proxy logs and Referer headers. The server instead mints a grant — a
 * 60-second JWT bound to one route path with a read-only scope — and the client
 * carries it in `?sig=`.
 *
 * This module owns the client-side grant cache and the batching queue in front
 * of `POST /file-grants`; `./api/grants.ts` owns the HTTP call itself and injects
 * it via `configureGrantMinter`. Injection rather than an import keeps the
 * transport out of this module: `./api/grants.ts` imports this file, so importing
 * it back for the transport would be a cycle. The one import that does come back
 * from there (`getApiBase`, from the leaf `./api/baseUrl.ts`) is a pure base-URL
 * helper used only for the final join.
 *
 * When no minter is configured — e.g. a test that mocks `../lib/api` wholesale
 * — every function degrades to a no-op/miss: nothing fetches, `grantedFileUrl`
 * always misses, and every caller falls back to the plain URL.
 */

export type Grant = {
  path: string;
  url: string;
  /** Epoch seconds (the API's form) or an ISO-8601 timestamp. */
  expires_at: number | string;
};

export type GrantMinter = (paths: string[]) => Promise<void>;

type CachedGrant = {
  url: string;
  /** Epoch milliseconds. */
  exp: number;
};

/** The server's TTL, used only when a response omits `expires_at`. */
const FALLBACK_TTL_MS = 60_000;

/** Re-mint this long before expiry, so a render cannot race the deadline; the lead time `./useFileGrants` schedules by. */
export const GRANT_FRESH_MARGIN_MS = 5_000;

/** The server rejects a batch larger than this. */
const MAX_BATCH_SIZE = 50;

/**
 * The four paths the server will sign. It rejects the WHOLE batch for anything
 * else, so this filter is what keeps one odd field from costing every URL in a
 * list its grant.
 */
const GRANTABLE_PATH_PATTERNS: readonly RegExp[] = [
  /^\/file\/[^/?#]+\/[^/?#]+$/,
  /^\/asset\/[^/?#]+\/files\/[^/?#]+$/,
  /^\/thumb\/[^/?#]+\.jpg$/,
  /^\/asset\/[^/?#]+\/prepared-print$/,
];

/** The only query parameters a file route understands. */
const GRANTABLE_QUERY_KEYS: ReadonlySet<string> = new Set(["v", "inline"]);

let minter: GrantMinter | null = null;
const cache = new Map<string, CachedGrant>();
const pending = new Set<string>();
let flushPromise: Promise<void> | null = null;

/** Injects the transport `./api/grants.ts` owns (`mintFileGrants`); `null` disables minting. */
export function configureGrantMinter(next: GrantMinter | null): void {
  minter = next;
}

/** True once `configureGrantMinter` has installed a transport (`./api/grants` does at import). */
export function hasGrantMinter(): boolean {
  return minter !== null;
}

function splitRel(rel: string): { path: string; query: string } {
  const queryIndex = rel.indexOf("?");
  if (queryIndex === -1) return { path: rel, query: "" };
  return { path: rel.slice(0, queryIndex), query: rel.slice(queryIndex + 1) };
}

/** Path-only test against the four grantable shapes; the query is checked separately. */
function isGrantablePath(path: string): boolean {
  return GRANTABLE_PATH_PATTERNS.some(pattern => pattern.test(path));
}

/**
 * True when the server would sign this rel: one of the four file routes, and at
 * most the `v` (cache-buster) and `inline` query parameters.
 */
export function isGrantable(rel: string): boolean {
  if (!rel.startsWith("/")) return false;
  const { path, query } = splitRel(rel);
  if (!isGrantablePath(path)) return false;
  if (!query) return true;
  // `URLSearchParams.keys()` needs `DOM.Iterable`, which this tsconfig omits, so
  // the few keys are read straight off the query string.
  for (const pair of query.split("&")) {
    if (!pair) continue;
    const separator = pair.indexOf("=");
    const key = separator === -1 ? pair : pair.slice(0, separator);
    if (!GRANTABLE_QUERY_KEYS.has(key)) return false;
  }
  return true;
}

/** A supporting file renders as the inline preview far more often than as a download. */
function isSupportingFilePath(path: string): boolean {
  return /^\/asset\/[^/?#]+\/files\/[^/?#]+$/.test(path);
}

/**
 * The API signs integer epoch seconds; milliseconds and ISO-8601 are accepted
 * too so a serialisation change cannot silently expire every grant at once.
 */
function expiryMilliseconds(value: Grant["expires_at"] | null | undefined, now: number): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value < 1e12 ? value * 1000 : value;
  }
  if (typeof value === "string") {
    const numeric = Number(value);
    if (value.trim() !== "" && Number.isFinite(numeric)) {
      return numeric < 1e12 ? numeric * 1000 : numeric;
    }
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) return parsed;
  }
  return now + FALLBACK_TTL_MS;
}

/** True when the cached grant is still usable *and* not about to expire. */
function isFresh(rel: string, now: number): boolean {
  const entry = cache.get(rel);
  if (!entry) return false;
  if (entry.exp <= now) {
    cache.delete(rel);
    return false;
  }
  return entry.exp > now + GRANT_FRESH_MARGIN_MS;
}

/**
 * Stores the grants the server just signed. Only grantable paths are kept: a
 * response can never widen what the cache will hand out.
 */
export function rememberGrants(grants: Grant[]): void {
  const now = Date.now();
  for (const grant of grants) {
    if (!grant || typeof grant.path !== "string" || typeof grant.url !== "string") continue;
    if (!isGrantable(grant.path)) continue;
    const exp = expiryMilliseconds(grant.expires_at, now);
    if (exp <= now) continue;
    cache.set(grant.path, { url: grant.url, exp });
    pending.delete(grant.path);
  }
}

/** Synchronous cache read for `fileUrl`; `null` on a miss or an expired entry. */
export function grantedFileUrl(rel: string): string | null {
  const entry = cache.get(rel);
  if (!entry) return null;
  if (entry.exp <= Date.now()) {
    cache.delete(rel);
    return null;
  }
  return entry.url;
}

/** Drops one grant so the next `primeGrants` re-mints it (a rendered URL 401'd). */
export function evictGrant(rel: string): void {
  cache.delete(rel);
}

/** When the cached grant for `rel` expires, in epoch milliseconds; null on a miss. */
export function grantExpiry(rel: string): number | null {
  return cache.get(rel)?.exp ?? null;
}

/** Test seam: forgets every cached grant and any queued work. */
export function resetFileGrants(): void {
  cache.clear();
  pending.clear();
}

/** Resolves after the batch that is already scheduled (or the next one) settles. */
function scheduleFlush(): Promise<void> {
  flushPromise ??= Promise.resolve()
    .then(flushPending)
    .finally(() => {
      flushPromise = null;
    });
  return flushPromise;
}

async function flushPending(): Promise<void> {
  const mint = minter;
  if (!mint) {
    pending.clear();
    return;
  }
  const rels = Array.from(pending);
  pending.clear();
  for (let start = 0; start < rels.length; start += MAX_BATCH_SIZE) {
    try {
      await mint(rels.slice(start, start + MAX_BATCH_SIZE));
    } catch {
      // A failed mint (401, 400, offline) must never reject a render path: the
      // cache stays empty for these paths and callers use the plain URL.
    }
  }
}

/**
 * Mints the missing grants for `paths`, batching everything requested in the
 * same tick into one request per ≤50 paths. Filtering happens here, so a list
 * field of an unknown shape is never sent (the server 400s the whole batch).
 * Never rejects: callers are on render/data paths and fall back on a miss.
 */
export async function primeGrants(paths: string[]): Promise<void> {
  if (!minter) return;
  const now = Date.now();
  for (const candidate of paths) {
    if (typeof candidate !== "string") continue;
    const rel = candidate.trim();
    if (!isGrantable(rel) || isFresh(rel, now)) continue;
    pending.add(rel);
    // The preview is the common render for a supporting file; priming it costs
    // nothing extra in the same batch, and the plain download reuses the base.
    if (!rel.includes("?") && isSupportingFilePath(rel)) {
      pending.add(`${rel}?inline=1`);
    }
  }
  while (pending.size > 0) {
    await scheduleFlush();
  }
}

/**
 * Strips the same-origin `/api` prefix a persisted `stableFileUrl` carries.
 * Anything else — foreign, absolute, protocol-relative, plain relative — is not
 * ours to resolve and returns `null`.
 */
function storedRel(src: string | undefined): string | null {
  if (!src || !src.startsWith("/api/")) return null;
  return src.slice("/api".length);
}

/**
 * Resolves a persisted markdown image src for the *current* viewer: the stored
 * `/api/...` path is primed (minted in the background) and, once its grant is
 * cached, rendered as `<api base> + <signed rel>`. Until then the src is
 * returned unchanged, so the image simply stays unauthenticated for a moment
 * instead of failing the render.
 */
export function useGrantedFileUrl(src: string | undefined): string | undefined {
  const rel = storedRel(src);
  const [resolution, setResolution] = useState<{ rel: string; url: string } | null>(null);

  useEffect(() => {
    if (!rel) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const resolve = async (): Promise<void> => {
      await primeGrants([rel]);
      // The component may have unmounted (or moved to another src) while the
      // mint was in flight; a late setState must not land.
      if (!active) return;
      const url = grantedFileUrl(rel);
      if (!url) return;
      setResolution({ rel, url });
      // A grant lives 60 s and a mounted image can outlive it, so re-mint just
      // before the deadline instead of leaving a dead src behind. The timer is
      // cleared on unmount and whenever the first resolve finds no grant.
      const exp = grantExpiry(rel);
      if (exp === null) return;
      timer = setTimeout(() => {
        evictGrant(rel);
        void resolve();
      }, Math.max(exp - Date.now() - GRANT_FRESH_MARGIN_MS, 0));
    };
    void resolve();
    return () => {
      active = false;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [rel]);

  if (!rel) return src;
  const granted = (resolution?.rel === rel ? resolution.url : null) ?? grantedFileUrl(rel);
  if (!granted) return src;
  return `${getApiBase()}${granted}`;
}
