import React from "react";
import {
  UnauthorizedError,
  listUserSessions,
  revokeUserSession,
  type PasswordReset,
  type User,
  type UserSession,
} from "../../lib/api";
import type { Role } from "../../lib/auth";
import SectionHeader from "./SectionHeader";
import { formatLastUsed, sessionDeviceLabel } from "./SessionsSection";
import { useUsers } from "./useUsers";

type Props = {
  onBack: () => void;
  onUnauthorized?: () => void;
  username?: string | null;
};

/** The server's `accounts.MIN_PASSWORD_LENGTH`; refusing here saves a round trip. */
const MIN_PASSWORD_LENGTH = 8;

/** Ascending privilege, so the select reads like the role ladder. */
const ROLES: Role[] = ["viewer", "contributor", "editor", "admin"];

const SESSIONS_ERROR = "The account's devices could not be loaded.";
const SESSION_REVOKE_ERROR = "That device could not be signed out.";

/** An ISO `created_at` as local time; a bad stamp degrades to "unknown". */
export function formatCreatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toLocaleDateString();
}

function Badge({ children }: { children: string }) {
  return (
    <span className="rounded-md border border-panel-strong px-2 py-0.5 text-[11px] text-muted">
      {children}
    </span>
  );
}

/**
 * One account's sessions, loaded on demand. Same shape as `SessionsSection`,
 * but scoped to a target account: every revoke re-lists, because the server
 * owns the answer.
 */
