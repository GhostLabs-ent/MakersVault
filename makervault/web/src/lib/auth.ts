const TOKEN_KEY = "makersvault_auth_token";
const REFRESH_TOKEN_KEY = "makersvault_auth_refresh_token";
const ROLE_KEY = "makersvault_auth_role";

export type Role = "admin" | "editor" | "viewer";

/** Mirror of `api/permissions.py` ROLE_LEVELS: viewer=read=1, editor=write=2, admin=3. */
const ROLE_RANK: Record<Role, number> = { viewer: 1, editor: 2, admin: 3 };

function getStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readToken(): string | null {
  const storage = getStorage();
  if (!storage) return null;
  return storage.getItem(TOKEN_KEY);
}

export function storeToken(token: string) {
  const storage = getStorage();
  if (!storage) return;
  storage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  const storage = getStorage();
  if (!storage) return;
  storage.removeItem(TOKEN_KEY);
  storage.removeItem(REFRESH_TOKEN_KEY);
  storage.removeItem(ROLE_KEY);
}

/**
 * The refresh token outlives the short-lived access token, so it is stored
 * next to it; `clearToken()` clears both tokens and the cached role, and is
 * the only sign-out path.
 */
export function readRefreshToken(): string | null {
  const storage = getStorage();
  if (!storage) return null;
  return storage.getItem(REFRESH_TOKEN_KEY);
}

export function storeRefreshToken(token: string) {
  const storage = getStorage();
  if (!storage) return;
  storage.setItem(REFRESH_TOKEN_KEY, token);
}

export function clearRefreshToken() {
  const storage = getStorage();
  if (!storage) return;
  storage.removeItem(REFRESH_TOKEN_KEY);
}

/**
 * An unknown or corrupt stored value is not a role: fail closed rather than
 * letting a typo rank above the server's answer.
 */
export function parseRole(value: unknown): Role | null {
  if (value === "admin" || value === "editor" || value === "viewer") return value;
  return null;
}

export function roleAtLeast(role: Role | null, required: Role): boolean {
  if (!role) return false;
  return ROLE_RANK[role] >= ROLE_RANK[required];
}

/** The last role `/me` reported; the server is the authority, this is a cache. */
export function readRole(): Role | null {
  const storage = getStorage();
  if (!storage) return null;
  return parseRole(storage.getItem(ROLE_KEY));
}

export function storeRole(role: Role) {
  const storage = getStorage();
  if (!storage) return;
  storage.setItem(ROLE_KEY, role);
}

export function authHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init || {});
  const token = readToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

export function appendTokenToUrl(url: string): string {
  const token = readToken();
  if (!token) return url;
  try {
    const parsed = new URL(url, typeof window !== "undefined" ? window.location.origin : "http://localhost");
    parsed.searchParams.set("token", token);
    return parsed.toString();
  } catch {
    const separator = url.includes("?") ? "&" : "?";
    return `${url}${separator}token=${encodeURIComponent(token)}`;
  }
}
