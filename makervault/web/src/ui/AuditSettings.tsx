import React from "react";

import { listAuditEvents, type AuditEvent } from "../lib/api";


type Props = {
  onBack: () => void;
};

const PAGE_SIZE = 50;


function resultClass(result: AuditEvent["result"]): string {
  if (result === "success") return "text-green-700 dark:text-green-300";
  if (result === "denied") return "text-amber-700 dark:text-amber-300";
  return "text-red-700 dark:text-red-300";
}


export default function AuditSettings({ onBack }: Props) {
  const [items, setItems] = React.useState<AuditEvent[]>([]);
  const [hasMore, setHasMore] = React.useState(false);
  const [nextCursor, setNextCursor] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);

  const load = React.useCallback(async (cursor?: string | null, append = false) => {
    setLoading(true);
    setMessage(null);
    try {
      const page = await listAuditEvents(PAGE_SIZE, cursor);
      setItems(current => append ? [...current, ...page.items] : page.items);
      setHasMore(page.has_more);
      setNextCursor(page.next_cursor || null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load audit events");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Security Audit</h2>
          <p className="text-sm text-muted">
            Durable outcomes for sign-in, administration, exports, handoff, settings, jobs, and content changes.
          </p>
        </div>
        <button className="rounded-md border border-panel-strong px-3 py-2 text-sm" onClick={onBack}>Back</button>
      </div>

      <div className="rounded-lg border border-panel bg-panel-soft p-4 text-sm">
        Audit records contain bounded actor, action, target, route, result, and source metadata. Request and response bodies,
        passwords, tokens, URLs, filenames, notes, and filesystem paths are not recorded.
      </div>

      {message && <p className="text-sm text-red-700 dark:text-red-300" aria-live="polite">{message}</p>}

      <div className="overflow-x-auto rounded-lg border border-panel">
        <table className="min-w-full divide-y divide-panel-strong text-left text-xs">
          <thead className="bg-panel-soft text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Time</th>
              <th className="px-3 py-2 font-medium">Result</th>
              <th className="px-3 py-2 font-medium">Actor</th>
              <th className="px-3 py-2 font-medium">Action</th>
              <th className="px-3 py-2 font-medium">Target / route</th>
              <th className="px-3 py-2 font-medium">Correlation</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-panel-strong bg-panel">
            {items.map(item => (
              <tr key={item.id}>
                <td className="whitespace-nowrap px-3 py-2">{new Date(item.occurred_at).toLocaleString()}</td>
                <td className={`px-3 py-2 font-medium ${resultClass(item.result)}`}>{item.result}</td>
                <td className="px-3 py-2">
                  <div>{item.actor_username || "Unauthenticated"}</div>
                  {item.actor_role && <div className="text-muted">{item.actor_role}</div>}
                </td>
                <td className="px-3 py-2">
                  <div className="font-mono">{item.action}</div>
                  <div className="text-muted">{item.status_code ?? "—"}</div>
                </td>
                <td className="px-3 py-2">
                  <div>{item.object_type && item.object_id ? `${item.object_type}: ${item.object_id}` : "—"}</div>
                  <div className="font-mono text-muted">{item.method} {item.route}</div>
                </td>
                <td className="max-w-48 truncate px-3 py-2 font-mono" title={item.correlation_id}>{item.correlation_id}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr><td className="px-3 py-6 text-center text-muted" colSpan={6}>No audit events recorded.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-muted">{items.length ? `${items.length} events loaded` : "No events loaded"}</span>
        <div className="flex gap-2">
          <button className="rounded-md border border-panel-strong px-3 py-2 text-sm disabled:opacity-50" disabled={loading} onClick={() => void load()}>Refresh</button>
          <button className="rounded-md border border-panel-strong px-3 py-2 text-sm disabled:opacity-50" disabled={loading || !hasMore || !nextCursor} onClick={() => void load(nextCursor, true)}>Load older</button>
        </div>
      </div>
    </div>
  );
}
