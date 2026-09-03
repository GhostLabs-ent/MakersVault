import React from "react";

import {
  createUser,
  listUsers,
  reauthenticateSession,
  resetUserPassword,
  updateUser,
  type LoginResult,
  type VaultUser,
} from "../lib/api";
import type { VaultRole } from "../lib/capabilities";
import { useVaultCapabilities } from "../lib/CapabilityContext";
import PasswordChange from "./PasswordChange";


type Props = {
  onBack: () => void;
};

const ROLES: VaultRole[] = ["viewer", "member", "administrator"];


export default function AccountSettings({ onBack }: Props) {
  const capabilities = useVaultCapabilities();
  const [users, setUsers] = React.useState<VaultUser[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [confirmationPassword, setConfirmationPassword] = React.useState("");
  const [message, setMessage] = React.useState<string | null>(null);
  const [showPasswordChange, setShowPasswordChange] = React.useState(false);
  const [createForm, setCreateForm] = React.useState({
    username: "",
    displayName: "",
    password: "",
    role: "viewer" as VaultRole,
  });
  const [resetPasswords, setResetPasswords] = React.useState<Record<string, string>>({});

  const load = React.useCallback(async () => {
    if (!capabilities.manageIdentity) return;
    setLoading(true);
    try {
      setUsers(await listUsers());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load accounts");
    } finally {
      setLoading(false);
    }
  }, [capabilities.manageIdentity]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const confirm = async () => {
    setMessage(null);
    try {
      await reauthenticateSession(confirmationPassword);
      setConfirmationPassword("");
      setMessage("Password confirmed. High-impact actions are available for five minutes.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Password confirmation failed");
    }
  };

  const create = async () => {
    setMessage(null);
    try {
      const created = await createUser({
        username: createForm.username,
        display_name: createForm.displayName,
        password: createForm.password,
        role: createForm.role,
      });
      setUsers(current => [...current, created].sort((a, b) => a.username.localeCompare(b.username)));
      setCreateForm({ username: "", displayName: "", password: "", role: "viewer" });
      setMessage(`Created ${created.username}. A password change is required at first sign-in.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Account creation failed");
    }
  };

  const mutate = async (
    user: VaultUser,
    changes: { display_name?: string; role?: VaultRole; enabled?: boolean },
  ) => {
    setBusyId(user.id);
    setMessage(null);
    try {
      const updated = await updateUser(user.id, changes);
      setUsers(current => current.map(item => item.id === updated.id ? updated : item));
      setMessage(`Updated ${updated.username}. Authority changes revoke that account's sessions.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Account update failed");
    } finally {
      setBusyId(null);
    }
  };

  const resetPassword = async (user: VaultUser) => {
    const password = resetPasswords[user.id] || "";
    if (password.length < 15) return;
    setBusyId(user.id);
    setMessage(null);
    try {
      const updated = await resetUserPassword(user.id, password);
      setUsers(current => current.map(item => item.id === updated.id ? updated : item));
      setResetPasswords(current => ({ ...current, [user.id]: "" }));
      setMessage(`Temporary password set for ${updated.username}; existing sessions were revoked.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Password reset failed");
    } finally {
      setBusyId(null);
    }
  };

  const passwordChanged = (_session: LoginResult) => {
    setShowPasswordChange(false);
    setMessage("Password changed and browser session rotated.");
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Accounts &amp; Access</h2>
          <p className="text-sm text-muted">Fixed shared-vault roles, passwords, and authority changes.</p>
        </div>
        <button className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={onBack}>Back</button>
      </div>

      <section className="rounded-lg border border-panel bg-panel-soft p-4">
        <h3 className="font-semibold">Confirm your password</h3>
        <p className="mt-1 text-xs text-muted">Confirmation opens a five-minute window for session revocation, account administration, and irreversible deletion.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input className="min-w-64 flex-1 rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" type="password" autoComplete="current-password" placeholder="Current password" value={confirmationPassword} onChange={event => setConfirmationPassword(event.target.value)} />
          <button className="rounded-md bg-accent px-3 py-2 text-sm disabled:opacity-50" disabled={!confirmationPassword} onClick={() => void confirm()}>Confirm</button>
          <button className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={() => setShowPasswordChange(value => !value)}>Change my password</button>
        </div>
      </section>

      {showPasswordChange && <PasswordChange onChanged={passwordChanged} onCancel={() => setShowPasswordChange(false)} />}

      {capabilities.manageIdentity && <>
        <section className="rounded-lg border border-panel bg-panel-soft p-4">
          <h3 className="font-semibold">Create account</h3>
          <p className="mt-1 text-xs text-muted">The temporary password must be changed at first sign-in.</p>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            <input className="rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" placeholder="Username" maxLength={256} value={createForm.username} onChange={event => setCreateForm(current => ({ ...current, username: event.target.value }))} />
            <input className="rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" placeholder="Display name" maxLength={256} value={createForm.displayName} onChange={event => setCreateForm(current => ({ ...current, displayName: event.target.value }))} />
            <input className="rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" type="password" autoComplete="new-password" placeholder="Temporary password (15+ characters)" minLength={15} maxLength={4096} value={createForm.password} onChange={event => setCreateForm(current => ({ ...current, password: event.target.value }))} />
            <select className="rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" value={createForm.role} onChange={event => setCreateForm(current => ({ ...current, role: event.target.value as VaultRole }))}>{ROLES.map(role => <option key={role} value={role}>{role}</option>)}</select>
          </div>
          <button className="mt-3 rounded-md bg-accent px-3 py-2 text-sm disabled:opacity-50" disabled={!createForm.username.trim() || !createForm.displayName.trim() || createForm.password.length < 15} onClick={() => void create()}>Create account</button>
        </section>

        <section className="rounded-lg border border-panel bg-panel-soft p-4">
          <div className="flex items-center justify-between"><h3 className="font-semibold">Accounts</h3><button className="rounded-md border border-panel-strong px-2 py-1 text-xs" disabled={loading} onClick={() => void load()}>{loading ? "Loading…" : "Refresh"}</button></div>
          <div className="mt-3 space-y-3">
            {users.map(user => (
              <article key={user.id} className="rounded-md border border-panel-strong bg-panel p-3">
                <div className="grid gap-2 lg:grid-cols-[minmax(10rem,1fr)_10rem_auto]">
                  <div><div className="font-semibold">{user.display_name}</div><div className="text-xs text-muted">{user.username}{user.password_change_required ? " · password change required" : ""}</div></div>
                  <select className="rounded-md border border-panel-strong bg-panel-soft px-2 py-1 text-sm" value={user.role} disabled={busyId === user.id} onChange={event => void mutate(user, { role: event.target.value as VaultRole })}>{ROLES.map(role => <option key={role} value={role}>{role}</option>)}</select>
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={user.enabled} disabled={busyId === user.id} onChange={event => void mutate(user, { enabled: event.target.checked })} />Enabled</label>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <input className="min-w-64 flex-1 rounded-md border border-panel-strong bg-panel-soft px-2 py-1 text-sm" type="password" autoComplete="new-password" placeholder="New temporary password" minLength={15} maxLength={4096} value={resetPasswords[user.id] || ""} onChange={event => setResetPasswords(current => ({ ...current, [user.id]: event.target.value }))} />
                  <button className="rounded-md border border-panel-strong px-2 py-1 text-xs disabled:opacity-50" disabled={busyId === user.id || (resetPasswords[user.id] || "").length < 15} onClick={() => void resetPassword(user)}>Set temporary password</button>
                  <button className="rounded-md border border-panel-strong px-2 py-1 text-xs" disabled={busyId === user.id} onClick={() => { const displayName = window.prompt("Display name", user.display_name); if (displayName?.trim()) void mutate(user, { display_name: displayName }); }}>Edit display name</button>
                </div>
              </article>
            ))}
            {!loading && users.length === 0 && <p className="text-sm text-muted">No accounts found.</p>}
          </div>
        </section>
      </>}

      {message && <p className="text-sm" aria-live="polite">{message}</p>}
    </div>
  );
}
