// Session endpoints: password login, OIDC/SSO login, refresh, `me` and logout.
// Distinct from `../auth`, which owns token storage and `authHeaders`.

import { authHeaders } from "../auth";
import { apiBase } from "./baseUrl";
import { UnauthorizedError, assertOk, readErrorMessage } from "./http";

export type AuthTokens = {
  token: string;
  expires_in: number;
  refresh_token?: string;
  token_type?: string;
  /**
   * `/login` answers one body shape for every account: a completed sign-in
   * carries `mfa_required: false` and a challenge carries `true`. Both fields
   * are optional here so the refresh and OIDC endpoints, which never mention
   * them, still fit this type.
   */
  mfa_required?: false;
  mfa_token?: null;
};

export async function login(username: string, password: string): Promise<AuthTokens | MfaChallenge> {
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
  const data = await res.json();
  if (isMfaChallenge(data)) {
    // Only the two challenge fields are meaningful; the token fields are null
    // on this body, so returning them would hand the caller a `token: null`.
    return { mfa_required: true, mfa_token: data.mfa_token };
  }
  return data;
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

// --- Two-factor authentication (Mf-lg02) ----------------------------------
// Every call below either carries a second-factor secret or spends one, so all
// of them are `cache: "no-store"` and none of them ever puts a secret, a code
// or a recovery code in a URL: a proxy access log or a cache entry holding a
// TOTP seed is a permanent compromise.

/**
 * `/login` answers this instead of a token pair when the account has a second
 * factor. The `mfa_token` is an opaque, short-lived challenge JWT - not a
 * session - so it is worth nothing on its own and is exchanged once by
 * `mfaVerify`. It is deliberately typed as its own shape rather than as an
 * optional field on `AuthTokens`, so the compiler forces the caller to check.
 */
export type MfaChallenge = { mfa_required: true; mfa_token: string };

/** Narrows a `/login` body to the challenge half; anything else is a session. */
export function isMfaChallenge(value: AuthTokens | MfaChallenge): value is MfaChallenge {
  return value.mfa_required === true && typeof value.mfa_token === "string";
}

/**
 * An MFA failure that carries the HTTP status, for the same reason
 * `OidcExchangeError` does: the caller has to tell a wrong code (401, re-enter
 * it) from a spent challenge (400, sign in again) from throttling (429, wait)
 * and a bare `Error` cannot express the difference.
 */
export class MfaError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "MfaError";
    this.status = status;
  }
}

/** A 401 from `/mfa/verify`: the challenge is live, the code was not. */
export const MFA_CODE_REJECTED = "Invalid or expired code.";
/** A 400 from `/mfa/verify`: the challenge itself is gone, so retrying is pointless. */
export const MFA_CHALLENGE_EXPIRED = "Your sign-in challenge expired. Sign in again.";
const MFA_THROTTLED = "Too many attempts. Wait a moment and try again.";

/**
 * The 429 copy. The API sends `Retry-After` in seconds on the MFA limiter and
 * omits it when the wait is unknown, so the wait is stated only when it is
 * there; the server's own `detail` is not reused because it does not know the
 * number the header carries.
 */
function mfaThrottleMessage(res: Response): string {
  const retryAfter = Number(res.headers.get("Retry-After"));
  if (Number.isFinite(retryAfter) && retryAfter > 0) {
    return `Too many attempts. Try again in ${Math.ceil(retryAfter)} seconds.`;
  }
  return MFA_THROTTLED;
}

/**
 * Trades the challenge `/login` minted, plus one TOTP or recovery code, for the
 * real token pair.
 *
 * No `authHeaders`: this runs before a session exists, so the challenge token in
 * the body is the only credential. Each refusal maps to the one piece of copy
 * the sign-in screen needs, so the caller never has to interpret a status.
 */
