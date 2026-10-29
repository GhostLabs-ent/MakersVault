import React from "react";
import {
  UnauthorizedError,
  browseSnapshot,
  deleteSnapshot,
  getSnapshotRetention,
  listSnapshots,
  restoreSnapshot,
  takeSnapshot,
  updateSnapshotRetention,
  type SnapshotBrowse,
  type SnapshotList,
  type SnapshotRetention,
} from "../../lib/api";
import { clampRetention } from "../../lib/snapshotUi";

export type SnapshotsState = {
  list: SnapshotList | null;
  loading: boolean;
  error: string | null;
  busy: boolean;
  actionError: string | null;
  notice: string | null;
  retention: SnapshotRetention | null;
  retentionLoading: boolean;
  retentionError: string | null;
  retentionSaving: boolean;
  browse: SnapshotBrowse | null;
  browseError: string | null;
  refresh: () => Promise<void>;
  take: () => Promise<void>;
  browseInto: (name: string, path: string) => Promise<void>;
  closeBrowse: () => void;
  restore: (name: string, path: string) => Promise<void>;
  remove: (name: string) => Promise<void>;
  saveRetention: (draft: SnapshotRetention) => Promise<void>;
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
  canManage: boolean;
  onUnauthorized?: () => void;
};

/**
 * Snapshot list, retention policy and browse/restore actions for the storage
 * section. Every network call is settled, so a torn-down or mis-mocked API
 * can only turn into an error string, never an unhandled rejection.
 */
export function useSnapshots({ canManage, onUnauthorized }: Props): SnapshotsState {
  const [list, setList] = React.useState<SnapshotList | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [retention, setRetention] = React.useState<SnapshotRetention | null>(null);
  const [retentionLoading, setRetentionLoading] = React.useState(false);
  const [retentionError, setRetentionError] = React.useState<string | null>(null);
  const [retentionSaving, setRetentionSaving] = React.useState(false);
  const [browse, setBrowse] = React.useState<SnapshotBrowse | null>(null);
  const [browseError, setBrowseError] = React.useState<string | null>(null);

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
    const result = await settle(() => listSnapshots());
    if (cancelled.current) return;
    setLoading(false);
    if (!result.ok) {
      if (isUnauthorized(result.error)) {
        unauthorizedRef.current?.();
        return;
      }
      setList(null);
      setError("Snapshots are unavailable.");
      return;
    }
    setList(result.value);
    setError(null);
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  // Retention is admin-only; a non-admin must never fire the request.
  React.useEffect(() => {
    if (!canManage) return;
    setRetentionLoading(true);
    setRetentionError(null);
    void (async () => {
      const result = await settle(() => getSnapshotRetention());
      if (cancelled.current) return;
      setRetentionLoading(false);
      if (!result.ok) {
        if (isUnauthorized(result.error)) {
          unauthorizedRef.current?.();
          return;
        }
        setRetentionError("Snapshot retention is unavailable.");
        return;
      }
      setRetention(result.value);
    })();
  }, [canManage]);

  const take = React.useCallback(async () => {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    const result = await settle(() => takeSnapshot());
    if (cancelled.current) return;
    setBusy(false);
    if (!result.ok) {
      if (isUnauthorized(result.error)) {
        unauthorizedRef.current?.();
        return;
      }
      setActionError(messageFor(result.error, "Failed to take a snapshot."));
      return;
    }
    const { snapshot, prune } = result.value;
    const plural = prune.pruned === 1 ? "snapshot" : "snapshots";
    const pruneNote = prune.pruned > 0 ? ` and ${prune.pruned} older ${plural} was pruned` : "";
    setNotice(`${snapshot.name} was taken; the reason recorded is manual${pruneNote}.`);
    await refresh();
  }, [refresh]);

  const browseInto = React.useCallback(async (name: string, path: string) => {
    setBrowseError(null);
    const result = await settle(() => browseSnapshot(name, path));
    if (cancelled.current) return;
    if (!result.ok) {
      if (isUnauthorized(result.error)) {
        unauthorizedRef.current?.();
        return;
      }
      setBrowse(null);
      setBrowseError(messageFor(result.error, "Failed to browse the snapshot."));
      return;
    }
    setBrowse(result.value);
  }, []);

  const closeBrowse = React.useCallback(() => {
    if (cancelled.current) return;
    setBrowse(null);
    setBrowseError(null);
  }, []);

  const restore = React.useCallback(async (name: string, path: string) => {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    const result = await settle(() => restoreSnapshot(name, path));
    if (cancelled.current) return;
    setBusy(false);
    if (!result.ok) {
      if (isUnauthorized(result.error)) {
        unauthorizedRef.current?.();
        return;
      }
      setActionError(messageFor(result.error, "Failed to restore from the snapshot."));
      return;
    }
    const { files, bytes, destination } = result.value;
    const fileWord = files === 1 ? "file" : "files";
    setNotice(`Restored ${files} ${fileWord} (${bytes} bytes) to ${destination}.`);
    setBrowse(null);
    setBrowseError(null);
  }, []);

  const remove = React.useCallback(
    async (name: string) => {
      setBusy(true);
      setActionError(null);
      setNotice(null);
      const result = await settle(() => deleteSnapshot(name));
      if (cancelled.current) return;
      setBusy(false);
      if (!result.ok) {
        if (isUnauthorized(result.error)) {
          unauthorizedRef.current?.();
          return;
        }
        setActionError(messageFor(result.error, "Failed to delete the snapshot."));
        return;
      }
      setNotice(`${name} was deleted.`);
      await refresh();
    },
    [refresh],
  );

  const saveRetention = React.useCallback(async (draft: SnapshotRetention) => {
    const payload = clampRetention(draft);
    setRetentionSaving(true);
    setRetentionError(null);
    const result = await settle(() => updateSnapshotRetention(payload));
    if (cancelled.current) return;
    setRetentionSaving(false);
    if (!result.ok) {
      if (isUnauthorized(result.error)) {
        unauthorizedRef.current?.();
        return;
      }
      setRetentionError(messageFor(result.error, "Failed to save snapshot retention."));
      return;
    }
    // Adopt the server's response as truth rather than trusting the draft.
    setRetention(result.value);
    setNotice("Snapshot retention saved.");
  }, []);

  return {
    list,
    loading,
    error,
    busy,
    actionError,
    notice,
    retention,
    retentionLoading,
    retentionError,
    retentionSaving,
    browse,
    browseError,
    refresh,
    take,
    browseInto,
    closeBrowse,
    restore,
    remove,
    saveRetention,
  };
}
