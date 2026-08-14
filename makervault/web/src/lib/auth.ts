const TOKEN_KEY = "makersvault_auth_token";

function getStorage(kind: "session" | "local"): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return kind === "session" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

export function readToken(): string | null {
  const session = getStorage("session");
  const current = session?.getItem(TOKEN_KEY) || null;
  if (current) return current;

  const persistent = getStorage("local");
  const legacy = persistent?.getItem(TOKEN_KEY) || null;
  if (!legacy) return null;
  persistent?.removeItem(TOKEN_KEY);
  if (!session) return null;
  session.setItem(TOKEN_KEY, legacy);
  return legacy;
}

export function storeToken(token: string) {
  getStorage("local")?.removeItem(TOKEN_KEY);
  getStorage("session")?.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  getStorage("session")?.removeItem(TOKEN_KEY);
  getStorage("local")?.removeItem(TOKEN_KEY);
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
