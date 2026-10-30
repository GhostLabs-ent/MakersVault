// Signed-in device sessions: the caller's own list plus the admin-only views.

import { authHeaders } from "../auth";
import { apiBase } from "./baseUrl";
import { assertOk } from "./http";

/**
 * One session as the server lists it. The two timestamps are epoch **seconds**,
 * not ISO strings, and neither refresh hash is ever in the payload.
 */
export type UserSession = {
  id: string;
  username: string;
  kind: "password" | "oidc" | "break-glass";
  device: string | null;
  user_agent: string | null;
  client_ip: string | null;
  created_at: number;
  last_used_at: number;
  current: boolean;
};

/** The caller's own sessions; `current` marks the one making this request. */
export async function listSessions(): Promise<UserSession[]> {
  const res = await fetch(`${apiBase()}/me/sessions`, { headers: authHeaders() });
  assertOk(res, "Failed to load the signed-in devices");
  return res.json();
}

/** Signs one of the caller's own sessions out; the API answers 204, nothing to parse. */
export async function revokeSession(sessionId: string): Promise<void> {
  const res = await fetch(`${apiBase()}/me/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  assertOk(res, "Failed to sign the device out");
}

/** Admin-only: another account's sessions (a 403 surfaces via `assertOk`). */
export async function listUserSessions(userId: string): Promise<UserSession[]> {
  const res = await fetch(`${apiBase()}/users/${encodeURIComponent(userId)}/sessions`, {
    headers: authHeaders(),
  });
  assertOk(res, "Failed to load the user's devices");
  return res.json();
}

/** Admin-only: sign another account's session out. A 404 means it was not there. */
export async function revokeUserSession(sessionId: string): Promise<void> {
  const res = await fetch(`${apiBase()}/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  assertOk(res, "Failed to sign the session out");
}
