// Session endpoints: password login, OIDC/SSO login, refresh, `me` and logout.
// Distinct from `../auth`, which owns token storage and `authHeaders`.

import { authHeaders } from "../auth";
import { apiBase } from "./baseUrl";
import { assertOk } from "./http";

export type AuthTokens = {
  token: string;
  expires_in: number;
  refresh_token?: string;
  token_type?: string;
};

export async function login(username: string, password: string): Promise<AuthTokens> {
  const res = await fetch(`${apiBase()}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    let message = "Login failed";
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") message = data.detail;
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  return res.json();
}

export async function refreshToken(refresh: string): Promise<AuthTokens> {
  const res = await fetch(`${apiBase()}/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  assertOk(res, "Token refresh failed");
  return res.json();
}

export type Me = {
  id: string | null;
  username: string;
  email: string | null;
  role: string;
  disabled: boolean;
  kind: string;
};

/** The caller's own account: the web client's only source of truth for role. */
export async function getMe(): Promise<Me> {
  const res = await fetch(`${apiBase()}/me`, { headers: authHeaders() });
  assertOk(res, "Failed to load the signed-in user");
  return res.json();
}

/** Best-effort server-side revocation; the caller clears local storage either way. */
export async function logout(refresh: string): Promise<void> {
  try {
    await fetch(`${apiBase()}/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
  } catch {
    // offline or already signed out: nothing left to revoke
  }
}

// --- OIDC / SSO sign-in ---------------------------------------------------
// Every call below runs before a session exists, so none of them carries
// `authHeaders`: the handoff code is the credential the API trades for a token
// pair. The flow itself (state, PKCE, the id_token) is entirely server-side.


export type OidcStatus = { enabled: boolean };

/**
 * Whether this deployment offers SSO at all. A deployment that was never given
 * an IdP answers 503 (and an old proxy might answer 404), and a network blip is
 * not a reason to break the login page: every failure reads as "no SSO", so the
 * button stays hidden instead of offering a dead end. Never throws.
 */
export async function getOidcStatus(): Promise<OidcStatus> {
  try {
    const res = await fetch(`${apiBase()}/auth/oidc/status`, { cache: "no-store" });
    if (!res.ok) return { enabled: false };
    const data = await res.json();
    return { enabled: Boolean(data?.enabled) };
  } catch {
    return { enabled: false };
  }
}

/**
 * The IdP handoff has to be a full page navigation (`window.location.assign`),
 * not a fetch: the browser must follow the API's redirect to the IdP so the
 * IdP's own session cookies apply.
 */
export function oidcStartUrl(): string {
  return `${apiBase()}/auth/oidc/start`;
}

/** Same shape as `/login`: the exchange issues the same token pair. */
export type OidcExchangeResult = AuthTokens;

/**
 * An exchange failure that carries the HTTP status. The caller needs the
 * difference between a spent code (401, retry is useless) and a deployment with
 * no local administrator yet (409, a persistent condition that "try again" would
 * misdescribe), and a bare `Error` cannot express it.
 */
export class OidcExchangeError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "OidcExchangeError";
    this.status = status;
  }
}

/**
 * Trades the single-use handoff code (delivered in the URL fragment) for a
 * session. A 401 means the code was bad, expired or replayed; the detail is for
 * the log only, because the caller replaces it with the fixed `exchange_failed`
 * copy and no server or IdP free text ever reaches the screen. The code itself
 * is never interpolated into a message.
 */
export async function exchangeOidcCode(code: string): Promise<AuthTokens> {
  const res = await fetch(`${apiBase()}/auth/oidc/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) {
    let message = "SSO sign-in failed";
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") message = data.detail;
    } catch {
      // ignore: a non-JSON error body is not worth surfacing
    }
    throw new OidcExchangeError(message, res.status);
  }
  return res.json();
}

/**
 * The frozen `sso_error` enum and its copy. The API decides which of these
 * values to put in the fragment; the client never derives text from it, so an
 * IdP's error description can never appear in the UI. Changing a string here is
 * a copy change, not a behaviour change.
 */
export const SSO_ERROR_COPY: Record<string, string> = {
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

const SSO_ERROR_FALLBACK = "Sign-in could not be completed. Please try again.";

/** Copy for a `#sso_error=` value; unknown codes fall back to the generic line. */
export function ssoErrorCopy(code: string | null): string | null {
  if (!code) return null;
  return SSO_ERROR_COPY[code] ?? SSO_ERROR_FALLBACK;
}
