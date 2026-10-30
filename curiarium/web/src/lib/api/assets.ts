// Asset listing, metadata and per-asset files. The `Batch*` result types live
// here too because every batch call acts on assets.

import { authHeaders } from "../auth";
import { apiBase } from "./baseUrl";
import { primeListGrants } from "./grantPriming";
import { UnauthorizedError, assertOk, readErrorMessage } from "./http";

/**
 * `deleteAsset`'s 404: someone else already deleted the row, so the grid treats
 * it as done rather than resurrecting a phantom card.
 */
export class AssetNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AssetNotFoundError";
  }
}

export type Asset = {
  id: string;
  name: string;
  filename: string;
  mime: string;
  size: number;
  title?: string | null;
  notes?: string | null;
  creator?: string | null;
  /**
   * The household account that added this file, a username snapshot taken when
   * the row was created - not the model's designer. `creator` above is provenance
   * a person types (who designed the model); `created_by` is who uploaded it. The
   * two are different people and the card renders them as such. Null when nobody
   * was signed in (auth disabled) and on rows written before attribution existed.
   */
  created_by?: string | null;
  /**
   * Which door the file came through: `upload | link-import | zip-import |
   * mount-import | scan | system`; null only on pre-attribution rows.
   */
  created_via?: string | null;
  /**
   * @deprecated Legacy v5.1 metadata, inert since Mf-aoyv and no longer offered
   * by this client (ADR 0003); still returned by the API for old clients.
   */
  collection?: string | null;
  tags: string[];
  url: string; // relative to API host
  thumb_url?: string | null; // relative to API host
  folder_id?: string | null;
  storage_path?: string | null;
  supporting_file_count: number;
  prepared_print?: PreparedPrint | null;
  slicer_url?: string | null;
  slicer_filename?: string | null;
  /** UTC ISO-8601 timestamp of when the file was first found missing, if it is. */
  missing_since?: string | null;
  /**
   * True when the row points at a mounted/external file rather than a managed
   * copy the server owns; deleting the row never touches that file.
   */
  is_reference?: boolean;
};

export type PreparedPrint = {
  printer?: string | null;
  material?: string | null;
  nozzle_mm?: number | null;
  layer_height_mm?: number | null;
  estimated_seconds?: number | null;
  /** Canonical slicer label, or the literal "unknown" when detection failed. */
  slicer?: string | null;
  format?: string | null;
  removable?: boolean;
};

export type AssetFile = {
  id: string;
  filename: string;
  mime: string;
  size: number;
  position: number;
  url: string;
};

/** Per-asset supporting-file quotas; a `0` limit means that quota is disabled. */
export type AssetFileLimits = {
  count: number;
  total_bytes: number;
  max_count: number;
  max_file_bytes: number;
  max_total_bytes: number;
};

export type ListAssetsResult = {
  items: Asset[];
  hasMore: boolean;
  nextOffset?: number;
};

/** Per-asset failure from one of the bulk endpoints (`code` is a stable slug). */
export type BatchFailure = {
  id: string;
  code: string;
  status: number;
  error: string;
};

export type BatchTagsResult = {
  updated: Asset[];
  failed: BatchFailure[];
};

/** A creator/notes bulk edit. Absent keys stay unchanged; null clears. */
export type BatchMetaChange = {
  creator?: string | null;
  notes?: string | null;
};

export type BatchMetaResult = {
  updated: Asset[];
  failed: BatchFailure[];
};

export type BatchFolderResult = {
  updated: Asset[];
  failed: BatchFailure[];
};

export type BatchDeleteResult = {
  deleted: string[];
  failed: BatchFailure[];
};

/** One asset's delete outcome; the files went to the server's trash, not away. */
export type AssetDeleteResult = {
  ok: boolean;
  /** null when the row had no file on disk (a scan-created or mounted record). */
  trash_path: string | null;
  files: number;
  bytes: number;
};

// This module owns SnapshotNotice because schemas/assets.py owns SnapshotNoticeOut;
// the other dialogs import the type from here rather than redeclaring it.
export type SnapshotNotice = {
  /** predelete | prepurge | prebulk */
  reason: string;
  policy: "warn" | "strict";
  capability: "available" | "unavailable";
  action: "snapshot" | "proceed_without" | "refuse";
  /** The only promise the UI may make: the exact name is minted server-side. */
  pattern: string;
  name?: string | null;
  /** Why the snapshot is unavailable, when it is. */
  detail?: string | null;
};

/** Counts for a bulk delete, plus what the server will do about a snapshot. */
export type AssetDeletePreview = {
  assets: number;
  files: number;
  bytes: number;
  snapshot?: SnapshotNotice | null;
};

