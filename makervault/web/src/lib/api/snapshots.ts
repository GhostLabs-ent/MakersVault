// Filesystem snapshots of the configured storage volumes. Transport only: the
// API decides which method (CephFS, ZFS, Btrfs, local copy) is in play, this
// module just binds to the routes it exposes.

import { authHeaders } from "../auth";
import { apiBase } from "./baseUrl";
import { UnauthorizedError, assertOk, readErrorMessage } from "./http";

/** One snapshot as the server lists it. Field names come off the wire verbatim. */
export type Snapshot = {
  name: string;
  created_at: string;
  age_seconds: number;
  reason: string;
};

export type SnapshotList = {
  snapshots: Snapshot[];
  method: string;
  supports_browse: boolean;
  supports_restore: boolean;
};

export type SnapshotPrune = {
  pruned: number;
  kept: number;
  names: string[];
};

export type SnapshotCreated = {
  snapshot: Snapshot;
  prune: SnapshotPrune;
};

export type SnapshotEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  modified_at: string | null;
};

export type SnapshotBrowse = {
  snapshot: string;
  path: string;
  entries: SnapshotEntry[];
};

export type SnapshotRestore = {
  snapshot: string;
  path: string;
  destination: string;
  files: number;
  bytes: number;
  scan_started: boolean;
};

export type SnapshotDeleteResult = {
  ok: boolean;
  name: string;
};

export type SnapshotRetention = {
  keep_last_n: number;
  keep_daily: number;
  max_age_days: number;
  hard_cap: number;
};

/** The snapshot list; always answers 200, with method `none` when unsupported. */
export async function listSnapshots(): Promise<SnapshotList> {
  const res = await fetch(`${apiBase()}/snapshots`, { headers: authHeaders() });
  assertOk(res, "Failed to load snapshots");
  return res.json();
}

/**
 * Take a snapshot now. The request carries no body at all: the server mints the
 * `manual` reason itself, and retention may prune old snapshots in the reply.
 */
export async function takeSnapshot(): Promise<SnapshotCreated> {
  const res = await fetch(`${apiBase()}/snapshots`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to take a snapshot"));
  }
  return res.json();
}

/** Admin-only: the current retention policy. */
export async function getSnapshotRetention(): Promise<SnapshotRetention> {
  const res = await fetch(`${apiBase()}/snapshots/retention`, { headers: authHeaders() });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to load snapshot retention"));
  }
  return res.json();
}

/**
 * Admin-only: replace the retention policy. All four fields are required and
 * `hard_cap` must be echoed back, so the caller sends the whole object.
 */
export async function updateSnapshotRetention(
  policy: SnapshotRetention,
): Promise<SnapshotRetention> {
  const res = await fetch(`${apiBase()}/snapshots/retention`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(policy),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to update snapshot retention"));
  }
  return res.json();
}

/** List one directory inside a snapshot; the server orders dirs before files. */
export async function browseSnapshot(name: string, path = ""): Promise<SnapshotBrowse> {
  const qs = new URLSearchParams({ path }).toString();
  const res = await fetch(
    `${apiBase()}/snapshots/${encodeURIComponent(name)}/browse?${qs}`,
    { headers: authHeaders() },
  );
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to browse the snapshot"));
  }
  return res.json();
}

/** Restore one path out of a snapshot; a 409 detail means the target exists. */
export async function restoreSnapshot(name: string, path: string): Promise<SnapshotRestore> {
  const res = await fetch(`${apiBase()}/snapshots/${encodeURIComponent(name)}/restore`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ path }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to restore from the snapshot"));
  }
  return res.json();
}

/** Admin-only: drop one snapshot. */
export async function deleteSnapshot(name: string): Promise<SnapshotDeleteResult> {
  const res = await fetch(`${apiBase()}/snapshots/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to delete the snapshot"));
  }
  return res.json();
}
