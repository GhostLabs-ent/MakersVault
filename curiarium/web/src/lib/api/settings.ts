// Server settings, library scans and import-run history. Distinct from
// `../settings`, the client-side settings cache.

import { authHeaders } from "../auth";
import { apiBase } from "./baseUrl";
import { UnauthorizedError, assertOk, readErrorMessage } from "./http";

export type MountImportSettings = {
  enabled: boolean;
  copy_files: boolean;
  path?: string | null;
};

export type StorageSettings = {
  template: string;
  default_template: string;
  allowed_tokens: string[];
  sample_path: string;
  moved: number;
  skipped: number;
};

export async function getMountImportSettings(): Promise<MountImportSettings> {
  const res = await fetch(`${apiBase()}/settings/mount-import`, { headers: authHeaders() });
  assertOk(res, "Failed to load mount import settings");
  return res.json();
}

export async function updateMountImportSettings(payload: {
  enabled: boolean;
  copy_files: boolean;
}): Promise<MountImportSettings> {
  const res = await fetch(`${apiBase()}/settings/mount-import`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  assertOk(res, "Failed to update mount import settings");
  return res.json();
}

export async function getStorageSettings(): Promise<StorageSettings> {
  const res = await fetch(`${apiBase()}/settings/storage`, { headers: authHeaders() });
  assertOk(res, "Failed to load storage settings");
  return res.json();
}

export async function updateStorageSettings(payload: {
  template: string;
}): Promise<StorageSettings> {
  const res = await fetch(`${apiBase()}/settings/storage`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to update storage settings"));
  }
  return res.json();
}

/**
 * Snapshot capability of one storage volume, as detected from the mounted
 * filesystem. Detection is advisory: nothing is written to disk and no
 * snapshot is taken by reporting it.
 */
export type StorageVolumeCapability = {
  roles: string[];
  path: string;
  fstype: string;
  mount_point: string;
  snapshot_method: string;
  usable: boolean;
  reason: string;
};

export type StorageCapabilities = {
  volumes: StorageVolumeCapability[];
};

export async function getStorageCapabilities(): Promise<StorageCapabilities> {
  const res = await fetch(`${apiBase()}/storage/capabilities`, { headers: authHeaders() });
  assertOk(res, "Failed to load storage capabilities");
  return res.json();
}

export type LibraryScanStatus = {
  running: boolean;
  started_at: number | null;
  finished_at: number | null;
  registered: number;
  known: number;
  ignored: number;
  missing: number;
  failed: number;
  errors: string[];
};

export async function getLibraryScanStatus(): Promise<LibraryScanStatus> {
  const res = await fetch(`${apiBase()}/library/scan`, { headers: authHeaders() });
  assertOk(res, "Failed to read library scan status");
  return res.json();
}

export async function startLibraryScan(): Promise<LibraryScanStatus> {
  const res = await fetch(`${apiBase()}/library/scan`, { method: "POST", headers: authHeaders() });
  if (res.status === 409) {
    throw new Error("A scan is already running");
  }
  assertOk(res, "Failed to start library scan");
  return res.json();
}

/**
 * One mounted-import run as the API reports it. `status` stays a plain string
 * because the server may add outcomes; the UI treats unknown values as neutral.
 */
export type ImportRunSummary = {
  id: string;
  status: string;
  mode: string | null;
  root: string | null;
  reason: string | null;
  /** Epoch seconds. */
  started_at: number;
  /** Epoch seconds; null while the run is still walking. */
  finished_at: number | null;
  registered: number;
  known: number;
  ignored: number;
  failed: number;
  /** Oversize subset of `ignored`. */
  rejected: number;
  discovered: number;
  /** `known + ignored`. */
  skipped: number;
};

export type ImportRunDetail = ImportRunSummary & { errors: string[] };

export type ImportRunList = {
  runs: ImportRunSummary[];
  total: number;
  limit: number;
  offset: number;
};

/** Newest-first page of mounted-import runs. */
export async function getImportRuns(limit = 20, offset = 0): Promise<ImportRunList> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const res = await fetch(`${apiBase()}/imports/runs?${qs.toString()}`, { headers: authHeaders() });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to load mount import runs"));
  }
  return res.json();
}

/** One run with its per-file errors (already bounded server-side). */
export async function getImportRun(id: string): Promise<ImportRunDetail> {
  const res = await fetch(`${apiBase()}/imports/runs/${encodeURIComponent(id)}`, {
    headers: authHeaders(),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to load the mount import run"));
  }
  return res.json();
}