export async function listAssets(params: {
  q?: string;
  tags?: string[];
  folder_id?: string;
  /** Only assets that belong to no project (the files-mode "unsorted pile"). */
  not_in_project?: boolean;
  /** Exact creator, case-insensitive; blank is ignored by the server. */
  creator?: string;
  sort?: "name" | "size" | "creator";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
} = {}): Promise<ListAssetsResult> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.tags && params.tags.length) qs.set("tags", params.tags.join(","));
  if (params.folder_id) qs.set("folder_id", params.folder_id);
  if (params.not_in_project) qs.set("not_in_project", "true");
  if (params.creator) qs.set("creator", params.creator);
  if (params.sort) qs.set("sort", params.sort);
  if (params.order) qs.set("order", params.order);
  if (typeof params.limit === "number") qs.set("limit", String(params.limit));
  if (typeof params.offset === "number") qs.set("offset", String(params.offset));
  const res = await fetch(`${apiBase()}/assets?${qs.toString()}`, {
    headers: authHeaders(),
  });
  assertOk(res, "Failed to list assets");
  const items = await res.json();
  await primeListGrants(items);
  const hasMore = (res.headers.get("X-Has-More") || "").toLowerCase() === "true";
  const nextOffsetRaw = res.headers.get("X-Next-Offset");
  const nextOffset = nextOffsetRaw ? Number(nextOffsetRaw) : undefined;
  return { items, hasMore, nextOffset };
}

export async function listTags(params: {
  q?: string;
  tags?: string[];
  folder_id?: string;
  /** Scope the chip set to one project's members (project mode). */
  project_id?: string;
  /** Scope the chip set to assets in no project (files-mode "unsorted pile"). */
  not_in_project?: boolean;
} = {}): Promise<string[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.tags && params.tags.length) qs.set("tags", params.tags.join(","));
  if (params.folder_id) qs.set("folder_id", params.folder_id);
  if (params.project_id) qs.set("project_id", params.project_id);
  if (params.not_in_project) qs.set("not_in_project", "true");
  const res = await fetch(`${apiBase()}/tags?${qs.toString()}`, {
    headers: authHeaders(),
  });
  assertOk(res, "Failed to list tags");
  return res.json();
}

/** Distinct non-empty creators, scoped exactly like the tag chips. */
export async function listCreators(params: {
  q?: string;
  tags?: string[];
  folder_id?: string;
  /** Scope the facet to one project's members (project mode). */
  project_id?: string;
  /** Scope the facet to assets in no project (files-mode "unsorted pile"). */
  not_in_project?: boolean;
} = {}): Promise<string[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.tags && params.tags.length) qs.set("tags", params.tags.join(","));
  if (params.folder_id) qs.set("folder_id", params.folder_id);
  if (params.project_id) qs.set("project_id", params.project_id);
  if (params.not_in_project) qs.set("not_in_project", "true");
  const res = await fetch(`${apiBase()}/creators?${qs.toString()}`, {
    headers: authHeaders(),
  });
  assertOk(res, "Failed to list creators");
  return res.json();
}

export async function setTags(id: string, tags: string[]): Promise<Asset> {
  const res = await fetch(`${apiBase()}/asset/${id}/tags`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ tags }),
  });
  assertOk(res, "Tag update failed");
  return res.json();
}

/**
 * Adds and/or removes tags on many assets in one request. The server answers
 * 200 with per-asset results, so a partial failure is not a thrown error.
 */
export async function batchSetTags(
  asset_ids: string[],
  change: { add?: string[]; remove?: string[] },
): Promise<BatchTagsResult> {
  const res = await fetch(`${apiBase()}/assets/batch/tags`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      asset_ids,
      add_tags: change.add ?? [],
      remove_tags: change.remove ?? [],
    }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Bulk tag update failed"));
  }
  return res.json();
}

/**
 * Sets creator/notes on many assets in one request. Only the keys present in
 * `change` are sent: `undefined` leaves a field alone, explicit `null` clears it.
 */
export async function batchSetMeta(
  asset_ids: string[],
  change: BatchMetaChange,
): Promise<BatchMetaResult> {
  const body: { asset_ids: string[]; creator?: string | null; notes?: string | null } = {
    asset_ids,
  };
  if (change.creator !== undefined) body.creator = change.creator;
  if (change.notes !== undefined) body.notes = change.notes;
  const res = await fetch(`${apiBase()}/assets/batch/meta`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Bulk metadata update failed"));
  }
  return res.json();
}

