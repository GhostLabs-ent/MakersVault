// API base-URL resolution for every request. Pure string logic plus the cached
// `loadSettings` read from `../settings` (the client settings cache, not
// `./settings`, which holds the server-side settings endpoints).

import { loadSettings } from "../settings";

export function normalizePublicUrl(raw: string): string | null {
  const trimmed = (raw || "").trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed.replace(/\/+$/, "");
  }
  const protocol = typeof window !== "undefined" ? window.location.protocol : "http:";
  return `${protocol}//${trimmed}`.replace(/\/+$/, "");
}

export function apiBaseFromPublicUrl(raw: string): string | null {
  const normalized = normalizePublicUrl(raw);
  if (!normalized) return null;
  if (/\/api\/?$/i.test(normalized)) {
    return normalized.replace(/\/+$/, "");
  }
  return `${normalized}/api`;
}

export function apiBaseFromSettings(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const settings = loadSettings();
    return apiBaseFromPublicUrl(settings.network?.publicUrl || "");
  } catch {
    return null;
  }
}

export function isLocalHostName(hostname: string) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

// API base URL resolution (browser-reachable)
export function resolveApiBase(): string {
  const settingsBase = apiBaseFromSettings();
  if (settingsBase) return settingsBase;
  const runtimeUrl = typeof window !== "undefined"
    ? (window as unknown as { __CURIARIUM_CONFIG__?: { apiUrl?: string } }).__CURIARIUM_CONFIG__?.apiUrl
    : "";
  const envUrl = runtimeUrl || (import.meta.env.VITE_API_URL as string | undefined) || "";
  const isAbs = /^(https?:)?\/\//i.test(envUrl);
  const hasWindow = typeof window !== "undefined";
  const host = hasWindow ? window.location.hostname : "localhost";
  const port = hasWindow ? window.location.port : "";
  const protocol = hasWindow ? window.location.protocol : "http:";
  const isStandardPort = port === "" || port === "80" || port === "443";
  const isLocalHost = isLocalHostName(host);
  const isProxyContext = hasWindow && !isLocalHost && isStandardPort;

  if (envUrl) {
    if (isAbs) {
      const absolute = envUrl.startsWith("//") ? `${protocol}${envUrl}` : envUrl;
      return absolute.replace(/\/$/, "");
    } else if (!isProxyContext) {
      // If someone sets just a port like ":8000" or "8000"
      const portOnly = envUrl.replace(/^:?/, "");
      return `http://${host}:${portOnly}`.replace(/\/$/, "");
    }
  }

  // Behind a reverse proxy on 80/443, default to same-origin /api when no
  // explicit absolute API URL is configured.
  if (isProxyContext && hasWindow) {
    return `${window.location.origin}/api`.replace(/\/$/, "");
  }

  // Default: same host, API on 8000
  return `http://${host}:8000`;
}

export function apiBase(): string {
  return resolveApiBase();
}

export function getApiBase() {
  return apiBase();
}
