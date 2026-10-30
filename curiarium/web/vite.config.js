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

/**
 * Only the occt-import-js `path`/`crypto` externalization warnings are dropped.
 * That package ships an emscripten bundle whose Node-only code paths reference
 * `path`/`crypto`; only its WASM entry point is used, and it runs inside a
 * worker, so the externalized browser stubs are never touched at runtime. Every
 * other warning goes to Vite's default handler unmodified.
 */
function isAcceptedOcctExternalization(warning) {
  const message = typeof warning === "string" ? warning : warning?.message;
  if (typeof message !== "string") return false;
  // Vite's plugin warnings arrive with the plugin name already prepended, so
  // tolerate the `[plugin vite:resolve] ` prefix as well as the bare sentence.
  return (
    /^(?:\[plugin vite:resolve\] )?Module "(path|crypto)" has been externalized for browser compatibility/.test(
      message,
    ) && message.includes("occt-import-js")
  );
}

export default defineConfig({
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  build: {
    // Entry chunk composition at the time of writing: react-dom 129.8 kB +
    // app shell ~262 kB + markdown stack 178.9 kB + lucide 22 kB. Three.js and
    // the settings page are dynamic imports, so they are not part of it. See
    // curiarium/docs/DEVELOPMENT.md for the full list of accepted warnings.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      onwarn(warning, defaultHandler) {
        if (isAcceptedOcctExternalization(warning)) return;
        defaultHandler(warning);
      },
    },
  },
  server: {
    host: true,
    allowedHosts: resolvedAllowedHosts,
  },
  preview: {
    allowedHosts: resolvedAllowedHosts,
  },
});