export async function listAssetFiles(id: string): Promise<AssetFile[]> {
  const res = await fetch(`${apiBase()}/asset/${id}/files`, { headers: authHeaders() });
  assertOk(res, "Failed to load supporting files");
  const files = await res.json();
  await primeListGrants(files);
  return files;
}

export async function listAssetFileLimits(assetId: string): Promise<AssetFileLimits> {
  const res = await fetch(`${apiBase()}/asset/${assetId}/files/limits`, {
    headers: authHeaders(),
  });
  assertOk(res, "Failed to load supporting-file limits");
  return res.json();
}

export async function renameAssetFile(
  assetId: string,
  fileId: string,
  filename: string,
): Promise<AssetFile> {
  const res = await fetch(`${apiBase()}/asset/${assetId}/files/${fileId}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ filename }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error(await readErrorMessage(res, "Rename failed"));
  return res.json();
}

export async function reorderAssetFiles(
  assetId: string,
  fileIds: string[],
): Promise<AssetFile[]> {
  const res = await fetch(`${apiBase()}/asset/${assetId}/files/order`, {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ file_ids: fileIds }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error(await readErrorMessage(res, "Failed to reorder supporting files"));
  return res.json();
}

export async function deleteAssetFile(assetId: string, fileId: string): Promise<Asset> {
  const res = await fetch(`${apiBase()}/asset/${assetId}/files/${fileId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  assertOk(res, "Failed to remove supporting file");
  return res.json();
}

export async function deletePreparedPrint(assetId: string): Promise<Asset> {
  const res = await fetch(`${apiBase()}/asset/${assetId}/prepared-print`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  assertOk(res, "Failed to clear prepared print");
  return res.json();
}

export async function updateAssetMeta(id: string, payload: {
  name?: string | null;
  title?: string | null;
  notes?: string | null;
  creator?: string | null;
}): Promise<Asset> {
  const res = await fetch(`${apiBase()}/asset/${id}/meta`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Metadata update failed"));
  }
  return res.json();
}

/**
 * Deletes one asset. `confirmName` must be the asset's file name exactly: the
 * server enforces it with a 400, so the typed gate in the dialog is not
 * cosmetic.
 */
export async function deleteAsset(id: string, confirmName: string): Promise<AssetDeleteResult> {
  const qs = new URLSearchParams({ confirm_name: confirmName });
  const res = await fetch(`${apiBase()}/asset/${id}?${qs.toString()}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (res.status === 404) {
    throw new AssetNotFoundError(await readErrorMessage(res, "Delete asset failed"));
  }
  if (!res.ok) {
    // Surface the server's 400 (mismatched confirm_name) detail in the dialog.
    throw new Error(await readErrorMessage(res, "Delete asset failed"));
  }
  return res.json();
}

/**
 * Deletes many assets in one request; per-asset results are reported, not
 * thrown. `confirmCount` must equal `asset_ids.length` — the server rejects
 * any other number with a 400, so the stepped confirm is not cosmetic either.
 */
export async function batchDeleteAssets(
  asset_ids: string[],
  confirmCount: number,
): Promise<BatchDeleteResult> {
  const res = await fetch(`${apiBase()}/assets/batch/delete`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ asset_ids, confirm_count: confirmCount }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Bulk delete failed"));
  }
  return res.json();
}

/**
 * Preview of a bulk delete: counts and, on servers that support it, the snapshot
 * notice. Repeated `asset_ids` params, not a comma-joined list; the server
 * answers 400 when the list is empty.
 */
export async function getAssetDeletePreview(assetIds: string[]): Promise<AssetDeletePreview> {
  const qs = new URLSearchParams();
  for (const id of assetIds) qs.append("asset_ids", id);
  const res = await fetch(`${apiBase()}/assets/delete-preview?${qs.toString()}`, {
    headers: authHeaders(),
  });
  assertOk(res, "Failed to load delete preview");
  return res.json();
}

export async function renameAsset(id: string, filename: string) {
  const res = await fetch(`${apiBase()}/asset/${id}/rename`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ filename }),
  });
  assertOk(res, "Rename failed");
  return res.json();
}

export async function updateAssetFolder(id: string, folder_id: string | null): Promise<Asset> {
  const res = await fetch(`${apiBase()}/asset/${id}/folder`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ folder_id }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Folder update failed"));
  }
  return res.json();
}

/** Moves many assets to a folder (or to unassigned with `null`) in one request. */
export async function batchMoveAssets(
  asset_ids: string[],
  folder_id: string | null,
): Promise<BatchFolderResult> {
  const res = await fetch(`${apiBase()}/assets/batch/folder`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ asset_ids, folder_id }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Bulk folder update failed"));
  }
  return res.json();
}
