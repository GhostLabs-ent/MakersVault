// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { renderFileUrl } from "./api";
import { clearToken, storeToken } from "./auth";

/**
 * jsdom reports a `window.localStorage` getter but, under Node's experimental
 * global localStorage, it resolves to `undefined`; install a real in-memory
 * Storage so the code under test finds a working store.
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

function parseRendered(src: string): URL {
  return new URL(src, "http://localhost");
}

const STORED_FILE_URL = "/api/file/abc123/logo.png";

describe("renderFileUrl", () => {
  beforeEach(() => {
    installMemoryStorage();
    window.localStorage.clear();
  });

  afterEach(() => {
    clearToken();
  });

  it("appends the viewer's session token to a stored /api file URL", () => {
    storeToken("viewer-token");

    const rendered = renderFileUrl(STORED_FILE_URL);
    expect(rendered).toBeTruthy();

    const parsed = parseRendered(rendered!);
    expect(parsed.pathname).toBe("/api/file/abc123/logo.png");
    expect(parsed.searchParams.get("token")).toBe("viewer-token");
  });

  it("returns the stored URL unchanged when no token is stored", () => {
    expect(renderFileUrl(STORED_FILE_URL)).toBe(STORED_FILE_URL);
  });

  it("leaves an absolute external URL untouched", () => {
    storeToken("viewer-token");

    const rendered = renderFileUrl("https://example.com/x.png");

    expect(rendered).toBe("https://example.com/x.png");
    expect(parseRendered(rendered!).searchParams.has("token")).toBe(false);
  });

  it("leaves a protocol-relative URL untouched", () => {
    storeToken("viewer-token");

    expect(renderFileUrl("//cdn.example.com/x.png")).toBe("//cdn.example.com/x.png");
  });

  it("leaves a non-API relative path untouched", () => {
    storeToken("viewer-token");

    expect(renderFileUrl("/asset/1/preview.png")).toBe("/asset/1/preview.png");
  });

  it("leaves empty and undefined sources untouched", () => {
    storeToken("viewer-token");

    // A bare origin plus `?token=` would be a valid-looking but useless URL.
    expect(renderFileUrl("")).toBe("");
    expect(renderFileUrl(undefined)).toBeUndefined();
  });

  it("is idempotent", () => {
    storeToken("viewer-token");

    const once = renderFileUrl(STORED_FILE_URL);

    expect(renderFileUrl(once)).toBe(once);
  });

  it("overwrites an author-injected token with the viewer's own", () => {
    storeToken("viewer-token");

    const rendered = renderFileUrl(`${STORED_FILE_URL}?token=attacker`);
    const parsed = parseRendered(rendered!);

    expect(parsed.searchParams.get("token")).toBe("viewer-token");
    expect(rendered).not.toContain("attacker");
  });
});
