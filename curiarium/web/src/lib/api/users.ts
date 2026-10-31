// Accounts and roles: the admin-only user directory and its lifecycle.

import type { Role } from "../auth";
import { authHeaders } from "../auth";
import { apiBase } from "./baseUrl";
import { FORBIDDEN_MESSAGE, UnauthorizedError, assertOk, readErrorMessage } from "./http";

/**
 * One account as `GET /users` reports it. `auth_source` describes the password
 * credential (there is one, or there is not); `oidc_issuer`/`oidc_subject`
 * describe the IdP binding. They are independent: an admin who reset an SSO
 * account with `allow_sso` produced an account that has both.
 */
export type User = {
  id: string;
  username: string;
  email: string | null;
  role: Role;
  disabled: boolean;
  auth_source: "local" | "sso";
  oidc_issuer: string | null;
  oidc_subject: string | null;
  created_at: string;
  updated_at: string;
};

export type UserCreate = { username: string; password: string; email?: string; role: Role };

export type UserPatch = { disabled?: boolean; role?: Role };

export type PasswordReset = { password: string; allow_disabled?: boolean; allow_sso?: boolean };

/**
 * The refusal an admin has to read. 401 and 403 keep their shared meanings
 * (`UnauthorizedError` / `FORBIDDEN_MESSAGE`), but a 409 or 422 is the server
 * explaining why *this* change is refused — "at least one enabled administrator
 * is required", "this account is disabled…" — and a generic fallback would
 * throw that sentence away. The last-admin and disabled-account refusals are
 * exactly the cases where the server knows better than a fixed string.
 */
async function refusal(res: Response, fallback: string): Promise<Error> {
  if (res.status === 401) return new UnauthorizedError();
  if (res.status === 403) return new Error(FORBIDDEN_MESSAGE);
  return new Error(await readErrorMessage(res, fallback));
}

/** Every account, in the server's username order (admin-only). */
export async function listUsers(): Promise<User[]> {
  const res = await fetch(`${apiBase()}/users`, { headers: authHeaders() });
  assertOk(res, "Failed to load the accounts");
  return res.json();
}

/** Mints a local account. The API hashes the password and never echoes it. */
export async function createUser(body: UserCreate): Promise<User> {
  const res = await fetch(`${apiBase()}/users`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  // A 409 here is a taken username or email and a 422 a rejected password, and
  // both are the server explaining which field to change.
  if (!res.ok) throw await refusal(res, "Failed to create the account");
  return res.json();
}

/** Changes role and/or disabled; a 409 means the last enabled admin would go. */
export async function updateUser(userId: string, body: UserPatch): Promise<User> {
  const res = await fetch(`${apiBase()}/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await refusal(res, "Failed to update the account");
  return res.json();
}

/**
 * Sets another account's password. The API answers 204 with no body, so there
 * is nothing to parse (and nothing that could carry the password back). The
 * two flags are deliberate doors: `allow_disabled` reopens a disabled account,
 * `allow_sso` gives an SSO-only account a local password.
 */
export async function resetUserPassword(userId: string, body: PasswordReset): Promise<void> {
  const res = await fetch(`${apiBase()}/users/${encodeURIComponent(userId)}/password`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await refusal(res, "Failed to set the password");
}
