// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { refreshToken } from "./api";
import {
  clearRefreshToken,
  clearToken,
  readRefreshToken,
  readToken,
  storeRefreshToken,
  storeToken,
} from "./auth";

type MockResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
  text: () => Promise<string>;
  headers: Headers;
};

type MockFetch = ReturnType<typeof vi.fn<(input: string, init?: RequestInit) => Promise<MockResponse>>>;

function respond(payload: unknown): MockResponse {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
    headers: new Headers(),
  };
}

function installFetch(response: MockResponse): MockFetch {
  const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<MockResponse>>(
    async () => response,
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

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

describe("auth token storage", () => {
  beforeEach(() => {
    installMemoryStorage();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("round-trips the refresh token", () => {
    expect(readRefreshToken()).toBeNull();

    storeRefreshToken("refresh-1");
    expect(readRefreshToken()).toBe("refresh-1");

    clearRefreshToken();
    expect(readRefreshToken()).toBeNull();
  });

  it("clears both tokens on sign-out", () => {
    storeToken("access-1");
    storeRefreshToken("refresh-1");

    clearToken();

    expect(readToken()).toBeNull();
    expect(readRefreshToken()).toBeNull();
  });
});

describe("refreshToken client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the refresh token as a JSON body", async () => {
    const payload = { token: "access-2", expires_in: 900, refresh_token: "refresh-2", token_type: "bearer" };
    const fetchMock = installFetch(respond(payload));

    const result = await refreshToken("refresh-1");

    expect(result).toEqual(payload);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/refresh$/);
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({ refresh_token: "refresh-1" });
  });
});
