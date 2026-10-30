import React, { type ReactElement } from "react";
import ConfirmDialog from "../ConfirmDialog";
import type { SnapshotEntry, SnapshotRetention } from "../../lib/api";
import {
  DB_CAVEAT,
  formatSnapshotAge,
  reasonLabel,
  snapshotMethodLine,
  takeSnapshotDisabledReason,
} from "../../lib/snapshotUi";
import type { StorageCapabilitiesState } from "./useStorageCapabilities";
import { useSnapshots } from "./useSnapshots";

type Props = {
  capabilities: StorageCapabilitiesState;
  canManage: boolean;
  onUnauthorized?: () => void;
};

// The server's `RetentionPolicy` defaults; replaced by the loaded policy in the effect below.
const SERVER_DEFAULT_DRAFT: SnapshotRetention = {
  keep_last_n: 20,
  keep_daily: 7,
  max_age_days: 30,
  hard_cap: 100,
};

/** Parent of a snapshot-relative path, or null at the snapshot root. */
function parentPath(path: string): string | null {
  const trimmed = path.replace(/\/+$/, "");
  const index = trimmed.lastIndexOf("/");
  if (index <= 0) return null;
  return trimmed.slice(0, index);
}

function parseCount(raw: string): number {
  const value = Number(raw);
  return Number.isFinite(value) ? Math.trunc(value) : 0;
}

