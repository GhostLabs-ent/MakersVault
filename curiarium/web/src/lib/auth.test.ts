// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { refreshToken } from "./api";
import {
  clearRefreshToken,
  clearToken,
  parseRole,
  readRefreshToken,
  readRole,
  readToken,
  roleAtLeast,
  storeRefreshToken,
  storeRole,
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

  it("clears both tokens and the cached role on sign-out", () => {
    storeToken("access-1");
    storeRefreshToken("refresh-1");
    storeRole("admin");

    clearToken();

    expect(readToken()).toBeNull();
    expect(readRefreshToken()).toBeNull();
    expect(readRole()).toBeNull();
  });
});

describe("role helpers", () => {
  beforeEach(() => {
    installMemoryStorage();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("round-trips a stored role", () => {
    expect(readRole()).toBeNull();

    storeRole("editor");
    expect(readRole()).toBe("editor");
  });

  it("fails closed on an unknown or corrupt stored value", () => {
    window.localStorage.setItem("curiarium_auth_role", "superuser");

    expect(readRole()).toBeNull();
  });

  it("parses only the roles the API knows", () => {
    expect(parseRole("admin")).toBe("admin");
    expect(parseRole("editor")).toBe("editor");
    expect(parseRole("contributor")).toBe("contributor");
    expect(parseRole("viewer")).toBe("viewer");
    expect(parseRole("Admin")).toBeNull();
    expect(parseRole("Contributor")).toBeNull();
    expect(parseRole("owner")).toBeNull();
    expect(parseRole(null)).toBeNull();
    expect(parseRole(undefined)).toBeNull();
    expect(parseRole(3)).toBeNull();
  });

  it("ranks roles viewer < editor < admin and fails closed on no role", () => {
    expect(roleAtLeast("viewer", "viewer")).toBe(true);
    expect(roleAtLeast("viewer", "editor")).toBe(false);
    expect(roleAtLeast("viewer", "admin")).toBe(false);
    expect(roleAtLeast("editor", "editor")).toBe(true);
    expect(roleAtLeast("editor", "admin")).toBe(false);
    expect(roleAtLeast("admin", "admin")).toBe(true);
    expect(roleAtLeast(null, "viewer")).toBe(false);
  });

  it("ranks a contributor above a viewer and below an editor", () => {
    // The rung this ticket adds: a contributor reaches contribute but not write.
    expect(roleAtLeast("contributor", "viewer")).toBe(true);
    expect(roleAtLeast("contributor", "contributor")).toBe(true);
    expect(roleAtLeast("contributor", "editor")).toBe(false);
    expect(roleAtLeast("contributor", "admin")).toBe(false);

    // Every rung above it passes, every rung below it fails.
    expect(roleAtLeast("editor", "contributor")).toBe(true);
    expect(roleAtLeast("admin", "contributor")).toBe(true);
    expect(roleAtLeast("viewer", "contributor")).toBe(false);
    expect(roleAtLeast(null, "contributor")).toBe(false);
  });

  it("does not clear the role when only the refresh token goes", () => {
    storeRole("viewer");
    storeRefreshToken("refresh-1");

    clearRefreshToken();

    expect(readRole()).toBe("viewer");
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
