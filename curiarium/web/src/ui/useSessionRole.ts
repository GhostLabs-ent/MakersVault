import { useEffect, useState } from "react";

import { FORBIDDEN_MESSAGE, UnauthorizedError, getMe } from "../lib/api";
import { parseRole, readRefreshToken, readRole, storeRole, type Role } from "../lib/auth";

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
export function useSessionRole({ token, authRequired, onUnauthorized }: Options): Role | null {
  const [role, setRole] = useState<Role | null>(() => (authRequired ? readRole() : "admin"));

  useEffect(() => {
    if (!authRequired) {
      setRole("admin");
      return;
    }
    if (!token) {
      setRole(null);
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
        setRole(next);
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
          setRole(null);
          return;
        }
        // Network blips and 5xx keep the cached role rather than hiding nav.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, authRequired, onUnauthorized]);

  return role;
}