export async function mfaVerify(mfaToken: string, code: string): Promise<AuthTokens> {
  const res = await fetch(`${apiBase()}/mfa/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mfa_token: mfaToken, code }),
    cache: "no-store",
  });
  if (res.status === 429) throw new MfaError(mfaThrottleMessage(res), 429);
  if (res.status === 400) throw new MfaError(MFA_CHALLENGE_EXPIRED, 400);
  if (res.status === 401) throw new MfaError(MFA_CODE_REJECTED, 401);
  if (!res.ok) throw new MfaError(await readErrorMessage(res, "Verification failed."), res.status);
  return res.json();
}

/**
 * The one request shape for the signed-in MFA routes. A 401 here is the
 * *session* expiring - not a rejected code - so it stays the plain
 * `UnauthorizedError` the settings shell already signs out on, while every
 * other refusal keeps the API's own `detail` because the copy is specific
 * ("Password confirmation failed" reads better than a generic line).
 */
async function mfaRequest(path: string, init: RequestInit, fallback: string): Promise<Response> {
  // `cache` last: no endpoint here may ever be served from a shared cache.
  const res = await fetch(`${apiBase()}${path}`, { ...init, cache: "no-store" });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new MfaError(await readErrorMessage(res, fallback), res.status);
  return res;
}

/** The caller's own second-factor state, plus the deployment-wide policy flag. */
export type MfaStatus = {
  enrolled: boolean;
  enrolled_at: string | null;
  recovery_codes_remaining: number;
  require_admin: boolean;
  /** False for an enrolled account and for an SSO-only one (no local password). */
  can_enrol: boolean;
};

export async function getMfaStatus(): Promise<MfaStatus> {
  const res = await mfaRequest("/mfa", { headers: authHeaders() }, "Failed to load two-factor status.");
  return res.json();
}

/** What `/mfa/enrol` hands back: the seed to scan or type, never stored by us. */
export type MfaEnrolment = {
  secret: string;
  otpauth_uri: string;
  digits: number;
  period: number;
  algorithm: string;
};

/**
 * Starts enrolment. The password is re-checked by the API (the sudo gate): a
 * hijacked session must not be able to attach a second factor of its own.
 * Nothing is persisted server-side until `mfaConfirm` proves a code works.
 */
export async function mfaEnrol(password: string): Promise<MfaEnrolment> {
  const res = await mfaRequest(
    "/mfa/enrol",
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ password }),
    },
    "Two-factor enrolment could not be started.",
  );
  return res.json();
}

/** The ten single-use codes, returned exactly once and never again. */
export type MfaRecoveryCodes = { recovery_codes: string[] };

/**
 * Completes enrolment. Argument order follows the API body's own reading order
 * only loosely; the named call sites make it explicit.
 */
export async function mfaConfirm(
  secret: string,
  code: string,
  password: string,
): Promise<MfaRecoveryCodes> {
  const res = await mfaRequest(
    "/mfa/confirm",
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ password, secret, code }),
    },
    "That code was not accepted.",
  );
  return res.json();
}

/** Drops the second factor. `204`, so there is nothing to parse. */
export async function mfaDisable(password: string): Promise<void> {
  await mfaRequest(
    "/mfa",
    {
      method: "DELETE",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ password }),
    },
    "Two-factor authentication could not be disabled.",
  );
}

/** Replaces every unused recovery code; the old ones stop working immediately. */
export async function mfaRegenerateRecoveryCodes(password: string): Promise<MfaRecoveryCodes> {
  const res = await mfaRequest(
    "/mfa/recovery-codes",
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ password }),
    },
    "Recovery codes could not be regenerated.",
  );
  return res.json();
}

/** Proving a code on the *current* session, which the admin policy requires. */
export type MfaStepUpResult = { mfa_verified: boolean };

export async function mfaStepUp(code: string): Promise<MfaStepUpResult> {
  const res = await mfaRequest(
    "/mfa/step-up",
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ code }),
    },
    "That code was not accepted.",
  );
  return res.json();
}

/**
 * The deployment-wide "administrators must present a second factor" policy.
 *
 * There is no read call here on purpose: `POST /settings/mfa` is the only
 * route, and `GET /mfa` already carries the same flag, which is what the
 * settings card renders. A client `GET /settings/mfa` would be a 405.
 */
export type MfaPolicy = { require_admin: boolean };

/** Admin-only; the API answers 409 when the caller has not stepped up. */
export async function setMfaPolicy(requireAdmin: boolean): Promise<MfaPolicy> {
  const res = await mfaRequest(
    "/settings/mfa",
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ require_admin: requireAdmin }),
    },
    "The two-factor policy could not be updated.",
  );
  return res.json();
}
