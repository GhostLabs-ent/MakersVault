// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import { loadSettings, resetSettingsCache, saveSettings } from "./settings";
import type { AppSettings, ThemeId } from "./settings";

const STORAGE_KEY = "makersvault_settings";
const SESSION_KEY = "makersvault_session_cookies";

function buildSettings(cookie: string, rememberCookies: boolean, theme = "dark"): AppSettings {
  return {
    slicer: { enabled: false, selected: "orca" },
    engraving: { enabled: false, selected: "lightburn" },
    theme: { selected: theme as ThemeId },
    makerworld: { cookie },
    thingiverse: { cookie },
    imports: { rememberCookies },
    network: { publicUrl: "" },
    previews: { mode: "automatic" },
  };
}

/** Reads the persisted settings blob, failing loudly when nothing was written. */
function readStoredBlob(): AppSettings {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  expect(raw).not.toBeNull();
  return JSON.parse(raw!) as AppSettings;
}

/**
 * jsdom reports `window.localStorage` getters but, under Node's experimental
 * global storage, they can resolve to `undefined`; tests install a real
 * in-memory Storage so the code under test sees a working store.
 */
function installMemoryStorage(property: "localStorage" | "sessionStorage"): void {
  const store = new Map<string, string>();
  const storage: Storage = {
    get length(): number {
      return store.size;
    },
    clear(): void {
      store.clear();
    },
    getItem(key: string): string | null {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number): string | null {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string): void {
      store.delete(key);
    },
    setItem(key: string, value: string): void {
      store.set(key, String(value));
    },
  };
  Object.defineProperty(window, property, { configurable: true, value: storage });
}

beforeEach(() => {
  installMemoryStorage("localStorage");
  installMemoryStorage("sessionStorage");
  window.localStorage.clear();
  window.sessionStorage.clear();
  resetSettingsCache();
});

describe("cookie storage scoping", () => {
  it("does not persist cookies to local storage without the opt-in", () => {
    saveSettings(buildSettings("mw=secret", false));

    const blob = readStoredBlob();
    expect(blob.makerworld.cookie).toBe("");
    expect(blob.thingiverse.cookie).toBe("");

    // The session store is the only at-rest copy.
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBe(
      JSON.stringify({ makerworld: "mw=secret", thingiverse: "mw=secret" }),
    );
    expect(loadSettings().makerworld.cookie).toBe("mw=secret");
  });

  it("drops the cookie when the browser restarts without the opt-in", () => {
    saveSettings(buildSettings("mw=secret", false));

    // A new browser session starts with an empty session store.
    window.sessionStorage.removeItem(SESSION_KEY);
    resetSettingsCache();

    const settings = loadSettings();
    expect(settings.makerworld.cookie).toBe("");
    expect(settings.thingiverse.cookie).toBe("");
  });

  it("persists cookies to local storage when the opt-in is on", () => {
    saveSettings(buildSettings("mw=secret", true));

    const blob = readStoredBlob();
    expect(blob.makerworld.cookie).toBe("mw=secret");
    expect(blob.thingiverse.cookie).toBe("mw=secret");

    // A remembered cookie must not linger in a second store.
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
    expect(loadSettings().makerworld.cookie).toBe("mw=secret");
  });

  it("migrates a legacy blob cookie out of local storage on the first save", () => {
    // Legacy payload: cookies in the long-lived blob, no `imports` key at all.
    const legacy = buildSettings("mw=legacy", false);
    delete (legacy as Partial<AppSettings>).imports;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(legacy));

    // Load stays write-free and falls back to the blob value.
    expect(loadSettings().makerworld.cookie).toBe("mw=legacy");
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();

    saveSettings(loadSettings());

    const blob = readStoredBlob();
    expect(blob.makerworld.cookie).toBe("");
    expect(blob.thingiverse.cookie).toBe("");
    expect(blob.imports.rememberCookies).toBe(false);
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBe(
      JSON.stringify({ makerworld: "mw=legacy", thingiverse: "mw=legacy" }),
    );
    expect(loadSettings().makerworld.cookie).toBe("mw=legacy");
  });

  it("moving from session to remembered storage removes the session copy", () => {
    saveSettings(buildSettings("mw=secret", false));
    const loaded = loadSettings();

    saveSettings({ ...loaded, imports: { rememberCookies: true } });

    expect(readStoredBlob().makerworld.cookie).toBe("mw=secret");
    expect(window.sessionStorage.getItem(SESSION_KEY)).toBeNull();
  });
});
