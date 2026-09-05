import React from "react";

import { changeOwnPassword, type LoginResult } from "../lib/api";
import { confirmCurrentAuthentication } from "../lib/passkeyFlows";


type Props = {
  required?: boolean;
  onChanged: (session: LoginResult) => void;
  onCancel?: () => void;
};


export default function PasswordChange({ required = false, onChanged, onCancel }: Props) {
  const [password, setPassword] = React.useState("");
  const [confirmation, setConfirmation] = React.useState("");
  const [currentPassword, setCurrentPassword] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password !== confirmation) {
      setMessage("The new passwords do not match.");
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await confirmCurrentAuthentication(currentPassword);
      const session = await changeOwnPassword(password);
      setCurrentPassword("");
      setPassword("");
      setConfirmation("");
      onChanged(session);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Password change failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="mx-auto flex w-full max-w-lg flex-col gap-4 rounded-xl border border-panel bg-panel-soft p-6 shadow-xl" onSubmit={submit}>
      <div>
        <h2 className="text-xl font-semibold">{required ? "Choose a new password" : "Change password"}</h2>
        <p className="mt-1 text-sm text-muted">
          Use at least 15 characters. Spaces and Unicode are supported; composition rules are not required.
        </p>
        {required && <p className="mt-2 text-sm">Your temporary or legacy password must be replaced before opening the vault.</p>}
      </div>
      <label className="flex flex-col gap-1 text-sm">
        <span>Current password</span>
        <input className="rounded-md border border-panel-strong bg-panel px-3 py-2" type="password" autoComplete="current-password" maxLength={4096} value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} required />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span>New password</span>
        <input className="rounded-md border border-panel-strong bg-panel px-3 py-2" type="password" autoComplete="new-password" minLength={15} maxLength={4096} value={password} onChange={event => setPassword(event.target.value)} required />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span>Confirm new password</span>
        <input className="rounded-md border border-panel-strong bg-panel px-3 py-2" type="password" autoComplete="new-password" minLength={15} maxLength={4096} value={confirmation} onChange={event => setConfirmation(event.target.value)} required />
      </label>
      {message && <p className="text-sm text-red-700 dark:text-red-300" aria-live="polite">{message}</p>}
      <div className="flex gap-2">
        <button className="rounded-md bg-accent px-3 py-2 text-sm disabled:opacity-50" disabled={saving || !currentPassword || password.length < 15 || confirmation.length < 15} type="submit">{saving ? "Changing…" : "Change password"}</button>
        {onCancel && <button className="rounded-md border border-panel-strong px-3 py-2 text-sm" type="button" onClick={onCancel}>{required ? "Sign out" : "Cancel"}</button>}
      </div>
    </form>
  );
}
