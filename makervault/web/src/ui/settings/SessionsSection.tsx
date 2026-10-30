import React from "react";
import { UnauthorizedError, listSessions, revokeSession, type UserSession } from "../../lib/api";
import SectionHeader from "./SectionHeader";

type Props = {
  onBack: () => void;
  onUnauthorized?: () => void;
};

const LOAD_ERROR = "Sessions are unavailable right now.";
const REVOKE_ERROR = "That device could not be signed out.";
/** A full user agent is long; the head is enough to tell two browsers apart. */
const USER_AGENT_LIMIT = 80;

/** `device` first, then a shortened user agent, then a generic label. */
export function sessionDeviceLabel(session: UserSession): string {
  const device = (session.device || "").trim();
  if (device) return device;
  const agent = (session.user_agent || "").trim();
  if (!agent) return "Unknown device";
  if (agent.length <= USER_AGENT_LIMIT) return agent;
  return `${agent.slice(0, USER_AGENT_LIMIT - 1)}…`;
}

/** Epoch seconds as local time; a zero or invalid stamp degrades to "unknown". */
export function formatLastUsed(epochSeconds: number): string {
  if (!Number.isFinite(epochSeconds) || epochSeconds <= 0) return "unknown";
  const date = new Date(epochSeconds * 1000);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toLocaleString();
}

function kindLabel(kind: UserSession["kind"]): string {
  if (kind === "oidc") return "Single sign-on";
  if (kind === "break-glass") return "Break-glass";
  return "Password";
}

function Badge({ children }: { children: string }) {
  return (
    <span className="rounded-md border border-panel-strong px-2 py-0.5 text-[11px] text-muted">
      {children}
    </span>
  );
}

export default function SessionsSection({ onBack, onUnauthorized }: Props) {
  const [sessions, setSessions] = React.useState<UserSession[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [revoking, setRevoking] = React.useState<string | null>(null);
  const cancelled = React.useRef(false);

  const reload = React.useCallback(async () => {
    try {
      const list = await listSessions();
      if (cancelled.current) return;
      setSessions(list);
      setError(null);
    } catch (err) {
      if (cancelled.current) return;
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      setError(LOAD_ERROR);
    } finally {
      if (!cancelled.current) setLoading(false);
    }
  }, [onUnauthorized]);

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
      await revokeSession(sessionId);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        onUnauthorized?.();
        return;
      }
      setError(REVOKE_ERROR);
      return;
    } finally {
      setRevoking(null);
    }
    // Re-read the list instead of splicing locally: the server owns the answer.
    await reload();
  };

  const others = sessions.filter(session => !session.current);

  return (
    <div className="flex flex-col gap-4">
      <SectionHeader
        title="Sessions"
        subtitle="Devices signed in to this account."
        onBack={onBack}
      />

      {loading && <p className="text-sm opacity-70">Loading sessions…</p>}

      {error && <p className="text-xs text-red-400">{error}</p>}

      {!loading && sessions.length === 0 && (
        <p className="text-sm opacity-70">No devices are signed in.</p>
      )}

      {!loading && sessions.length > 0 && others.length === 0 && (
        <p className="text-xs opacity-70">No other devices are signed in to this account.</p>
      )}

      {sessions.map(session => (
        <div
          key={session.id}
          className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-2"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium break-all">{sessionDeviceLabel(session)}</span>
              {session.current && <Badge>This device</Badge>}
              {session.kind !== "password" && <Badge>{kindLabel(session.kind)}</Badge>}
            </div>
            {!session.current && (
              <button
                type="button"
                className="text-sm px-3 py-2 rounded-md border border-panel-strong disabled:opacity-60"
                disabled={revoking !== null}
                onClick={() => void revoke(session.id)}
              >
                {revoking === session.id ? "Revoking…" : "Revoke"}
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-2 text-sm text-muted">
            <span>{session.client_ip || "Unknown address"}</span>
            <span>Last used {formatLastUsed(session.last_used_at)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
