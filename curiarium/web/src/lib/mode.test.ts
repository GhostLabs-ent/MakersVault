// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MODE_STORAGE_KEY, loadMode, saveMode } from "./mode";

/** jsdom may resolve `window.localStorage` to undefined; install a real one. */
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
      store.set(key, value);
    },
  };
  Object.defineProperty(window, "localStorage", { value: storage, configurable: true });
}

beforeEach(() => {
  installMemoryStorage();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("library mode persistence", () => {
  it("defaults to files when nothing is stored", () => {
    expect(loadMode()).toBe("files");
  });

  it("round-trips both modes", () => {
    saveMode("projects");
    expect(loadMode()).toBe("projects");

    saveMode("files");
    expect(loadMode()).toBe("files");
  });

  it("ignores a stored value it does not recognise", () => {
    window.localStorage.setItem(MODE_STORAGE_KEY, "grid");
    expect(loadMode()).toBe("files");
  });

  it("falls back to files when storage reads throw", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    expect(loadMode()).toBe("files");
  });

  it("swallows storage write failures", () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    expect(() => saveMode("projects")).not.toThrow();
  });
});
