// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { SSO_ERROR_COPY, exchangeOidcCode, getOidcStatus, oidcStartUrl, ssoErrorCopy } from "./api";

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

const tokens = {
  token: "access-sso",
  expires_in: 900,
  refresh_token: "refresh-sso",
  token_type: "bearer",
};

describe("getOidcStatus", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads the flag from a 200", async () => {
    const fetchMock = installFetch(respond({ enabled: true }));

    await expect(getOidcStatus()).resolves.toEqual({ enabled: true });

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/auth/oidc/status")).toBe(true);
    // A cached answer would leave the SSO button stale for the whole session.
    expect(init.cache).toBe("no-store");
  });

  it("reads a 503 (auth disabled server-side) as 'no SSO'", async () => {
    installFetch(respond(null, { ok: false, status: 503, body: "" }));

    await expect(getOidcStatus()).resolves.toEqual({ enabled: false });
  });

  it("reads a transport failure as 'no SSO' instead of throwing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }));

    await expect(getOidcStatus()).resolves.toEqual({ enabled: false });
  });
});

describe("exchangeOidcCode", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the handoff code and parses the token pair", async () => {
    const fetchMock = installFetch(respond(tokens));

    await expect(exchangeOidcCode("handoff-1")).resolves.toEqual(tokens);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/auth/oidc/exchange")).toBe(true);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ code: "handoff-1" });
  });

  it("rejects on a 401 without echoing the code in the message", async () => {
    installFetch(respond({ detail: "Invalid or expired SSO code" }, { ok: false, status: 401 }));

    const error = await exchangeOidcCode("handoff-secret-1").catch((err: unknown) => err);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("Invalid or expired SSO code");
    expect((error as Error).message).not.toContain("handoff-secret-1");
  });
});

describe("oidcStartUrl", () => {
  it("points at the API start endpoint", () => {
    expect(oidcStartUrl().endsWith("/auth/oidc/start")).toBe(true);
  });
});

describe("ssoErrorCopy", () => {
  it("returns the frozen copy for every enum value", () => {
    const expected: Record<string, string> = {
      state_missing: "Sign-in could not be completed. Please try again.",
      state_unknown: "Sign-in could not be completed. Please try again.",
      state_replayed: "This sign-in link has already been used. Please try again.",
      state_expired: "This sign-in link has expired. Please try again.",
      cookie_mismatch: "Sign-in could not be completed. Please try again.",
      nonce_mismatch: "Sign-in could not be completed. Please try again.",
      token_invalid: "The identity provider's response could not be verified.",
      provider_unavailable: "The identity provider is unavailable. Try again shortly.",
      provider_rejected: "Sign-in was cancelled or refused by the identity provider.",
      group_not_allowed: "Your account is not in a group allowed to sign in.",
      domain_not_allowed: "Your email domain is not allowed to sign in.",
      no_admin_bootstrap: "An administrator must sign in locally once before SSO can create accounts.",
      exchange_failed: "Sign-in could not be completed. Please try again.",
    };

    expect(SSO_ERROR_COPY).toEqual(expected);
    for (const [code, copy] of Object.entries(expected)) {
      expect(ssoErrorCopy(code)).toBe(copy);
    }
  });

  it("falls back to the generic line for an unknown or empty code", () => {
    expect(ssoErrorCopy("idp_said_something_awful")).toBe(
      "Sign-in could not be completed. Please try again.",
    );
    expect(ssoErrorCopy(null)).toBeNull();
    expect(ssoErrorCopy("")).toBeNull();
  });
});
