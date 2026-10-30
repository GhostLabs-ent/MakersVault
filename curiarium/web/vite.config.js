import { defineConfig } from "vite";

import pkg from "./package.json";

function normalizeHostEntry(entry) {
  // Accept full URLs or bare hostnames and strip protocol/port when present.
  try {
    const parsed = new URL(entry);
    return parsed.hostname;
  } catch {
    return entry.split(":")[0]; // handle host:port input
  }
}

function parseAllowedHosts(value, extras = []) {
  const extraHosts = extras.map(normalizeHostEntry).filter(Boolean);

  if (!value) {
    // Default to permissive host handling in containerized/reverse-proxy setups.
    // Users can still explicitly lock this down with VITE_ALLOWED_HOSTS.
    return true;
  }

  const normalized = value
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean)
    .map(normalizeHostEntry);

  const merged = Array.from(new Set([...normalized, ...extraHosts]));

  if (!merged.length) return true;

  if (
    merged.length === 1 &&
    ["*", "true", "1"].includes(merged[0].toLowerCase())
  ) {
    return true;
  }

  return merged;
}

const apiUrlHost = (() => {
  const url = process.env.VITE_API_URL;
  if (!url) return null;
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
})();

const resolvedAllowedHosts = parseAllowedHosts(
  process.env.VITE_ALLOWED_HOSTS ||
    process.env.ALLOWED_HOSTS ||
    process.env.CORS_ORIGINS,
  apiUrlHost ? [apiUrlHost] : []
);

export default defineConfig({
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  server: {
    host: true,
    allowedHosts: resolvedAllowedHosts,
  },
  preview: {
    allowedHosts: resolvedAllowedHosts,
  },
});