function UserSessionsPanel({
  userId,
  onUnauthorized,
}: {
  userId: string;
  onUnauthorized?: () => void;
}) {
  const [sessions, setSessions] = React.useState<UserSession[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [revoking, setRevoking] = React.useState<string | null>(null);
  const cancelled = React.useRef(false);

  const reload = React.useCallback(async () => {
    try {
      const list = await listUserSessions(userId);
      if (cancelled.current) return;
      setSessions(list);
      setError(null);
    } catch (err) {
      if (cancelled.current) return;
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      setError(SESSIONS_ERROR);
    } finally {
      if (!cancelled.current) setLoading(false);
    }
  }, [userId, onUnauthorized]);

  React.useEffect(() => {
    cancelled.current = false;
    void reload();
    return () => {
      cancelled.current = true;
    };
  }, [reload]);

  const revoke = async (sessionId: string) => {
    setRevoking(sessionId);
    setError(null);
    try {
      await revokeUserSession(sessionId);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      setError(SESSION_REVOKE_ERROR);
      return;
    } finally {
      setRevoking(null);
    }
    await reload();
  };

  return (
    <div className="flex flex-col gap-2 rounded-md border border-panel-strong p-3">
      {loading && <p className="text-sm opacity-70">Loading devices…</p>}

      {error && <p className="text-xs text-red-400">{error}</p>}

      {!loading && sessions.length === 0 && (
        <p className="text-sm opacity-70">No devices are signed in to this account.</p>
      )}

      {sessions.map(session => (
        <div
          key={session.id}
          className="flex items-start justify-between gap-3 text-sm"
        >
          <div className="flex flex-col">
            <span>{sessionDeviceLabel(session)}</span>
            <span className="text-xs text-muted">
              Last used {formatLastUsed(session.last_used_at)}
            </span>
          </div>
          <button
            type="button"
            className="text-xs px-2 py-1 rounded-md border border-panel-strong disabled:opacity-60"
            disabled={revoking !== null}
            onClick={() => void revoke(session.id)}
          >
            {revoking === session.id ? "Revoking…" : "Revoke"}
          </button>
        </div>
      ))}
    </div>
  );
}

export default function UsersSection({ onBack, onUnauthorized, username = null }: Props) {
  const users = useUsers({ onUnauthorized });

  const [draft, setDraft] = React.useState({
    username: "",
    password: "",
    email: "",
    role: "viewer" as Role,
  });
  const [createError, setCreateError] = React.useState<string | null>(null);

  const [resetFor, setResetFor] = React.useState<string | null>(null);
  const [resetPassword, setResetPassword] = React.useState("");
  const [allowDisabled, setAllowDisabled] = React.useState(false);
  const [allowSso, setAllowSso] = React.useState(false);

  const [sessionsFor, setSessionsFor] = React.useState<string | null>(null);

  const openReset = (user: User) => {
    setResetFor(current => (current === user.id ? null : user.id));
    setResetPassword("");
    setAllowDisabled(false);
    setAllowSso(false);
  };

  const submitReset = async (user: User) => {
    // Each flag opens a door that was deliberately shut, so it is sent only
    // when the admin ticked the box that says so.
    const body: PasswordReset = { password: resetPassword };
    if (user.disabled && allowDisabled) body.allow_disabled = true;
    if (user.auth_source === "sso" && allowSso) body.allow_sso = true;
    const ok = await users.resetPassword(user.id, body);
    if (!ok) return;
    setResetFor(null);
    setResetPassword("");
    setAllowDisabled(false);
    setAllowSso(false);
  };

  const submitCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = draft.username.trim();
    if (!name) {
      setCreateError("Enter a username.");
      return;
    }
    if (!draft.password) {
      setCreateError("Enter a password.");
      return;
    }
    if (draft.password.length < MIN_PASSWORD_LENGTH) {
      setCreateError(`The password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setCreateError(null);
    const email = draft.email.trim();
    const ok = await users.create({
      username: name,
      password: draft.password,
      role: draft.role,
      ...(email ? { email } : {}),
    });
    if (!ok) return;
    setDraft({ username: "", password: "", email: "", role: "viewer" });
  };

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader
        title="Users"
        subtitle="Accounts that can sign in to this vault."
        onBack={onBack}
      />

      <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
        <div>
          <div className="text-lg font-semibold">Create account</div>
          <p className="text-sm opacity-70">
            A local account signs in with the password you set here.
          </p>
        </div>
        <form className="flex flex-col gap-3" onSubmit={event => void submitCreate(event)}>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-muted">Username</span>
              <input
                value={draft.username}
                onChange={event => {
                  setDraft(current => ({ ...current, username: event.target.value }));
                  setCreateError(null);
                }}
                className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong text-sm"
                autoComplete="off"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-muted">Password</span>
              <input
                type="password"
                value={draft.password}
                onChange={event => {
                  setDraft(current => ({ ...current, password: event.target.value }));
                  setCreateError(null);
                }}
                className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong text-sm"
                autoComplete="new-password"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-muted">Role</span>
              {/* `admin` must be offered even when the list is empty: the only
                  account that can see an empty list is break-glass, and minting
                  the first admin is exactly what this form is for (A11). */}
              <select
                value={draft.role}
                onChange={event =>
                  setDraft(current => ({ ...current, role: event.target.value as Role }))
                }
                className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong text-sm"
              >
                {ROLES.map(role => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-muted">Email (optional)</span>
              <input
                value={draft.email}
                onChange={event =>
                  setDraft(current => ({ ...current, email: event.target.value }))
                }
                className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong text-sm"
                autoComplete="off"
              />
            </label>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              className="text-sm px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
              disabled={users.busy}
            >
              Create account
            </button>
            {createError && <p className="text-xs text-red-400">{createError}</p>}
          </div>
        </form>
      </div>

      {users.loading && <p className="text-sm opacity-70">Loading accounts…</p>}

      {users.error && <p className="text-xs text-red-400">{users.error}</p>}

      {users.actionError && <p className="text-xs text-red-400">{users.actionError}</p>}

      {users.notice && <p className="text-sm text-emerald-400">{users.notice}</p>}

      {!users.loading && !users.error && users.users.length === 0 && (
        <div className="rounded-lg border border-dashed border-panel-strong bg-panel-soft px-4 py-8 text-center text-sm text-muted">
          <p className="font-medium">No accounts yet.</p>
          <p>
            The environment break-glass administrator is still the only door. SSO cannot
            create the first account: the API answers{" "}
            <span className="font-mono text-xs">no_admin_bootstrap</span> — “An administrator
            must sign in locally once before SSO can create accounts.” Create an admin
            account here, and break-glass stops working the moment it exists.
          </p>
        </div>
      )}

      {users.users.map(user => (
        <div
          key={user.id}
          className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{user.username}</span>
                {user.username === username && <Badge>You</Badge>}
                {user.disabled && <Badge>Disabled</Badge>}
              </div>
              <span className="text-sm text-muted">{user.email || "no email"}</span>
              {/* A4: `auth_source` describes the password credential; the issuer
                  and subject describe the IdP binding. A local password granted
                  with `allow_sso` makes an account two-door, so both badges
                  render — never an either/or. */}
              <div className="flex flex-wrap items-center gap-2">
                {user.auth_source === "local" && <Badge>Local password</Badge>}
                {user.oidc_issuer !== null && (
                  <Badge>
                    {`SSO · ${user.oidc_issuer}${
                      user.oidc_subject ? ` · ${user.oidc_subject}` : ""
                    }`}
                  </Badge>
                )}
                <span className="text-xs text-muted">
                  Created {formatCreatedAt(user.created_at)}
                </span>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <select
                aria-label={`Role for ${user.username}`}
                value={user.role}
                onChange={event =>
                  void users.setRole(user.id, event.target.value as Role)
                }
                disabled={users.busy}
                className="px-2 py-1 rounded-md border border-panel-strong bg-panel-strong text-sm"
              >
                {ROLES.map(role => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="text-sm px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
                disabled={users.busy}
                onClick={() => void users.setDisabled(user.id, !user.disabled)}
              >
                {user.disabled ? "Enable" : "Disable"}
              </button>
              <button
                type="button"
                className="text-sm px-3 py-2 rounded-md border border-panel-strong"
                onClick={() => openReset(user)}
              >
                Reset password
              </button>
              <button
                type="button"
                className="text-sm px-3 py-2 rounded-md border border-panel-strong"
                onClick={() =>
                  setSessionsFor(current => (current === user.id ? null : user.id))
                }
              >
                Sessions
              </button>
            </div>
          </div>

          {resetFor === user.id && (
            <div className="flex flex-col gap-2 rounded-md border border-panel-strong p-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs uppercase tracking-wide text-muted">
                  New password for {user.username}
                </span>
                <input
                  type="password"
                  value={resetPassword}
                  onChange={event => setResetPassword(event.target.value)}
                  className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong text-sm"
                  autoComplete="new-password"
                />
              </label>
              {user.disabled && (
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={allowDisabled}
                    onChange={event => setAllowDisabled(event.target.checked)}
                  />
                  <span>
                    This account is disabled — reopen it deliberately
                    <span className="block text-xs text-muted">
                      Without this the server refuses the reset and the account stays shut.
                    </span>
                  </span>
                </label>
              )}
              {user.auth_source === "sso" && (
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={allowSso}
                    onChange={event => setAllowSso(event.target.checked)}
                  />
                  <span>
                    This account signs in with SSO — give it a local password anyway
                    <span className="block text-xs text-muted">
                      Without this the server keeps the identity provider as the only door.
                    </span>
                  </span>
                </label>
              )}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  className="text-sm px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
                  disabled={users.busy || resetPassword.length === 0}
                  onClick={() => void submitReset(user)}
                >
                  Set password
                </button>
                <p className="text-xs text-muted">
                  Setting a password signs the account out everywhere else.
                </p>
              </div>
            </div>
          )}

          {sessionsFor === user.id && (
            <UserSessionsPanel userId={user.id} onUnauthorized={onUnauthorized} />
          )}
        </div>
      ))}
    </div>
  );
}
