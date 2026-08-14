import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { clearToken, readToken, storeToken } from "./auth";


class MemoryStorage implements Storage {
  private values = new Map<string, string>();

  get length() {
    return this.values.size;
  }

  clear() {
    this.values.clear();
  }

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  key(index: number) {
    return Array.from(this.values.keys())[index] ?? null;
  }

  removeItem(key: string) {
    this.values.delete(key);
  }

  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

const TOKEN_KEY = "makersvault_auth_token";
let originalWindow: typeof globalThis.window | undefined;
let localStorage: MemoryStorage;
let sessionStorage: MemoryStorage;

beforeEach(() => {
  originalWindow = globalThis.window;
  localStorage = new MemoryStorage();
  sessionStorage = new MemoryStorage();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage, sessionStorage },
  });
});

afterEach(() => {
  if (originalWindow === undefined) {
    Reflect.deleteProperty(globalThis, "window");
  } else {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow,
    });
  }
});

describe("administrator token storage", () => {
  it("migrates a legacy persistent token exactly once", () => {
    localStorage.setItem(TOKEN_KEY, "legacy-token");

    expect(readToken()).toBe("legacy-token");
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe("legacy-token");
    expect(readToken()).toBe("legacy-token");
  });

  it("stores new tokens only for the browser session and clears both stores", () => {
    localStorage.setItem(TOKEN_KEY, "old-token");
    storeToken("new-token");

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe("new-token");

    localStorage.setItem(TOKEN_KEY, "unexpected-legacy-token");
    clearToken();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });
});
