// Session endpoints: login, refresh, `me` and logout. Distinct from `../auth`,
// which owns token storage and `authHeaders`.

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
