// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  FORBIDDEN_MESSAGE,
  UnauthorizedError,
  createUser,
  listUsers,
  resetUserPassword,
  updateUser,
  type User,
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

const ada: User = {
  id: "u-ada",
  username: "ada",
  email: "ada@example.com",
  role: "admin",
  disabled: false,
  auth_source: "local",
  oidc_issuer: null,
  oidc_subject: null,
  created_at: "2024-01-02T03:04:05Z",
  updated_at: "2024-01-02T03:04:05Z",
};

describe("users API client", () => {
  beforeEach(() => {
    installMemoryStorage();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists the accounts with a GET and the bearer token", async () => {
    storeToken("token-1");
    const fetchMock = installFetch(respond([ada]));

    await expect(listUsers()).resolves.toEqual([ada]);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/users")).toBe(true);
    expect(init.method).toBeUndefined();
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer token-1");
  });

  it("creates an account with a POST and a JSON body", async () => {
    storeToken("token-1");
    const fetchMock = installFetch(respond(ada, { status: 201 }));

    await expect(
      createUser({ username: "ada", password: "correct-horse", role: "admin", email: "ada@example.com" }),
    ).resolves.toEqual(ada);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/users")).toBe(true);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer token-1");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({
      username: "ada",
      password: "correct-horse",
      role: "admin",
      email: "ada@example.com",
    });
  });

  it("patches an account through the percent-encoded id", async () => {
    storeToken("token-1");
    const fetchMock = installFetch(respond({ ...ada, disabled: true }));

    await expect(updateUser("user/../1 2", { disabled: true })).resolves.toEqual({
      ...ada,
      disabled: true,
    });

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/users/user%2F..%2F1%202")).toBe(true);
    expect(init.method).toBe("PATCH");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer token-1");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({ disabled: true });
  });

  it("sets a password through the percent-encoded sub-resource and parses no body", async () => {
    storeToken("token-1");
    const fetchMock = installFetch(respond(null, { status: 204, body: "" }));

    await expect(
      resetUserPassword("user/../1 2", { password: "correct-horse", allow_sso: true }),
    ).resolves.toBeUndefined();

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/users/user%2F..%2F1%202/password")).toBe(true);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer token-1");
    expect(JSON.parse(String(init.body))).toEqual({
      password: "correct-horse",
      allow_sso: true,
    });
  });

  it("throws UnauthorizedError on a 401 from every call", async () => {
    installFetch(respond(null, { ok: false, status: 401, body: "" }));
    await expect(listUsers()).rejects.toBeInstanceOf(UnauthorizedError);

    vi.unstubAllGlobals();
    installFetch(respond(null, { ok: false, status: 401, body: "" }));
    await expect(createUser({ username: "a", password: "12345678", role: "viewer" })).rejects.toBeInstanceOf(
      UnauthorizedError,
    );

    vi.unstubAllGlobals();
    installFetch(respond(null, { ok: false, status: 401, body: "" }));
    await expect(updateUser("u-1", { role: "viewer" })).rejects.toBeInstanceOf(UnauthorizedError);

    vi.unstubAllGlobals();
    installFetch(respond(null, { ok: false, status: 401, body: "" }));
    await expect(resetUserPassword("u-1", { password: "12345678" })).rejects.toBeInstanceOf(
      UnauthorizedError,
    );
  });

  it("maps a 403 to the shared forbidden message", async () => {
    installFetch(respond(null, { ok: false, status: 403, body: "" }));

    const error = await listUsers().catch((err: unknown) => err);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe(FORBIDDEN_MESSAGE);
  });

  it("surfaces the server's 409 detail instead of a generic sentence", async () => {
    installFetch(
      respond(null, {
        ok: false,
        status: 409,
        body: JSON.stringify({ detail: "at least one enabled administrator is required" }),
      }),
    );

    const error = await updateUser("u-ada", { role: "viewer" }).catch((err: unknown) => err);
    expect((error as Error).message).toBe("at least one enabled administrator is required");
  });

  it("surfaces the server's 409 detail from a create, not the generic sentence", async () => {
    installFetch(
      respond(null, {
        ok: false,
        status: 409,
        body: JSON.stringify({ detail: "username is already taken" }),
      }),
    );

    const error = await createUser({ username: "ada", password: "correct-horse", role: "admin" }).catch(
      (err: unknown) => err,
    );
    expect((error as Error).message).toBe("username is already taken");
  });

  it("surfaces the server's 422 detail from the password reset", async () => {
    installFetch(
      respond(null, {
        ok: false,
        status: 422,
        body: JSON.stringify({ detail: "password must be at least 8 characters" }),
      }),
    );

    const error = await resetUserPassword("u-1", { password: "short" }).catch(
      (err: unknown) => err,
    );
    expect((error as Error).message).toBe("password must be at least 8 characters");
  });
});
