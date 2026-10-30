import { useEffect, useMemo, useState } from "react";
import {
  UnauthorizedError,
  listAuditEvents,
  type AuditPage,
  type AuditQuery,
} from "../lib/api";
import { useStableCallback } from "../lib/useStableCallback";

/** `assertOk` turns a 403 into exactly this message; the page replaces it. */
const FORBIDDEN_MESSAGE = "Your role does not allow this action.";
const FORBIDDEN_NOTICE = "Administrator access required.";
const PAGE_SIZE = 50;

const AUDIT_ACTIONS = [
  "asset.create",
  "asset.delete",
  "asset.rename",
  "asset.move",
  "asset.file.delete",
  "asset.prepared_print.delete",
  "folder.delete",
  "folder.rename",
  "folder.move",
  "trash.purge",
  "settings.storage.update",
  "settings.mount_import.update",
  "user.create",
  "user.role_change",
  "user.disable",
  "user.enable",
  "library.scan.start",
  "login.succeeded",
  "snapshot.schedule.skipped",
  "snapshot.schedule.failed",
];

type Props = {
  onUnauthorized?: () => void;
};

function errorMessage(err: unknown, fallback: string) {
  if (err instanceof Error && err.message.trim()) return err.message;
  return fallback;
}

/** The timestamp is rendered as sent when it is not a date the browser parses. */
function formatTimestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

/** Compact JSON; a detail the browser cannot serialise renders as nothing. */
function formatDetail(detail: Record<string, unknown> | null) {
  if (!detail) return "";
  try {
    return JSON.stringify(detail);
  } catch {
    return "";
  }
}

