// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  FORBIDDEN_MESSAGE,
  UnauthorizedError,
  listSessions,
  listUserSessions,
  revokeSession,
  revokeUserSession,
} from "./api";
import { storeToken } from "./auth";

type MockResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
  text: () => Promise<string>;
  headers: Headers;
};

type MockFetch = ReturnType<typeof vi.fn<(input: string, init?: RequestInit) => Promise<MockResponse>>>;

function respond(
  payload: unknown,
  init: { ok?: boolean; status?: number; body?: string } = {},
): MockResponse {
  const body = init.body ?? JSON.stringify(payload);
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => payload,
    text: async () => body,
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

function onlyCall(fetchMock: MockFetch): { url: string; init: RequestInit } {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0];
  if (!init) throw new Error("fetch was called without an init object");
  return { url, init };
}

/** jsdom's localStorage can resolve to `undefined` under Node's global; install a real one. */
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

const currentSession = {
  id: "sess-current",
  username: "ada",
  kind: "password" as const,
  device: "Firefox on Linux",
  user_agent: "Mozilla/5.0 (X11; Linux x86_64)",
  client_ip: "10.0.0.5",
  created_at: 1735689600,
  last_used_at: 1735689600,
  current: true,
};

const otherSession = {
  id: "sess-other",
  username: "ada",
  kind: "oidc" as const,
  device: null,
  user_agent: null,
  client_ip: null,
  created_at: 1735603200,
  last_used_at: 1735603200,
  current: false,
};

const sessionList = [currentSession, otherSession];

describe("sessions API client", () => {
  beforeEach(() => {
    installMemoryStorage();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists the caller's sessions with a GET and the bearer token", async () => {
    storeToken("token-1");
    const fetchMock = installFetch(respond(sessionList));

    await expect(listSessions()).resolves.toEqual(sessionList);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/me/sessions")).toBe(true);
    expect(init.method).toBeUndefined();
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer token-1");
  });

  it("revokes one session with a DELETE and no body", async () => {
    const fetchMock = installFetch(respond(null, { status: 204, body: "" }));

    await expect(revokeSession("sess-other")).resolves.toBeUndefined();

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/me/sessions/sess-other")).toBe(true);
    expect(init.method).toBe("DELETE");
    expect(init.body).toBeUndefined();
  });

  it("percent-encodes the session id it revokes", async () => {
    const fetchMock = installFetch(respond(null, { status: 204, body: "" }));

    await revokeSession("sess/../1 2");

    const { url } = onlyCall(fetchMock);
    expect(url.endsWith("/me/sessions/sess%2F..%2F1%202")).toBe(true);
  });

  it("lists another account's sessions through the admin route", async () => {
    const fetchMock = installFetch(respond(sessionList));

    await expect(listUserSessions("user/../1 2")).resolves.toEqual(sessionList);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/users/user%2F..%2F1%202/sessions")).toBe(true);
    expect(init.method).toBeUndefined();
  });

  it("revokes another account's session through the admin route", async () => {
    const fetchMock = installFetch(respond(null, { status: 204, body: "" }));

    await expect(revokeUserSession("sess/../1 2")).resolves.toBeUndefined();

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/sessions/sess%2F..%2F1%202")).toBe(true);
    expect(init.method).toBe("DELETE");
  });

  it("throws UnauthorizedError on a 401 from the list", async () => {
    installFetch(respond(null, { ok: false, status: 401, body: "" }));

    await expect(listSessions()).rejects.toBeInstanceOf(UnauthorizedError);
  });

  it("throws UnauthorizedError on a 401 from either revoke", async () => {
    installFetch(respond(null, { ok: false, status: 401, body: "" }));
    await expect(revokeSession("sess-other")).rejects.toBeInstanceOf(UnauthorizedError);

    vi.unstubAllGlobals();
    installFetch(respond(null, { ok: false, status: 401, body: "" }));
    await expect(revokeUserSession("sess-other")).rejects.toBeInstanceOf(UnauthorizedError);
  });

  it("maps a 403 on the admin list to the shared forbidden message", async () => {
    installFetch(respond(null, { ok: false, status: 403, body: "" }));

    const error = await listUserSessions("user-1").catch((err: unknown) => err);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe(FORBIDDEN_MESSAGE);
  });

  it("maps a 404 on revoke to a plain Error, not a forbidden one", async () => {
    installFetch(respond(null, { ok: false, status: 404, body: "" }));

    const error = await revokeSession("sess-gone").catch((err: unknown) => err);
    expect(error).toBeInstanceOf(Error);
    expect(error).not.toBeInstanceOf(UnauthorizedError);
    expect((error as Error).message).toBe("Failed to sign the device out");
  });
});
