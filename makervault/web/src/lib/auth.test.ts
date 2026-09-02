import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearLegacyAuthTokens,
  sessionFetch,
  setSessionCsrfToken,
} from "./auth";


class MemoryStorage implements Storage {
  private values = new Map<string, string>();
  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  getItem(key: string) { return this.values.get(key) ?? null; }
  key(index: number) { return Array.from(this.values.keys())[index] ?? null; }
  removeItem(key: string) { this.values.delete(key); }
  setItem(key: string, value: string) { this.values.set(key, value); }
}


const TOKEN_KEY = "makersvault_auth_token";
let originalWindow: typeof globalThis.window | undefined;
let originalDocument: typeof globalThis.document | undefined;
let originalFetch: typeof globalThis.fetch;
let localStorage: MemoryStorage;
let sessionStorage: MemoryStorage;


beforeEach(() => {
  originalWindow = globalThis.window;
  originalDocument = globalThis.document;
  originalFetch = globalThis.fetch;
  localStorage = new MemoryStorage();
  sessionStorage = new MemoryStorage();
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage,
      sessionStorage,
      location: { origin: "https://vault.example" },
    },
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: { cookie: "__Host-makersvault_csrf=bound-csrf-token" },
  });
});


afterEach(() => {
  vi.restoreAllMocks();
  globalThis.fetch = originalFetch;
  if (originalWindow === undefined) Reflect.deleteProperty(globalThis, "window");
  else Object.defineProperty(
    globalThis,
    "window",
    { configurable: true, value: originalWindow },
  );
  if (originalDocument === undefined) Reflect.deleteProperty(globalThis, "document");
  else Object.defineProperty(
    globalThis,
    "document",
    { configurable: true, value: originalDocument },
  );
});


describe("opaque browser sessions", () => {
  it("removes legacy bearer material instead of migrating it", () => {
    localStorage.setItem(TOKEN_KEY, "legacy-local-token");
    sessionStorage.setItem(TOKEN_KEY, "legacy-session-token");

    clearLegacyAuthTokens();

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("sends cookies and the readable CSRF cookie on unsafe requests", async () => {
    const mocked = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    globalThis.fetch = mocked;

    await sessionFetch("https://api.example/assets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    const init = mocked.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(init.credentials).toBe("include");
    expect(headers.get("X-CSRF-Token")).toBe("bound-csrf-token");
    expect(headers.has("Authorization")).toBe(false);
  });

  it("uses an in-memory CSRF value when the API cookie is host-isolated", async () => {
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { cookie: "" },
    });
    setSessionCsrfToken("cross-host-session-csrf");
    const mocked = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    globalThis.fetch = mocked;

    await sessionFetch("https://api.vault.example/assets", { method: "DELETE" });

    const init = mocked.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe(
      "cross-host-session-csrf",
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("does not add CSRF headers to safe reads", async () => {
    const mocked = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    globalThis.fetch = mocked;

    await sessionFetch("https://api.example/assets");

    const init = mocked.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("include");
    expect(new Headers(init.headers).has("X-CSRF-Token")).toBe(false);
  });
});
