// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fileUrl, getApiBase } from "./api";
import { loadSettings, resetSettingsCache, saveSettings } from "./settings";
import type { AppSettings, ThemeId } from "./settings";

const STORAGE_KEY = "makersvault_settings";
const LEGACY_THEME_KEY = "makersvault_theme";

function buildSettings(publicUrl: string, theme = "dark"): AppSettings {
  return {
    slicer: { enabled: true, selected: "orca" },
    engraving: { enabled: false, selected: "lightburn" },
    theme: { selected: theme as ThemeId },
    makerworld: { cookie: "" },
    thingiverse: { cookie: "" },
    imports: { rememberCookies: false },
    network: { publicUrl },
    previews: { mode: "automatic" },
  };
}

/** Writes a realistic settings payload straight to storage, bypassing `saveSettings`. */
function seedStoredSettings(publicUrl: string, theme = "dark"): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(buildSettings(publicUrl, theme)));
}

/**
 * jsdom reports a `window.localStorage` getter but, under Node's experimental
 * global localStorage, it resolves to `undefined`; tests install a real
 * in-memory Storage so the code under test sees a working store.
 */
function installMemoryStorage(): void {
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
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
}

beforeEach(() => {
  installMemoryStorage();
  window.localStorage.clear();
  resetSettingsCache();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("settings cache", () => {
  it("parses the stored payload once no matter how many URLs are resolved", () => {
    seedStoredSettings("maker.example.com");
    const parseSpy = vi.spyOn(JSON, "parse");

    const base = getApiBase();
    const url = fileUrl("/x.png");
    expect(base).toBe("http://maker.example.com/api");
    expect(url).toBe("http://maker.example.com/api/x.png");

    for (let i = 0; i < 100; i += 1) {
      expect(getApiBase()).toBe(base);
      expect(fileUrl("/x.png")).toBe(url);
    }
    expect(parseSpy).toHaveBeenCalledTimes(1);
  });

  it("applies a saved change on the very next call", () => {
    seedStoredSettings("before.example.com");
    expect(getApiBase()).toBe("http://before.example.com/api");
    const parseSpy = vi.spyOn(JSON, "parse");
    const parseCountBefore = parseSpy.mock.calls.length;

    saveSettings(buildSettings("after.example.com"));

    expect(getApiBase()).toBe("http://after.example.com/api");
    expect(fileUrl("/x.png")).toBe("http://after.example.com/api/x.png");
    expect(parseSpy.mock.calls.length).toBe(parseCountBefore + 1);
  });

  it("picks up a write made outside saveSettings", () => {
    seedStoredSettings("before.example.com");
    expect(getApiBase()).toBe("http://before.example.com/api");

    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(buildSettings("external.example.com")),
    );

    expect(getApiBase()).toBe("http://external.example.com/api");
  });

  it("revalidates when only the legacy theme key changes", () => {
    const raw = JSON.stringify(buildSettings("legacy.example.com", "sepia"));
    window.localStorage.setItem(STORAGE_KEY, raw);
    window.localStorage.setItem(LEGACY_THEME_KEY, "dark");

    expect(loadSettings().theme.selected).toBe("dark");

    // Main payload stays byte-identical; only the legacy key moves.
    window.localStorage.setItem(LEGACY_THEME_KEY, "light");

    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(raw);
    expect(loadSettings().theme.selected).toBe("light");
  });

  it("caches the default settings for corrupt JSON", () => {
    window.localStorage.setItem(STORAGE_KEY, "{not json");
    const parseSpy = vi.spyOn(JSON, "parse");

    const base = getApiBase();
    const url = fileUrl("/x.png");
    for (let i = 0; i < 50; i += 1) {
      expect(getApiBase()).toBe(base);
      expect(fileUrl("/x.png")).toBe(url);
    }

    expect(loadSettings().network.publicUrl).toBe("");
    expect(parseSpy).toHaveBeenCalledTimes(1);
  });

  it("returns a stable frozen object until the store changes, and reset forces a re-parse", () => {
    seedStoredSettings("identity.example.com");

    const first = loadSettings();
    expect(loadSettings()).toBe(first);
    expect(Object.isFrozen(first)).toBe(true);
    expect(Object.isFrozen(first.network)).toBe(true);

    seedStoredSettings("changed.example.com");

    const second = loadSettings();
    expect(second).not.toBe(first);
    expect(second.network.publicUrl).toBe("changed.example.com");

    resetSettingsCache();

    const third = loadSettings();
    expect(third).not.toBe(second);
    expect(third).toEqual(second);
  });

  it("falls back to defaults when the settings key is cleared", () => {
    seedStoredSettings("cleared.example.com");
    expect(loadSettings().network.publicUrl).toBe("cleared.example.com");

    window.localStorage.removeItem(STORAGE_KEY);

    expect(loadSettings().network.publicUrl).toBe("");
    expect(getApiBase()).toBe("http://localhost:8000");
  });
});
