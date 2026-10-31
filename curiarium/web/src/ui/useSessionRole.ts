import { useEffect, useState } from "react";

import { FORBIDDEN_MESSAGE, UnauthorizedError, getMe } from "../lib/api";
import { parseRole, readRefreshToken, readRole, storeRole, type Role } from "../lib/auth";

export type SessionIdentity = {
  role: Role | null;
  /** `/me`'s username; null until it answers, or when auth is disabled. */
  username: string | null;
  /** "password" | "oidc" | "break-glass" as the API reports it. */
  kind: string | null;
};

type Options = {
  token: string | null;
  authRequired: boolean;
  onUnauthorized: () => void;
};

/**
 * The signed-in user's role as `/me` last reported it. The cache is seeded from
 * localStorage so the nav does not flicker on entry; the server's answer is
 * authoritative, so demotions land on the next `/me` refresh.
 *
 * With auth disabled every route is open and `/me` is a 503, so that deployment
 * reports `admin` without calling the API.
 */
export function useSessionRole({ token, authRequired, onUnauthorized }: Options): SessionIdentity {
  const [identity, setIdentity] = useState<SessionIdentity>(() => ({
    role: authRequired ? readRole() : "admin",
    username: null,
    kind: null,
  }));
  const setRole = (role: Role | null) => setIdentity(previous => ({ ...previous, role }));

  useEffect(() => {
    if (!authRequired) {
      setIdentity({ role: "admin", username: null, kind: null });
      return;
    }
    if (!token) {
      setIdentity({ role: null, username: null, kind: null });
      return;
    }

    setRole(readRole());
    let cancelled = false;
    void (async () => {
      try {
        const me = await getMe();
        if (cancelled) return;
        const next = parseRole(me.role);
        if (next) storeRole(next);
        setIdentity({ role: next, username: me.username ?? null, kind: me.kind ?? null });
      } catch (err) {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          // Boot-time race: App's refresh rotation fires concurrently with a
          // stale access token. A stored refresh token means the session is
          // recoverable, so do not latch the signed-out state for it.
          if (!readRefreshToken()) onUnauthorized();
          return;
        }
        if (err instanceof Error && err.message === FORBIDDEN_MESSAGE) {
          // The session is valid; this account simply may not see who it is.
          setIdentity(previous => ({ ...previous, role: null }));
          return;
        }
        // Network blips and 5xx keep the cached role rather than hiding nav.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, authRequired, onUnauthorized]);

  return identity;
}