export default function AuditLog({ onUnauthorized }: Props) {
  // Free-text filters are committed on Enter/blur; the rest apply immediately.
  const [actorDraft, setActorDraft] = useState("");
  const [targetDraft, setTargetDraft] = useState("");
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [target, setTarget] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AuditPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const handleUnauthorized = useStableCallback(() => onUnauthorized?.());

  // Memoised on primitives only, so the effect below fires once per change.
  const query = useMemo<AuditQuery>(
    () => ({
      actor: actor || undefined,
      action: action || undefined,
      target: target || undefined,
      since: since || undefined,
      until: until || undefined,
      limit: PAGE_SIZE,
      offset,
    }),
    [actor, action, target, since, until, offset]
  );

  const load = useStableCallback(async (params: AuditQuery) => {
    setLoading(true);
    setError(null);
    try {
      setPage(await listAuditEvents(params));
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        handleUnauthorized();
        return;
      }
      const message = errorMessage(err, "Unable to load the audit log.");
      setError(message === FORBIDDEN_MESSAGE ? FORBIDDEN_NOTICE : message);
      setPage(null);
    } finally {
      setLoading(false);
    }
  });

  useEffect(() => {
    void load(query);
  }, [load, query]);

  const commitActor = () => {
    const value = actorDraft.trim();
    if (value === actor) return;
    setActor(value);
    setOffset(0);
  };

  const commitTarget = () => {
    const value = targetDraft.trim();
    if (value === target) return;
    setTarget(value);
    setOffset(0);
  };

  const clearFilters = () => {
    setActorDraft("");
    setTargetDraft("");
    setActor("");
    setAction("");
    setTarget("");
    setSince("");
    setUntil("");
    setOffset(0);
  };

  // The label describes the page on screen, not a request still in flight.
  const pageOffset = page?.offset ?? 0;
  const limit = page?.limit ?? PAGE_SIZE;
  const events = page?.events ?? [];
  const total = page?.total ?? 0;
  const firstRow = events.length ? pageOffset + 1 : 0;
  const lastRow = pageOffset + events.length;
  const hasPrev = pageOffset > 0;
  const hasNext = pageOffset + limit < total;

  const fieldClass =
    "px-2 py-1.5 rounded-md border border-panel-strong bg-transparent text-sm";

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
        <div>
          <div className="text-lg font-semibold">Audit log</div>
          <p className="text-sm text-muted">
            Every recorded action, newest first. Administrator access is enforced by the API,
            not by this page.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-muted">
            <span>Actor</span>
            <input
              aria-label="Actor"
              className={fieldClass}
              value={actorDraft}
              placeholder="Any actor"
              onChange={event => setActorDraft(event.target.value)}
              onBlur={commitActor}
              onKeyDown={event => {
                if (event.key === "Enter") commitActor();
              }}
            />
          </label>

          <label className="flex flex-col gap-1 text-xs text-muted">
            <span>Action</span>
            <select
              aria-label="Action"
              className={fieldClass}
              value={action}
              onChange={event => {
                setAction(event.target.value);
                setOffset(0);
              }}
            >
              <option value="">Any action</option>
              {AUDIT_ACTIONS.map(name => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs text-muted">
            <span>Target</span>
            <input
              aria-label="Target"
              className={fieldClass}
              value={targetDraft}
              placeholder="Any target"
              onChange={event => setTargetDraft(event.target.value)}
              onBlur={commitTarget}
              onKeyDown={event => {
                if (event.key === "Enter") commitTarget();
              }}
            />
          </label>

          <label className="flex flex-col gap-1 text-xs text-muted">
            <span>Since</span>
            <input
              aria-label="Since"
              type="date"
              className={fieldClass}
              value={since}
              onChange={event => {
                setSince(event.target.value);
                setOffset(0);
              }}
            />
          </label>

          <label className="flex flex-col gap-1 text-xs text-muted">
            <span>Until</span>
            <input
              aria-label="Until"
              type="date"
              className={fieldClass}
              value={until}
              onChange={event => {
                setUntil(event.target.value);
                setOffset(0);
              }}
            />
          </label>

          <button
            type="button"
            className="px-3 py-1.5 rounded-md border border-panel-strong text-sm"
            onClick={clearFilters}
          >
            Clear
          </button>
        </div>
      </div>

      <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
        {error && <p className="text-sm text-red-400">{error}</p>}

        {!error && loading && !page && <p className="text-sm text-muted">Loading audit log…</p>}

        {!error && !loading && events.length === 0 && (
          <p className="text-sm text-muted">No audit entries match these filters.</p>
        )}

        {events.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-muted">
                  <th className="px-2 py-2 font-medium">When</th>
                  <th className="px-2 py-2 font-medium">Actor</th>
                  <th className="px-2 py-2 font-medium">Action</th>
                  <th className="px-2 py-2 font-medium">Target</th>
                  <th className="px-2 py-2 font-medium">Request</th>
                  <th className="px-2 py-2 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-panel">
                {events.map(event => (
                  <tr key={event.id}>
                    <td className="px-2 py-2 whitespace-nowrap">
                      {formatTimestamp(event.created_at)}
                    </td>
                    <td className="px-2 py-2">
                      <div className="font-medium">{event.actor}</div>
                      <div className="text-xs text-muted">
                        {event.actor_role} · {event.actor_kind}
                      </div>
                    </td>
                    <td className="px-2 py-2 font-mono text-xs">{event.action}</td>
                    <td className="px-2 py-2 text-xs break-all">{event.target}</td>
                    <td
                      className="px-2 py-2 font-mono text-xs text-muted"
                      title={event.request_id}
                    >
                      {event.request_id.slice(0, 8)}
                    </td>
                    <td className="px-2 py-2 font-mono text-[11px] text-muted break-all max-w-[18rem]">
                      {formatDetail(event.detail)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 flex-wrap">
          <span className="text-sm text-muted">
            Showing {firstRow}–{lastRow} of {total}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="px-3 py-1.5 rounded-md border border-panel-strong text-sm disabled:opacity-60"
              onClick={() => setOffset(Math.max(0, pageOffset - limit))}
              disabled={!hasPrev || loading}
            >
              Previous
            </button>
            <button
              type="button"
              className="px-3 py-1.5 rounded-md border border-panel-strong text-sm disabled:opacity-60"
              onClick={() => setOffset(pageOffset + limit)}
              disabled={!hasNext || loading}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
