import React from "react";

import {
  beginPasskeyRegistration,
  completePasskeyRegistration,
  createUser,
  getAuthenticatorPolicy,
  getPasskeys,
  getSession,
  listUsers,
  removePasskey,
  renamePasskey,
  resetUserMfa,
  resetUserPassword,
  updateAuthenticatorPolicy,
  updateUser,
  type AuthenticatorPolicy,
  type AuthenticatorPolicyMode,
  type LoginResult,
  type PasskeyAccount,
  type VaultUser,
} from "../lib/api";
import type { VaultRole } from "../lib/capabilities";
import { useVaultCapabilities } from "../lib/CapabilityContext";
import { confirmCurrentAuthentication } from "../lib/passkeyFlows";
import { createPasskeyCredential } from "../lib/passkeys";
import PasswordChange from "./PasswordChange";


type Props = {
  onBack: () => void;
};

const ROLES: VaultRole[] = ["viewer", "member", "administrator"];


export default function AccountSettings({ onBack }: Props) {
  const capabilities = useVaultCapabilities();
  const [users, setUsers] = React.useState<VaultUser[]>([]);
  const [passkeys, setPasskeys] = React.useState<PasskeyAccount | null>(null);
  const [policy, setPolicy] = React.useState<AuthenticatorPolicy | null>(null);
  const [currentUserId, setCurrentUserId] = React.useState<string | null>(null);
  const [passkeyLabel, setPasskeyLabel] = React.useState("");
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
    setLoading(true);
    try {
      const [ownPasskeys, currentSession] = await Promise.all([
        getPasskeys(),
        getSession(),
      ]);
      setPasskeys(ownPasskeys);
      setCurrentUserId(currentSession?.user_id ?? null);
      if (capabilities.manageIdentity) {
        const [accounts, authenticatorPolicy] = await Promise.all([
          listUsers(),
          getAuthenticatorPolicy(),
        ]);
        setUsers(accounts);
        setPolicy(authenticatorPolicy);
      }
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
      await confirmCurrentAuthentication(confirmationPassword);
      setConfirmationPassword("");
      setMessage("Identity confirmed. High-impact actions are available for five minutes.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Password confirmation failed");
    }
  };

  const enrollPasskey = async () => {
    if (!passkeyLabel.trim()) return;
    setMessage(null);
    try {
      const options = await beginPasskeyRegistration();
      const credential = await createPasskeyCredential(options);
      setPasskeys(await completePasskeyRegistration(passkeyLabel.trim(), credential));
      setPasskeyLabel("");
      setMessage("Passkey added. Future sign-ins now require your password and passkey.");
      if (capabilities.manageIdentity) void load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Passkey registration failed");
    }
  };

  const renameOwnPasskey = async (id: string, currentLabel: string) => {
    const label = window.prompt("Passkey label", currentLabel)?.trim();
    if (!label) return;
    setMessage(null);
    try {
      const updated = await renamePasskey(id, label);
      setPasskeys(current => current ? {
        ...current,
        credentials: current.credentials.map(item => item.id === id ? updated : item),
      } : current);
      setMessage("Passkey renamed.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Passkey rename failed");
    }
  };

  const removeOwnPasskey = async (id: string, label: string) => {
    if (!window.confirm(`Remove ${label}? Confirm your identity above first.`)) return;
    setMessage(null);
    try {
      await removePasskey(id);
      await load();
      setMessage("Passkey removed.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Passkey removal failed");
    }
  };

  const changePolicy = async (mode: AuthenticatorPolicyMode) => {
    setMessage(null);
    try {
      const updated = await updateAuthenticatorPolicy(mode);
      setPolicy(updated);
      setMessage("Passkey requirement updated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Policy update failed");
    }
  };

  const resetMfa = async (user: VaultUser) => {
    if (!window.confirm(
      `Reset passkey MFA for ${user.username}? Their passkeys will be removed and sessions revoked. Their password is not changed.`,
    )) return;
    setBusyId(user.id);
    setMessage(null);
    try {
      await resetUserMfa(user.id);
      await load();
      setMessage(`Passkey MFA reset for ${user.username}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "MFA reset failed");
    } finally {
      setBusyId(null);
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
          <p className="text-sm text-muted">Fixed shared-vault roles, passwords, passkeys, and authority changes.</p>
        </div>
        <button className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={onBack}>Back</button>
      </div>

      <section className="rounded-lg border border-panel bg-panel-soft p-4">
        <h3 className="font-semibold">Confirm your identity</h3>
        <p className="mt-1 text-xs text-muted">Confirmation opens a five-minute window for passkey changes, session revocation, account administration, and irreversible deletion. Accounts using MFA will also receive a passkey prompt.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input className="min-w-64 flex-1 rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" type="password" autoComplete="current-password" placeholder="Current password" value={confirmationPassword} onChange={event => setConfirmationPassword(event.target.value)} />
          <button className="rounded-md bg-accent px-3 py-2 text-sm disabled:opacity-50" disabled={!confirmationPassword} onClick={() => void confirm()}>Confirm</button>
          <button className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={() => setShowPasswordChange(value => !value)}>Change my password</button>
        </div>
      </section>

      {showPasswordChange && <PasswordChange onChanged={passwordChanged} onCancel={() => setShowPasswordChange(false)} />}

      <section className="rounded-lg border border-panel bg-panel-soft p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">Your passkeys</h3>
            <p className="mt-1 text-xs text-muted">Passkeys are a second factor after your password. Keep two where practical so one lost device does not require an Administrator reset.</p>
          </div>
          {passkeys && (
            <span className="rounded-full border border-panel-strong px-2 py-1 text-xs">
              {passkeys.mfa_enabled ? "MFA enabled" : "Password only"}
            </span>
          )}
        </div>
        {passkeys?.available === false ? (
          <p className="mt-3 text-sm text-muted">Passkeys are unavailable until the operator configures one stable supported HTTPS hostname and RP ID.</p>
        ) : (
          <>
            <div className="mt-3 flex flex-wrap gap-2">
              <input className="min-w-64 flex-1 rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" placeholder="Passkey label, for example Laptop" maxLength={128} value={passkeyLabel} onChange={event => setPasskeyLabel(event.target.value)} />
              <button className="rounded-md bg-accent px-3 py-2 text-sm disabled:opacity-50" disabled={!passkeyLabel.trim()} onClick={() => void enrollPasskey()}>Add passkey</button>
            </div>
            <p className="mt-2 text-xs text-muted">Confirm your identity above before adding a passkey. Once MFA is enabled, confirmation also requires an existing passkey.</p>
            <div className="mt-3 space-y-2">
              {passkeys?.credentials.map(passkey => (
                <div key={passkey.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-panel-strong bg-panel p-3">
                  <div>
                    <div className="font-medium">{passkey.label}</div>
                    <div className="text-xs text-muted">
                      Added {new Date(passkey.created_at).toLocaleString()}
                      {passkey.backed_up ? " · synced/backed up" : passkey.device_type === "multi_device" ? " · backup capable, not backed up" : " · single device"}
                      {passkey.last_used_at ? ` · last used ${new Date(passkey.last_used_at).toLocaleString()}` : ""}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button className="rounded-md border border-panel-strong px-2 py-1 text-xs" onClick={() => void renameOwnPasskey(passkey.id, passkey.label)}>Rename</button>
                    <button className="rounded-md border border-red-500/60 px-2 py-1 text-xs text-red-600 dark:text-red-300" onClick={() => void removeOwnPasskey(passkey.id, passkey.label)}>Remove</button>
                  </div>
                </div>
              ))}
              {passkeys && passkeys.credentials.length === 0 && <p className="text-sm text-muted">No passkeys enrolled.</p>}
            </div>
          </>
        )}
      </section>

      {capabilities.manageIdentity && <>
        <section className="rounded-lg border border-panel bg-panel-soft p-4">
          <h3 className="font-semibold">Passkey requirement</h3>
          <p className="mt-1 text-xs text-muted">Optional is the default. A required mode can be selected only after every enabled targeted account has enrolled.</p>
          {policy && (
            <div className="mt-3 space-y-2">
              <select aria-label="Passkey requirement" className="w-full rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" value={policy.mode} disabled={!policy.available} onChange={event => void changePolicy(event.target.value as AuthenticatorPolicyMode)}>
                <option value="optional">Optional</option>
                <option value="require_administrators" disabled={policy.require_administrators_blockers.length > 0}>Require Administrators</option>
                <option value="require_all" disabled={policy.require_all_blockers.length > 0}>Require everyone</option>
              </select>
              {policy.require_administrators_blockers.length > 0 && <p className="text-xs text-muted">Administrators still needing enrollment: {policy.require_administrators_blockers.join(", ")}</p>}
              {policy.require_all_blockers.length > 0 && <p className="text-xs text-muted">Enabled accounts still needing enrollment: {policy.require_all_blockers.join(", ")}</p>}
              <p className="text-xs text-muted">Confirm your identity above before changing this setting. Required policy also prevents removing or resetting the targeted account’s last passkey.</p>
              <p className="text-xs text-muted">With Require Administrators, create a Member or Viewer, let them enroll, then promote them. With Require everyone, temporarily select Optional while a new account joins and enrolls.</p>
            </div>
          )}
        </section>

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
                  <div><div className="font-semibold">{user.display_name}</div><div className="text-xs text-muted">{user.username}{user.id === currentUserId ? " · you" : ""}{user.mfa_enabled ? " · passkey MFA" : " · password only"}{user.password_change_required ? " · password change required" : ""}</div></div>
                  <select className="rounded-md border border-panel-strong bg-panel-soft px-2 py-1 text-sm" value={user.role} disabled={busyId === user.id} onChange={event => void mutate(user, { role: event.target.value as VaultRole })}>{ROLES.map(role => <option key={role} value={role}>{role}</option>)}</select>
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={user.enabled} disabled={busyId === user.id} onChange={event => void mutate(user, { enabled: event.target.checked })} />Enabled</label>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <input className="min-w-64 flex-1 rounded-md border border-panel-strong bg-panel-soft px-2 py-1 text-sm" type="password" autoComplete="new-password" placeholder="New temporary password" minLength={15} maxLength={4096} value={resetPasswords[user.id] || ""} onChange={event => setResetPasswords(current => ({ ...current, [user.id]: event.target.value }))} />
                  <button className="rounded-md border border-panel-strong px-2 py-1 text-xs disabled:opacity-50" disabled={busyId === user.id || (resetPasswords[user.id] || "").length < 15} onClick={() => void resetPassword(user)}>Set temporary password</button>
                  <button className="rounded-md border border-panel-strong px-2 py-1 text-xs" disabled={busyId === user.id} onClick={() => { const displayName = window.prompt("Display name", user.display_name); if (displayName?.trim()) void mutate(user, { display_name: displayName }); }}>Edit display name</button>
                  {user.mfa_enabled && user.id !== currentUserId && <button className="rounded-md border border-red-500/60 px-2 py-1 text-xs text-red-600 dark:text-red-300" disabled={busyId === user.id} onClick={() => void resetMfa(user)}>Reset passkey MFA</button>}
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
