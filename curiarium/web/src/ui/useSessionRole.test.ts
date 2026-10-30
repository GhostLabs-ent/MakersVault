// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";

vi.mock("../lib/api", () => ({
  FORBIDDEN_MESSAGE: "Your role does not allow this action.",
  UnauthorizedError: class UnauthorizedError extends Error {},
  getMe: vi.fn(),
}));

import { FORBIDDEN_MESSAGE, UnauthorizedError, getMe, type Me } from "../lib/api";
import {
  clearToken,
  readRole,
  storeRefreshToken,
  storeRole,
  storeToken,
} from "../lib/auth";
import { useSessionRole } from "./useSessionRole";

const getMeMock = vi.mocked(getMe);
const onUnauthorized = vi.fn();

function me(role: string): Me {
  return {
    id: "u1",
    username: role,
    email: null,
    role,
    disabled: false,
    kind: "local",
  };
}

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
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
}

beforeEach(() => {
  installMemoryStorage();
  window.localStorage.clear();
  getMeMock.mockReset();
  onUnauthorized.mockReset();
});

afterEach(() => {
  clearToken();
  cleanup();
});

describe("useSessionRole", () => {
  it("resolves the role /me reports and caches it", async () => {
    getMeMock.mockResolvedValue(me("viewer"));

    const { result } = renderHook(() =>
      useSessionRole({ token: "access-1", authRequired: true, onUnauthorized }),
    );

    await waitFor(() => expect(result.current).toBe("viewer"));
    expect(readRole()).toBe("viewer");
  });

  it("resolves an admin", async () => {
    getMeMock.mockResolvedValue(me("admin"));

    const { result } = renderHook(() =>
      useSessionRole({ token: "access-1", authRequired: true, onUnauthorized }),
    );

    await waitFor(() => expect(result.current).toBe("admin"));
  });

  it("reports admin without calling /me when auth is disabled", async () => {
    const { result } = renderHook(() =>
      useSessionRole({ token: null, authRequired: false, onUnauthorized }),
    );

    expect(result.current).toBe("admin");
    expect(getMeMock).not.toHaveBeenCalled();
  });

  it("reports no role without a token", () => {
    const { result } = renderHook(() =>
      useSessionRole({ token: null, authRequired: true, onUnauthorized }),
    );

    expect(result.current).toBeNull();
    expect(getMeMock).not.toHaveBeenCalled();
  });

  it("swallows a boot-time 401 while a refresh token can recover the session", async () => {
    storeToken("stale-access");
    storeRefreshToken("refresh-1");
    getMeMock.mockRejectedValue(new UnauthorizedError());

    const { result } = renderHook(() =>
      useSessionRole({ token: "stale-access", authRequired: true, onUnauthorized }),
    );

    await waitFor(() => expect(getMeMock).toHaveBeenCalled());
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(result.current).toBeNull();
  });

  it("reports the session as expired on a 401 when no refresh token remains", async () => {
    storeToken("stale-access");
    getMeMock.mockRejectedValue(new UnauthorizedError());

    renderHook(() => useSessionRole({ token: "stale-access", authRequired: true, onUnauthorized }));

    await waitFor(() => expect(onUnauthorized).toHaveBeenCalledTimes(1));
  });

  it("fails closed on a 403 without ending the session", async () => {
    storeRole("admin");
    getMeMock.mockRejectedValue(new Error(FORBIDDEN_MESSAGE));

    const { result } = renderHook(() =>
      useSessionRole({ token: "access-1", authRequired: true, onUnauthorized }),
    );

    await waitFor(() => expect(getMeMock).toHaveBeenCalled());
    await waitFor(() => expect(result.current).toBeNull());
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("refetches and updates the role when the token rotates", async () => {
    getMeMock.mockResolvedValueOnce(me("viewer")).mockResolvedValueOnce(me("admin"));

    const { result, rerender } = renderHook(
      ({ token }: { token: string }) =>
        useSessionRole({ token, authRequired: true, onUnauthorized }),
      { initialProps: { token: "access-1" } },
    );

    await waitFor(() => expect(result.current).toBe("viewer"));

    rerender({ token: "access-2" });

    await waitFor(() => expect(result.current).toBe("admin"));
    expect(getMeMock).toHaveBeenCalledTimes(2);
  });
});
