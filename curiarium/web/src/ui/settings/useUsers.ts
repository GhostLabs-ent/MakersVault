import React from "react";
import {
  UnauthorizedError,
  createUser,
  listUsers,
  resetUserPassword,
  updateUser,
  type PasswordReset,
  type User,
  type UserCreate,
} from "../../lib/api";
import type { Role } from "../../lib/auth";

export type UsersState = {
  users: User[];
  loading: boolean;
  error: string | null;
  busy: boolean;
  actionError: string | null;
  notice: string | null;
  refresh: () => Promise<void>;
  create: (body: UserCreate) => Promise<boolean>;
  setRole: (userId: string, role: Role) => Promise<boolean>;
  setDisabled: (userId: string, disabled: boolean) => Promise<boolean>;
  resetPassword: (userId: string, body: PasswordReset) => Promise<boolean>;
};

type Settled<T> = { ok: true; value: T } | { ok: false; error: unknown };

/**
 * Call an API function without ever letting its rejection escape. The call is
 * deferred into the closure so even a synchronous throw (a mocked module that
 * omits the export) is contained.
 */
async function settle<T>(call: () => Promise<T>): Promise<Settled<T>> {
  try {
    return { ok: true, value: await call() };
  } catch (error) {
    return { ok: false, error };
  }
}

function isUnauthorized(error: unknown): boolean {
  try {
    return error instanceof UnauthorizedError;
  } catch {
    return false;
  }
}

function messageFor(error: unknown, fallback: string): string {
  try {
    return error instanceof Error && error.message ? error.message : fallback;
  } catch {
    return fallback;
  }
}

type Props = {
  onUnauthorized?: () => void;
};

/**
 * The account directory and its mutations. Every call is settled, so a failed
 * mutation becomes an `actionError` string (the server's own sentence when it
 * sent one) and never an unhandled rejection. Each mutation returns `true` only
 * on success, so a form is cleared exactly when the server accepted it, and
 * every success re-lists because the server owns the answer.
 */
export function useUsers({ onUnauthorized }: Props): UsersState {
  const [users, setUsers] = React.useState<User[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const cancelled = React.useRef(false);
  const unauthorizedRef = React.useRef(onUnauthorized);

  // Declared first so the cleanup always wins: every setState below checks it.
  React.useEffect(() => {
    cancelled.current = false;
    return () => {
      cancelled.current = true;
    };
  }, []);

  // The callback lives in a ref so the effects below can keep `[]` deps.
  React.useEffect(() => {
    unauthorizedRef.current = onUnauthorized;
  }, [onUnauthorized]);

  const refresh = React.useCallback(async () => {
    const result = await settle(() => listUsers());
    if (cancelled.current) return;
    setLoading(false);
    if (!result.ok) {
      if (isUnauthorized(result.error)) {
        unauthorizedRef.current?.();
        return;
      }
      setUsers([]);
      setError("Accounts are unavailable right now.");
      return;
    }
    setUsers(result.value);
    setError(null);
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  /** The shared shape of every mutation: clear, settle, report, re-list. */
  const mutate = React.useCallback(
    async (call: () => Promise<unknown>, success: string, fallback: string): Promise<boolean> => {
      setBusy(true);
      setActionError(null);
      setNotice(null);
      const result = await settle(call);
      if (cancelled.current) return false;
      setBusy(false);
      if (!result.ok) {
        if (isUnauthorized(result.error)) {
          unauthorizedRef.current?.();
          return false;
        }
        setActionError(messageFor(result.error, fallback));
        return false;
      }
      setNotice(success);
      await refresh();
      return true;
    },
    [refresh],
  );

  const create = React.useCallback(
    (body: UserCreate) =>
      mutate(
        () => createUser(body),
        `The account ${body.username} was created.`,
        "Failed to create the account.",
      ),
    [mutate],
  );

  const setRole = React.useCallback(
    (userId: string, role: Role) =>
      mutate(() => updateUser(userId, { role }), "The role was updated.", "Failed to update the role."),
    [mutate],
  );

  const setDisabled = React.useCallback(
    (userId: string, disabled: boolean) =>
      mutate(
        () => updateUser(userId, { disabled }),
        disabled ? "The account was disabled." : "The account was enabled again.",
        disabled ? "Failed to disable the account." : "Failed to enable the account.",
      ),
    [mutate],
  );

  const resetPassword = React.useCallback(
    (userId: string, body: PasswordReset) =>
      mutate(
        () => resetUserPassword(userId, body),
        "The password was set and the account's other sessions were signed out.",
        "Failed to set the password.",
      ),
    [mutate],
  );

  return {
    users,
    loading,
    error,
    busy,
    actionError,
    notice,
    refresh,
    create,
    setRole,
    setDisabled,
    resetPassword,
  };
}
