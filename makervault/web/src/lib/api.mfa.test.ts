// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  MFA_CHALLENGE_EXPIRED,
  MFA_CODE_REJECTED,
  MfaError,
  getMfaStatus,
  isMfaChallenge,
  login,
  mfaConfirm,
  mfaDisable,
  mfaEnrol,
  mfaRegenerateRecoveryCodes,
  mfaStepUp,
  mfaVerify,
  setMfaPolicy,
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
  init: { ok?: boolean; status?: number; body?: string; headers?: Record<string, string> } = {},
): MockResponse {
  const body = init.body ?? JSON.stringify(payload);
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => payload,
    text: async () => body,
    headers: new Headers(init.headers ?? {}),
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

function bearer(init: RequestInit): string | null {
  return new Headers(init.headers).get("Authorization");
}

function jsonBody(init: RequestInit): unknown {
  if (typeof init.body !== "string") throw new Error("expected a JSON string body");
  return JSON.parse(init.body);
}

/** jsdom's localStorage can resolve to `undefined` under Node's global. */
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
      return store.has(key) ? (store.get(key) as string) : null;
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

const tokens = {
  token: "access-1",
  expires_in: 900,
  refresh_token: "refresh-1",
  token_type: "bearer",
};

beforeEach(() => {
  installMemoryStorage();
  storeToken("session-token");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("login and the second-factor challenge", () => {
  it("hands back a token pair for an account without a second factor", async () => {
    const fetchMock = installFetch(respond({ ...tokens, mfa_required: false, mfa_token: null }));

    const result = await login("admin", "hunter2");

    expect(isMfaChallenge(result)).toBe(false);
    expect(result).toMatchObject({ token: "access-1", expires_in: 900 });
    expect(onlyCall(fetchMock).url.endsWith("/login")).toBe(true);
  });

  it("hands back the challenge, not a token pair, for an account with one", async () => {
    installFetch(
      respond({
        mfa_required: true,
        mfa_token: "challenge-jwt",
        token: null,
        refresh_token: null,
        expires_in: 0,
        token_type: "bearer",
      }),
    );

    const result = await login("admin", "hunter2");

    expect(isMfaChallenge(result)).toBe(true);
    // The null token fields must not survive as a `token: null` session.
    expect(result).toEqual({ mfa_required: true, mfa_token: "challenge-jwt" });
  });

  it("keeps the existing error-message handling for a refused password", async () => {
    installFetch(respond({ detail: "Invalid username or password" }, { ok: false, status: 401 }));

    await expect(login("admin", "wrong")).rejects.toThrow("Invalid username or password");
  });
});

describe("mfaVerify", () => {
  it("trades the challenge and the code for a token pair", async () => {
    const fetchMock = installFetch(respond(tokens));

    await expect(mfaVerify("challenge-jwt", "123456")).resolves.toMatchObject({
      token: "access-1",
      refresh_token: "refresh-1",
    });

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/mfa/verify")).toBe(true);
    expect(init.method).toBe("POST");
    // No session exists yet: the challenge in the body is the only credential.
    expect(bearer(init)).toBeNull();
    expect(jsonBody(init)).toEqual({ mfa_token: "challenge-jwt", code: "123456" });
  });

  it("says the code was wrong on a 401", async () => {
    installFetch(respond({ detail: "Invalid or expired code" }, { ok: false, status: 401 }));

    const err = await mfaVerify("challenge-jwt", "000000").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(MfaError);
    expect((err as MfaError).status).toBe(401);
    expect((err as MfaError).message).toBe(MFA_CODE_REJECTED);
  });

  it("says to sign in again on a 400, because the challenge is gone", async () => {
    installFetch(respond({ detail: "Invalid or expired challenge" }, { ok: false, status: 400 }));

    const err = await mfaVerify("spent-jwt", "123456").catch((e: unknown) => e);

    expect((err as MfaError).status).toBe(400);
    expect((err as MfaError).message).toBe(MFA_CHALLENGE_EXPIRED);
  });

  it("surfaces the Retry-After wait on a 429", async () => {
    installFetch(
      respond({ detail: "Too many failed login attempts." }, { ok: false, status: 429, headers: { "Retry-After": "30" } }),
    );

    const err = await mfaVerify("challenge-jwt", "000000").catch((e: unknown) => e);

    expect((err as MfaError).status).toBe(429);
    expect((err as MfaError).message).toContain("30 seconds");
  });

  it("falls back to a plain throttle line when no Retry-After is sent", async () => {
    installFetch(respond({ detail: "Too many failed login attempts." }, { ok: false, status: 429 }));

    const err = await mfaVerify("challenge-jwt", "000000").catch((e: unknown) => e);

    expect((err as MfaError).message).toBe("Too many attempts. Wait a moment and try again.");
  });
});

describe("the signed-in MFA endpoints", () => {
  it("reads the caller's own status with a bearer token and no caching", async () => {
    const status = {
      enrolled: false,
      enrolled_at: null,
      recovery_codes_remaining: 0,
      require_admin: false,
      can_enrol: true,
    };
    const fetchMock = installFetch(respond(status));

    await expect(getMfaStatus()).resolves.toEqual(status);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/mfa")).toBe(true);
    expect(bearer(init)).toBe("Bearer session-token");
    expect(init.cache).toBe("no-store");
  });

  it("starts enrolment with the password in the body, never in a URL", async () => {
    const enrolment = {
      secret: "JBSWY3DPEHPK3PXP",
      otpauth_uri: "otpauth://totp/MakersVault:admin?secret=JBSWY3DPEHPK3PXP",
      digits: 6,
      period: 30,
      algorithm: "SHA1",
    };
    const fetchMock = installFetch(respond(enrolment));

    await expect(mfaEnrol("hunter2")).resolves.toEqual(enrolment);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/mfa/enrol")).toBe(true);
    expect(url).not.toContain("?");
    expect(url).not.toContain("hunter2");
    expect(init.cache).toBe("no-store");
    expect(jsonBody(init)).toEqual({ password: "hunter2" });
  });

  it("confirms with the password, the secret and the code", async () => {
    const fetchMock = installFetch(respond({ recovery_codes: ["AAAAA-BBBBB"] }));

    await expect(mfaConfirm("JBSWY3DPEHPK3PXP", "123456", "hunter2")).resolves.toEqual({
      recovery_codes: ["AAAAA-BBBBB"],
    });

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/mfa/confirm")).toBe(true);
    expect(url).not.toContain("JBSWY3DPEHPK3PXP");
    expect(jsonBody(init)).toEqual({
      password: "hunter2",
      secret: "JBSWY3DPEHPK3PXP",
      code: "123456",
    });
  });

  it("disables with a DELETE and accepts the empty 204", async () => {
    const fetchMock = installFetch(respond(null, { status: 204, body: "" }));

    await expect(mfaDisable("hunter2")).resolves.toBeUndefined();

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/mfa")).toBe(true);
    expect(init.method).toBe("DELETE");
    expect(jsonBody(init)).toEqual({ password: "hunter2" });
  });

  it("regenerates recovery codes", async () => {
    const fetchMock = installFetch(respond({ recovery_codes: ["CCCCC-DDDDD"] }));

    await expect(mfaRegenerateRecoveryCodes("hunter2")).resolves.toEqual({
      recovery_codes: ["CCCCC-DDDDD"],
    });

    const { url } = onlyCall(fetchMock);
    expect(url.endsWith("/mfa/recovery-codes")).toBe(true);
  });

  it("steps the current session up with a code", async () => {
    const fetchMock = installFetch(respond({ mfa_verified: true }));

    await expect(mfaStepUp("123456")).resolves.toEqual({ mfa_verified: true });

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/mfa/step-up")).toBe(true);
    expect(jsonBody(init)).toEqual({ code: "123456" });
  });

  it("writes the deployment policy", async () => {
    const fetchMock = installFetch(respond({ require_admin: true }));

    await expect(setMfaPolicy(true)).resolves.toEqual({ require_admin: true });
    const write = onlyCall(fetchMock);
    expect(write.url.endsWith("/settings/mfa")).toBe(true);
    expect(write.init.method).toBe("POST");
    expect(jsonBody(write.init)).toEqual({ require_admin: true });
  });

  it("keeps the API's own detail and status for a refusal", async () => {
    installFetch(
      respond({ detail: "Two-factor authentication is already enabled" }, { ok: false, status: 409 }),
    );

    const err = await mfaEnrol("hunter2").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(MfaError);
    expect((err as MfaError).status).toBe(409);
    expect((err as MfaError).message).toBe("Two-factor authentication is already enabled");
  });
});
