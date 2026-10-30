import { useEffect, useReducer, useState } from "react";

import {
  GRANT_FRESH_MARGIN_MS,
  grantExpiry,
  grantedFileUrl,
  hasGrantMinter,
  isGrantable,
  primeGrants,
} from "./fileGrants";

/**
 * Keeps the grants a mounted component's markup needs warm.
 *
 * `fileUrl()` is a synchronous cache read by design (ADR 0005 §7), and the
 * grant cache is not observable: minting a grant repaints nothing. A view that
 * renders a browser-loaded URL (`<img src>`, `<iframe src>`, `<a href>`) must
 * therefore mint on mount and re-mint just before each expiry, then repaint
 * itself when the URL it would render actually changed. Grants still live 60 s;
 * nothing here extends one. `useGrantedFileUrl` in `./fileGrants` stays the
 * sibling for persisted markdown image `src`s.
 *
 * Imports only `./fileGrants` and `react`: the transport installs itself from
 * `./api/grants`, and importing anything under `./api` here would close the
 * cycle that injection exists to avoid.
 */

/** Re-attempt a re-mint that did not move its expiry after this long. */
export const GRANT_RETRY_MS = 10_000;

export type GrantRel = string | null | undefined;

/** A rel that needs a grant right now: grantable, but with nothing usable cached. */
function needsGrant(rel: string): boolean {
  return isGrantable(rel) && grantedFileUrl(rel) === null;
}

/**
 * Callers pass a fresh array literal every render, so the effect keys on the
 * contents (the rels, in order) instead of the array identity.
 */
function relsKey(rels: readonly GrantRel[]): string {
  return rels
    .filter((rel): rel is string => typeof rel === "string" && rel !== "")
    .join("\u0000");
}

function parseRels(key: string): string[] {
  return key === "" ? [] : key.split("\u0000");
}

function useGrantKeeper(rels: readonly GrantRel[], rerenderOnRefresh: boolean): boolean {
  const key = relsKey(rels);
  // The cache is not observable, so a mint can only reach a repaint by bumping
  // state here. The counter value itself is never read.
  const [, bumpRevision] = useReducer((revision: number) => revision + 1, 0);
  // The rels key whose first mint attempt has settled: per key, so an instance
  // that swaps its rels re-arms the gate for the new ones instead of rendering
  // them unsigned on the first paint.
  const [settledKey, setSettledKey] = useState<string | null>(null);
  const list = parseRels(key);

  useEffect(() => {
    // With no transport (`../lib/api` mocked wholesale in tests) nothing can
    // ever be minted: no state, no timer, no extra render.
    if (!hasGrantMinter()) return;
    const rels = parseRels(key);
    if (rels.length === 0) return;

    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    /** True once this mount has held a cached expiry, so a lost grant is retried. */
    let renewing = false;

    /** The soonest expiry across the list, or null when no rel holds a grant. */
    const soonestExpiry = (): number | null => {
      let soonest: number | null = null;
      for (const rel of rels) {
        const exp = grantExpiry(rel);
        if (exp === null) continue;
        if (soonest === null || exp < soonest) soonest = exp;
      }
      return soonest;
    };

    const arm = (): void => {
      const soonest = soonestExpiry();
      if (soonest === null) {
        // No cached grant. A mint that failed on the very first attempt stays a
        // miss until the next mount or interaction, as it always has. But a grant
        // this mount once held and then lost must be retried: one outage spanning
        // an expiry would otherwise strand the element for the rest of the mount.
        if (!renewing) return;
        timer = setTimeout(() => {
          void refresh();
        }, GRANT_RETRY_MS);
        return;
      }
      renewing = true;
      const delay = soonest - Date.now() - GRANT_FRESH_MARGIN_MS;
      // Firing here re-mints on its own, because `isFresh` reports a grant
      // inside the margin as stale. No `evictGrant`: that would throw away a
      // still-valid grant and buy a needless request.
      // A delay at or below zero means the renewal that just ran did not move the
      // expiry — the mint failed. Disarming here would leave the element stale for
      // the rest of the mount, so retry instead.
      timer = setTimeout(() => {
        void refresh();
      }, delay > 0 ? delay : GRANT_RETRY_MS);
    };

    const refresh = async (): Promise<void> => {
      await primeGrants(rels);
      if (!active) return;
      // Only markup holding the URL string itself (an `<a href>`) may repaint:
      // an `<img src>` would re-download the bytes a new URL points at.
      if (rerenderOnRefresh) bumpRevision();
      arm();
    };

    const keepWarm = async (): Promise<void> => {
      const before = rels.map(grantedFileUrl);
      await primeGrants(rels);
      // The component may have unmounted (or moved to other rels) mid-mint; a
      // late setState must not land.
      if (!active) return;
      const changed = rels.some((rel, index) => grantedFileUrl(rel) !== before[index]);
      if (changed || rerenderOnRefresh) bumpRevision();
      // The first attempt settles the gate for these rels whether it worked or
      // not: a mint that failed (offline, 401) must not hold a view on its
      // placeholder, and a gate that could re-close after a later expiry would
      // trap it there.
      setSettledKey(key);
      arm();
    };

    void keepWarm();
    return () => {
      active = false;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [key, rerenderOnRefresh]);

  // Computed during render, never stored: a warm cache (or a missing transport)
  // is ready on the very first render.
  if (!hasGrantMinter() || settledKey === key) return true;
  return list.every(rel => !needsGrant(rel));
}

/**
 * Mints the grants `rels` need on mount and keeps them warm while mounted.
 * Returns true when every grantable rel has a grant — a view should gate an
 * `<img>`/`<iframe>`/model body on it so the first request is never unsigned.
 */
export function useFileGrants(rels: readonly GrantRel[]): boolean {
  return useGrantKeeper(rels, false);
}

/**
 * Identical to `useFileGrants`, except that a scheduled re-mint also re-renders.
 * Only for markup that holds the URL string itself (an `<a href>`); an `<img
 * src>` must NOT use this — a re-minted grant is a new URL, so a re-render
 * re-downloads the bytes. Used by `src/ui/FileDownloadLink.tsx`.
 */
export function useLiveFileGrants(rels: readonly GrantRel[]): boolean {
  return useGrantKeeper(rels, true);
}