export default function SnapshotCard({
  capabilities,
  canManage,
  onUnauthorized,
}: Props): ReactElement {
  const state = useSnapshots({ canManage, onUnauthorized });
  const [pendingDelete, setPendingDelete] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState<SnapshotRetention>(SERVER_DEFAULT_DRAFT);

  React.useEffect(() => {
    if (state.retention) setDraft(state.retention);
  }, [state.retention]);

  const reason = takeSnapshotDisabledReason(capabilities);
  const browse = state.browse;

  const renderControls = (name: string): ReactElement => (
    <div className="flex items-center gap-2">
      {state.list?.supports_browse && (
        <button
          type="button"
          className="text-xs px-2 py-1 rounded-md border border-panel-strong"
          onClick={() => void state.browseInto(name, "")}
        >
          Browse
        </button>
      )}
      {state.list?.supports_restore && (
        <button
          type="button"
          className="text-xs px-2 py-1 rounded-md border border-panel-strong"
          onClick={() => void state.restore(name, "")}
        >
          Restore
        </button>
      )}
      <button
        type="button"
        className="text-xs px-2 py-1 rounded-md border border-panel-strong text-red-400"
        onClick={() => setPendingDelete(name)}
      >
        Delete
      </button>
    </div>
  );

  const renderEntry = (entry: SnapshotEntry): ReactElement => {
    if (entry.is_dir) {
      return (
        <button
          type="button"
          className="text-left text-sm"
          onClick={() => browse && void state.browseInto(browse.snapshot, entry.path)}
        >
          {entry.name}/
        </button>
      );
    }
    return (
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm">{entry.name}</span>
        <button
          type="button"
          className="text-xs px-2 py-1 rounded-md border border-panel-strong"
          onClick={() => browse && void state.restore(browse.snapshot, entry.path)}
        >
          {`Restore ${entry.name}`}
        </button>
      </div>
    );
  };

  return (
    <div className="rounded-lg border border-panel bg-panel-soft p-4 flex flex-col gap-3">
      <div>
        <div className="text-lg font-semibold">Filesystem snapshots</div>
        <p className="text-sm opacity-70">
          Snapshots are taken on the server&apos;s snapshot-capable library volume and listed here.
        </p>
      </div>

      {state.loading && <p className="text-sm opacity-70">Reading snapshots…</p>}
      {!state.loading && state.error && <p className="text-sm text-red-400">{state.error}</p>}
      {!state.loading && !state.error && (
        <p className="text-sm opacity-70">{snapshotMethodLine(state.list?.method ?? "")}</p>
      )}

      {canManage && (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="text-sm px-3 py-2 rounded-md bg-accent disabled:opacity-60"
            disabled={Boolean(reason) || state.busy}
            aria-describedby={reason ? "snapshot-take-reason" : undefined}
            onClick={() => void state.take()}
          >
            Take snapshot now
          </button>
          {reason && (
            <p id="snapshot-take-reason" className="text-xs opacity-70">
              {reason}
            </p>
          )}
        </div>
      )}

      {state.notice && <p className="text-sm text-emerald-400">{state.notice}</p>}
      {state.actionError && <p className="text-sm text-red-400">{state.actionError}</p>}

      {state.list && state.list.snapshots.length === 0 && (
        <p className="text-sm opacity-70">No snapshots have been taken yet.</p>
      )}
      {state.list && state.list.snapshots.length > 0 && (
        <ul aria-label="Snapshots" className="flex flex-col gap-2">
          {state.list.snapshots.map(entry => (
            <li
              key={entry.name}
              className="flex items-center justify-between gap-2 rounded-md border border-dashed border-panel-strong p-2"
            >
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">{entry.name}</span>
                <span className="text-xs opacity-70">
                  {reasonLabel(entry.reason)} · {formatSnapshotAge(entry.age_seconds)}
                </span>
              </div>
              {canManage && renderControls(entry.name)}
            </li>
          ))}
        </ul>
      )}

      {browse && (
        <div className="rounded-md border border-dashed border-panel-strong p-3 flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium">{browse.snapshot}</span>
            <button
              type="button"
              className="text-xs px-2 py-1 rounded-md border border-panel-strong"
              onClick={() => state.closeBrowse()}
            >
              Back to snapshot list
            </button>
          </div>
          <div className="font-mono text-[11px] break-all">{browse.path || "/"}</div>
          {parentPath(browse.path) !== null && (
            <button
              type="button"
              className="self-start text-xs px-2 py-1 rounded-md border border-panel-strong"
              onClick={() => void state.browseInto(browse.snapshot, parentPath(browse.path) ?? "")}
            >
              Up one level
            </button>
          )}
          <ul className="flex flex-col gap-1">
            {browse.entries.map(entry => (
              <li key={entry.path}>{renderEntry(entry)}</li>
            ))}
          </ul>
        </div>
      )}
      {state.browseError && <p className="text-sm text-red-400">{state.browseError}</p>}

      {canManage && (
        <div className="rounded-md border border-dashed border-panel-strong p-3 flex flex-col gap-3">
          <div className="text-base font-semibold">Retention policy</div>
          {state.retentionLoading && (
            <p className="text-sm opacity-70">Reading the retention policy…</p>
          )}
          {state.retentionError && <p className="text-sm text-red-400">{state.retentionError}</p>}
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-muted">Keep last N snapshots</span>
            <input
              type="number"
              min={1}
              className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong text-sm"
              value={draft.keep_last_n}
              onChange={event =>
                setDraft(prev => ({ ...prev, keep_last_n: parseCount(event.target.value) }))
              }
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-muted">Keep daily snapshots for</span>
            <input
              type="number"
              min={0}
              className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong text-sm"
              value={draft.keep_daily}
              onChange={event =>
                setDraft(prev => ({ ...prev, keep_daily: parseCount(event.target.value) }))
              }
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-muted">
              Delete snapshots older than (days)
            </span>
            <input
              type="number"
              min={1}
              className="px-3 py-2 rounded-md border border-panel-strong bg-panel-strong text-sm"
              value={draft.max_age_days}
              onChange={event =>
                setDraft(prev => ({ ...prev, max_age_days: parseCount(event.target.value) }))
              }
            />
          </label>
          <p className="text-sm opacity-70">
            Hard cap: {draft.hard_cap} snapshots. The server never keeps more than this.
          </p>
          <p className="text-xs opacity-70">{DB_CAVEAT}</p>
          <button
            type="button"
            className="self-start text-sm px-3 py-2 rounded-md bg-accent disabled:opacity-60"
            disabled={state.retentionSaving || state.retention === null}
            onClick={() => void state.saveRetention(draft)}
          >
            Save retention policy
          </button>
        </div>
      )}

      {pendingDelete !== null && (
        <ConfirmDialog
          title={`Delete the snapshot ${pendingDelete}?`}
          body="The snapshot is removed from the server. Files restored from it earlier are unaffected."
          confirmLabel="Delete snapshot"
          danger
          busy={state.busy}
          onConfirm={async () => {
            await state.remove(pendingDelete);
            setPendingDelete(null);
          }}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
