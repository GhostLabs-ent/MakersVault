const LEGACY_TOKEN_KEY = "makersvault_auth_token";
const CSRF_COOKIE_NAMES = ["__Host-makersvault_csrf", "makersvault_csrf_dev"];
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
let memoryCsrfToken: string | null = null;


function getStorage(kind: "session" | "local"): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return kind === "session" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}


export function clearLegacyAuthTokens() {
  getStorage("session")?.removeItem(LEGACY_TOKEN_KEY);
  getStorage("local")?.removeItem(LEGACY_TOKEN_KEY);
  memoryCsrfToken = null;
}


export function setSessionCsrfToken(token: string | null) {
  memoryCsrfToken = token || null;
}


function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const [rawName, ...valueParts] = part.trim().split("=");
    if (rawName === name) {
      try {
        return decodeURIComponent(valueParts.join("="));
      } catch {
        return null;
      }
    }
  }
  return null;
}


function csrfToken(): string | null {
  if (memoryCsrfToken) return memoryCsrfToken;
  for (const name of CSRF_COOKIE_NAMES) {
    const value = readCookie(name);
    if (value) return value;
  }
  return null;
}


export async function sessionFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers || {});
  headers.delete("Authorization");
  if (!SAFE_METHODS.has(method)) {
    const csrf = csrfToken();
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  return fetch(input, {
    ...init,
    headers,
    credentials: "include",
  });
}


export function authHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init || {});
  headers.delete("Authorization");
  return headers;
}
