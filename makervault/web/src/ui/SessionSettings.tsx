import React from "react";

import {
  BrowserSession,
  UnauthorizedError,
  getBrowserSessions,
  revokeAllBrowserSessions,
  revokeBrowserSession,
} from "../lib/api";
import { confirmCurrentAuthentication } from "../lib/passkeyFlows";


type Props = {
  onBack: () => void;
  onUnauthorized?: () => void;
};


function timestamp(value: number) {
  return new Date(value * 1000).toLocaleString();
}


export default function SessionSettings({ onBack, onUnauthorized }: Props) {
  const [sessions, setSessions] = React.useState<BrowserSession[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [message, setMessage] = React.useState<string | null>(null);
  const [password, setPassword] = React.useState("");

  const load = React.useCallback(async () => {
    setLoading(true);
    setMessage(null);
    try {
      setSessions(await getBrowserSessions());
    } catch (error) {
      if (error instanceof UnauthorizedError) onUnauthorized?.();
      else setMessage(error instanceof Error ? error.message : "Failed to load sessions.");
    } finally {
      setLoading(false);
    }
  }, [onUnauthorized]);

  React.useEffect(() => { void load(); }, [load]);

  const revokeOne = async (session: BrowserSession) => {
    setMessage(null);
    try {
      await revokeBrowserSession(session.id);
      if (session.current) {
        onUnauthorized?.();
        return;
      }
      setSessions(current => current.filter(item => item.id !== session.id));
      setMessage("Session revoked.");
    } catch (error) {
      if (error instanceof UnauthorizedError) onUnauthorized?.();
      else setMessage(error instanceof Error ? error.message : "Failed to revoke session.");
    }
  };

  const revokeAll = async () => {
    setMessage(null);
    try {
      await revokeAllBrowserSessions();
      onUnauthorized?.();
    } catch (error) {
      if (error instanceof UnauthorizedError) onUnauthorized?.();
      else setMessage(error instanceof Error ? error.message : "Failed to revoke sessions.");
    }
  };

  const confirmPassword = async () => {
    setMessage(null);
    try {
      await confirmCurrentAuthentication(password);
      setPassword("");
      setMessage("Identity confirmed. Session revocation is available for five minutes.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Password confirmation failed.");
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Browser Sessions</h2>
          <p className="text-sm opacity-70">
            Review signed-in browsers and revoke access without changing your password.
          </p>
        </div>
        <button className="text-sm px-3 py-2 rounded-md border border-panel-strong" onClick={onBack}>
          Back
        </button>
      </div>

      {message && <div className="text-sm">{message}</div>}
      <div className="rounded-lg border border-panel bg-panel-soft p-4">
        <div className="text-sm font-medium">Confirm before revoking sessions</div>
        <p className="mt-1 text-xs text-muted">Accounts using MFA will also be prompted for a passkey.</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <input className="min-w-64 flex-1 rounded-md border border-panel-strong bg-panel px-3 py-2 text-sm" type="password" autoComplete="current-password" placeholder="Current password" value={password} onChange={event => setPassword(event.target.value)} />
          <button className="rounded-md bg-accent px-3 py-2 text-sm disabled:opacity-50" disabled={!password} onClick={() => void confirmPassword()}>Confirm</button>
        </div>
      </div>
      {loading ? (
        <div className="text-sm opacity-70">Loading sessions…</div>
      ) : (
        <div className="flex flex-col gap-3">
          {sessions.map(session => (
            <div key={session.id} className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-wrap justify-between gap-3">
              <div className="min-w-0">
                <div className="font-medium">
                  {session.current ? "This browser" : "Signed-in browser"}
                </div>
                <div className="text-xs opacity-70 break-words">
                  {session.user_agent || "Unknown browser"}
                </div>
                <div className="text-xs opacity-70">
                  {session.client_address || "Unknown address"} · Last used {timestamp(session.last_seen_at)}
                </div>
                <div className="text-xs opacity-70">
                  Idle expiry {timestamp(session.idle_expires_at)} · Final expiry {timestamp(session.absolute_expires_at)}
                </div>
              </div>
              <button
                className="self-center text-sm px-3 py-2 rounded-md border border-red-500/60 text-red-600 dark:text-red-300"
                onClick={() => void revokeOne(session)}
              >
                {session.current ? "Sign out" : "Revoke"}
              </button>
            </div>
          ))}
          {!sessions.length && <div className="text-sm opacity-70">No active sessions.</div>}
        </div>
      )}

      <div>
        <button
          className="text-sm px-3 py-2 rounded-md border border-red-500/60 text-red-600 dark:text-red-300 disabled:opacity-50"
          disabled={loading || sessions.length === 0}
          onClick={() => {
            if (confirm("Sign out every browser session, including this one?")) void revokeAll();
          }}
        >
          Sign out everywhere
        </button>
      </div>
    </div>
  );
}
