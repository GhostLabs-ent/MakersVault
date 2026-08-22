import { appendTokenToUrl, authHeaders } from "./auth";
import { loadSettings } from "./settings";
import { HandoffGrant, HandoffTool } from "./handoff";

export class UnauthorizedError extends Error {
  constructor(message = "Unauthorized") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

function assertOk(res: Response, message: string) {
  if (res.status === 401) {
    throw new UnauthorizedError();
  }
  if (!res.ok) {
    throw new Error(message);
  }
}

async function readErrorMessage(res: Response, fallback: string) {
  let body = "";
  try {
    body = await res.text();
  } catch {
    return fallback;
  }
  const trimmed = body.trim();
  if (!trimmed) return fallback;
  try {
    const data = JSON.parse(trimmed);
    if (typeof data?.detail === "string" && data.detail.trim()) {
      return data.detail.trim();
    }
  } catch {
    // ignore JSON parse errors
  }
  return trimmed;
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
  preview_status: "pending" | "ready" | "failed" | "skipped_policy" | "retry_requested";
  preview_reason?: string | null;
  preview_attempts: number;
  preview_policy_version: number;
  preview_updated_at?: string | null;
  preview_source?: string | null;
  current_revision_id?: string | null;
};

export type PreparedPrint = {
  printer?: string | null;
  material?: string | null;
  nozzle_mm?: number | null;
  layer_height_mm?: number | null;
  estimated_seconds?: number | null;
  format?: string | null;
  removable?: boolean;
};

export type AssetFile = {
  id: string;
  filename: string;
  mime: string;
  size: number;
  url: string;
  revision_id?: string | null;
};

export type ArtifactRevision = {
  id: string;
  revision_number: number;
  created_at: string;
  origin_revision_id?: string | null;
  filename: string;
  mime: string;
  size: number;
  sha256?: string | null;
  content_state: "pending" | "ready" | "unavailable" | "changed" | "failed";
  content_reason?: string | null;
  content_checked_at?: string | null;
  change_note?: string | null;
  prepared_print?: PreparedPrint | null;
  url: string;
  thumb_url?: string | null;
  is_current: boolean;
};

export type RevisionMutation = {
  asset: Asset;
  revision: ArtifactRevision;
  created: boolean;
};

export type TrashItem = {
  id: string;
  name: string;
  filename: string;
  deleted_at: string;
  original_folder_id?: string | null;
  original_folder_name?: string | null;
  managed_bytes: number;
  managed_file_count: number;
  revision_count: number;
  supporting_file_count: number;
  external_source: boolean;
};

export type TrashRetentionPolicy = "until_needed" | "day" | "week" | "month" | "never";

export type TrashSettings = {
  policy: TrashRetentionPolicy;
  choices: TrashRetentionPolicy[];
  trash_count: number;
  managed_bytes: number;
  orphaned_quarantine: string[];
};

export type TrashPurgeItem = {
  asset_id: string;
  name: string;
  status: string;
  managed_files: number;
  managed_bytes: number;
  external_source_preserved: boolean;
};

export class TrashConflictError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "TrashConflictError";
    this.code = code;
  }
}

export type ImportInspectInfo = {
  filename: string;
  mime: string;
  is_zip: boolean;
};

export type ZipEntryInfo = {
  path: string;
  size: number;
};

export type ImportZipResult = {
  assets: Asset[];
  failed: string[];
};

export type ListAssetsResult = {
  items: Asset[];
  hasMore: boolean;
  nextOffset?: number;
};

export type MountImportSettings = {
  enabled: boolean;
  copy_files: boolean;
  path?: string | null;
  last_scan?: MountScan | null;
};

export type MountScanFailure = {
  path: string;
  reason: string;
};

export type MountScan = {
  id: string;
  trigger: "startup" | "manual";
  status: "running" | "completed" | "completed_with_failures" | "failed" | "interrupted";
  mode: "copy" | "index_in_place";
  root_path: string;
  started_at: string;
  finished_at?: string | null;
  imported: number;
  skipped: number;
  failed: number;
  failure_details: MountScanFailure[];
  failure_details_omitted: number;
};

export type StorageSettings = {
  template: string;
  default_template: string;
  allowed_tokens: string[];
  sample_path: string;
  moved: number;
  skipped: number;
};

export type PreviewPolicy = {
  version: number;
  active_jobs: number;
  queue_limit: number;
  automatic_max_bytes: number;
  automatic_max_triangles: number;
  automatic_3mf_expanded_bytes: number;
  automatic_3mf_entries: number;
  automatic_memory_bytes: number;
  automatic_timeout_seconds: number;
  detail_max_bytes: number;
  detail_max_triangles: number;
  detail_3mf_expanded_bytes: number;
  detail_3mf_entries: number;
  detail_memory_bytes: number;
  detail_timeout_seconds: number;
  automatic_step_enabled: boolean;
};

export type ContentHashFailure = {
  revision_id: string;
  reason: string;
};

export type ContentHashJob = {
  id: string;
  trigger: "startup" | "manual" | "verify";
  status: "running" | "completed" | "completed_with_findings" | "interrupted";
  started_at: string;
  finished_at?: string | null;
  total: number;
  processed: number;
  ready: number;
  unavailable: number;
  changed: number;
  failed: number;
  failure_details: ContentHashFailure[];
  failure_details_omitted: number;
};

let previewPolicyPromise: Promise<PreviewPolicy> | null = null;

function normalizePublicUrl(raw: string): string | null {
  const trimmed = (raw || "").trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed.replace(/\/+$/, "");
  }
  const protocol = typeof window !== "undefined" ? window.location.protocol : "http:";
  return `${protocol}//${trimmed}`.replace(/\/+$/, "");
}

function apiBaseFromPublicUrl(raw: string): string | null {
  const normalized = normalizePublicUrl(raw);
  if (!normalized) return null;
  if (/\/api\/?$/i.test(normalized)) {
    return normalized.replace(/\/+$/, "");
  }
  return `${normalized}/api`;
}

function apiBaseFromSettings(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const settings = loadSettings();
    return apiBaseFromPublicUrl(settings.network?.publicUrl || "");
  } catch {
    return null;
  }
}

function isLocalHostName(hostname: string) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

// API base URL resolution (browser-reachable)
function resolveApiBase(): string {
  const settingsBase = apiBaseFromSettings();
  if (settingsBase) return settingsBase;
  const runtimeUrl = typeof window !== "undefined"
    ? (window as unknown as { __MAKERSVAULT_CONFIG__?: { apiUrl?: string } }).__MAKERSVAULT_CONFIG__?.apiUrl
    : "";
  const envUrl = runtimeUrl || (import.meta.env.VITE_API_URL as string | undefined) || "";
  const isAbs = /^(https?:)?\/\//i.test(envUrl);
  const hasWindow = typeof window !== "undefined";
  const host = hasWindow ? window.location.hostname : "localhost";
  const port = hasWindow ? window.location.port : "";
  const protocol = hasWindow ? window.location.protocol : "http:";
  const isStandardPort = port === "" || port === "80" || port === "443";
  const isLocalHost = isLocalHostName(host);
  const isProxyContext = hasWindow && !isLocalHost && isStandardPort;

  if (envUrl) {
    if (isAbs) {
      const absolute = envUrl.startsWith("//") ? `${protocol}${envUrl}` : envUrl;
      return absolute.replace(/\/$/, "");
    } else if (!isProxyContext) {
      // If someone sets just a port like ":8000" or "8000"
      const portOnly = envUrl.replace(/^:?/, "");
      return `http://${host}:${portOnly}`.replace(/\/$/, "");
    }
  }

  // Behind a reverse proxy on 80/443, default to same-origin /api when no
  // explicit absolute API URL is configured.
  if (isProxyContext && hasWindow) {
    return `${window.location.origin}/api`.replace(/\/$/, "");
  }

  // Default: same host, API on 8000
  return `http://${host}:8000`;
}

function apiBase(): string {
  return resolveApiBase();
}

export async function listAssets(params: {
  q?: string;
  tags?: string[];
  folder_id?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<ListAssetsResult> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.tags && params.tags.length) qs.set("tags", params.tags.join(","));
  if (params.folder_id) qs.set("folder_id", params.folder_id);
  if (typeof params.limit === "number") qs.set("limit", String(params.limit));
  if (typeof params.offset === "number") qs.set("offset", String(params.offset));
  const res = await fetch(`${apiBase()}/assets?${qs.toString()}`, {
    headers: authHeaders(),
  });
  assertOk(res, "Failed to list assets");
  const items = await res.json();
  const hasMore = (res.headers.get("X-Has-More") || "").toLowerCase() === "true";
  const nextOffsetRaw = res.headers.get("X-Next-Offset");
  const nextOffset = nextOffsetRaw ? Number(nextOffsetRaw) : undefined;
  return { items, hasMore, nextOffset };
}

export async function listTags(params: {
  q?: string;
  tags?: string[];
  folder_id?: string;
} = {}): Promise<string[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.tags && params.tags.length) qs.set("tags", params.tags.join(","));
  if (params.folder_id) qs.set("folder_id", params.folder_id);
  const res = await fetch(`${apiBase()}/tags?${qs.toString()}`, {
    headers: authHeaders(),
  });
  assertOk(res, "Failed to list tags");
  return res.json();
}

export async function uploadAsset(
  file: File,
  opts: { title?: string; notes?: string; tags?: string[]; folder_id?: string }
 = {}
) {
  const fd = new FormData();
  fd.set("file", file);
  if (opts.title) fd.set("title", opts.title);
  if (opts.notes) fd.set("notes", opts.notes);
  if (opts.tags && opts.tags.length) fd.set("tags", opts.tags.join(","));
  if (opts.folder_id) fd.set("folder_id", opts.folder_id);
  const res = await fetch(`${apiBase()}/upload`, {
    method: "POST",
    body: fd,
    headers: authHeaders(),
  });
  if (res.status === 401) {
    throw new UnauthorizedError();
  }
  if (!res.ok) {
    const message = await readErrorMessage(res, "Upload failed");
    throw new Error(message);
  }
  return res.json();
}

export async function importFromLink(payload: {
  url: string;
  title?: string;
  notes?: string;
  tags?: string[];
  folder_id?: string;
  filename?: string;
  makerworld_cookie?: string;
  thingiverse_cookie?: string;
}) {
  const res = await fetch(`${apiBase()}/import`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (res.status === 401) {
    throw new UnauthorizedError();
  }
  if (!res.ok) {
    let message = "Import failed";
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") message = data.detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(message);
  }
  return res.json();
}

export async function inspectImportLink(payload: {
  url: string;
  title?: string;
  notes?: string;
  tags?: string[];
  folder_id?: string;
  filename?: string;
  makerworld_cookie?: string;
  thingiverse_cookie?: string;
}): Promise<ImportInspectInfo> {
  const res = await fetch(`${apiBase()}/import/inspect`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (res.status === 401) {
    throw new UnauthorizedError();
  }
  if (!res.ok) {
    const message = await readErrorMessage(res, "Inspect failed");
    throw new Error(message);
  }
  return res.json();
}

export async function listImportZipEntries(payload: {
  url: string;
  title?: string;
  notes?: string;
  tags?: string[];
  folder_id?: string;
  filename?: string;
  makerworld_cookie?: string;
  thingiverse_cookie?: string;
}): Promise<{ filename: string; entries: ZipEntryInfo[] }> {
  const res = await fetch(`${apiBase()}/import/zip/entries`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (res.status === 401) {
    throw new UnauthorizedError();
  }
  if (!res.ok) {
    const message = await readErrorMessage(res, "Zip listing failed");
    throw new Error(message);
  }
  return res.json();
}

export async function importZipFromLink(payload: {
  url: string;
  entries: string[];
  title?: string;
  notes?: string;
  tags?: string[];
  folder_id?: string;
  filename?: string;
  makerworld_cookie?: string;
  thingiverse_cookie?: string;
}): Promise<ImportZipResult> {
  const res = await fetch(`${apiBase()}/import/zip`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (res.status === 401) {
    throw new UnauthorizedError();
  }
  if (!res.ok) {
    const message = await readErrorMessage(res, "Zip import failed");
    throw new Error(message);
  }
  return res.json();
}

export async function setTags(id: string, tags: string[]) {
  const res = await fetch(`${apiBase()}/asset/${id}/tags`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ tags }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Tag update failed"));
  }
  return res.json();
}

export async function uploadGeneratedThumbnail(id: string, image: Blob): Promise<Asset> {
  const body = new FormData();
  body.set("file", image, "thumbnail.png");
  const res = await fetch(`${apiBase()}/asset/${id}/thumbnail-generated`, {
    method: "POST",
    headers: authHeaders(),
    body,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to save generated thumbnail"));
  }
  return res.json();
}

export function getPreviewPolicy(): Promise<PreviewPolicy> {
  if (!previewPolicyPromise) {
    previewPolicyPromise = fetch(`${apiBase()}/settings/preview-policy`, { headers: authHeaders() })
      .then(response => {
        assertOk(response, "Failed to load preview policy");
        return response.json() as Promise<PreviewPolicy>;
      })
      .catch(error => {
        previewPolicyPromise = null;
        throw error;
      });
  }
  return previewPolicyPromise;
}

export async function updatePreviewState(
  id: string,
  payload: { status: "pending" | "failed" | "skipped_policy"; reason?: string | null },
): Promise<Asset> {
  const response = await fetch(`${apiBase()}/asset/${id}/preview-state`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  assertOk(response, "Failed to update preview state");
  return response.json();
}

export async function requestPreviewRetry(id: string): Promise<Asset> {
  const response = await fetch(`${apiBase()}/asset/${id}/preview-retry`, {
    method: "POST",
    headers: authHeaders(),
  });
  assertOk(response, "Failed to retry preview");
  return response.json();
}

export async function listAssetFiles(id: string): Promise<AssetFile[]> {
  const res = await fetch(`${apiBase()}/asset/${id}/files`, { headers: authHeaders() });
  assertOk(res, "Failed to load supporting files");
  return res.json();
}

export async function uploadAssetFile(
  id: string,
  file: File,
  revisionId?: string | null,
): Promise<Asset> {
  const body = new FormData();
  body.set("file", file, file.name);
  if (revisionId) body.set("revision_id", revisionId);
  const res = await fetch(`${apiBase()}/asset/${id}/files`, {
    method: "POST",
    headers: authHeaders(),
    body,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to add file"));
  }
  return res.json();
}

export async function listArtifactRevisions(id: string): Promise<ArtifactRevision[]> {
  const res = await fetch(`${apiBase()}/asset/${id}/revisions`, { headers: authHeaders() });
  assertOk(res, "Failed to load version history");
  return res.json();
}

export async function uploadArtifactRevision(
  id: string,
  file: File,
  changeNote?: string,
  expectedCurrentRevisionId?: string | null,
): Promise<RevisionMutation> {
  const body = new FormData();
  body.set("file", file, file.name);
  if (changeNote?.trim()) body.set("change_note", changeNote.trim());
  if (expectedCurrentRevisionId) {
    body.set("expected_current_revision_id", expectedCurrentRevisionId);
  }
  const res = await fetch(`${apiBase()}/asset/${id}/revisions`, {
    method: "POST",
    headers: authHeaders(),
    body,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error(await readErrorMessage(res, "Failed to add version"));
  return res.json();
}

export async function restoreArtifactRevision(
  assetId: string,
  revisionId: string,
  changeNote?: string,
): Promise<RevisionMutation> {
  const res = await fetch(`${apiBase()}/asset/${assetId}/revisions/${revisionId}/restore`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ change_note: changeNote?.trim() || null }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error(await readErrorMessage(res, "Failed to restore version"));
  return res.json();
}

export function artifactHistoryExportUrl(assetId: string) {
  return fileUrl(`/asset/${assetId}/revisions/export`);
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
  collection?: string | null;
}) {
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

export async function deleteAsset(id: string) {
  const res = await fetch(`${apiBase()}/asset/${id}`, { method: "DELETE", headers: authHeaders() });
  assertOk(res, "Delete asset failed");
  return res.json();
}

export async function listTrash(): Promise<TrashItem[]> {
  const res = await fetch(`${apiBase()}/trash`, { headers: authHeaders() });
  assertOk(res, "Failed to load Trash");
  return res.json();
}

export async function restoreTrashAsset(
  id: string,
  restoreUnassigned = false,
): Promise<Asset> {
  const res = await fetch(`${apiBase()}/trash/${id}/restore`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ restore_unassigned: restoreUnassigned }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (res.status === 409) {
    const payload = await res.json().catch(() => null);
    const detail = payload?.detail;
    if (detail && typeof detail === "object") {
      throw new TrashConflictError(detail.code || "conflict", detail.message || "Restore conflict");
    }
  }
  if (!res.ok) throw new Error(await readErrorMessage(res, "Failed to restore model"));
  return res.json();
}

export async function permanentlyDeleteTrash(
  assetIds: string[],
  confirmation: string,
): Promise<TrashPurgeItem[]> {
  const res = await fetch(`${apiBase()}/trash/permanent`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ asset_ids: assetIds, confirmation }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error(await readErrorMessage(res, "Permanent deletion failed"));
  return res.json();
}

export async function emptyTrash(confirmation: string): Promise<TrashPurgeItem[]> {
  const res = await fetch(`${apiBase()}/trash/empty`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ asset_ids: [], confirmation }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error(await readErrorMessage(res, "Empty Trash failed"));
  return res.json();
}

export async function getTrashSettings(): Promise<TrashSettings> {
  const res = await fetch(`${apiBase()}/settings/trash`, { headers: authHeaders() });
  assertOk(res, "Failed to load Trash settings");
  return res.json();
}

export async function updateTrashSettings(policy: TrashRetentionPolicy): Promise<TrashSettings> {
  const res = await fetch(`${apiBase()}/settings/trash`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ policy }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error(await readErrorMessage(res, "Failed to update Trash settings"));
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

export async function updateAssetFolder(id: string, folder_id: string | null) {
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

export async function createHandoff(id: string, tool: HandoffTool): Promise<HandoffGrant> {
  const res = await fetch(`${apiBase()}/asset/${id}/handoff`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ tool }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Unable to create bridge handoff"));
  }
  const handoff = await res.json() as HandoffGrant;
  return {
    ...handoff,
    redeem_url: `${apiBase()}${handoff.redeem_url}`,
  };
}

export function fileUrl(rel: string) {
  // API returns relative URLs. Join with API base.
  if (!rel) return rel;
  return appendTokenToUrl(`${apiBase()}${rel}`);
}

// Folders -------------------------------------------------------

export type Folder = { id: string; name: string; tags: string[]; parent_id?: string | null };

export async function listFolders(): Promise<Folder[]> {
  const res = await fetch(`${apiBase()}/folders`, { headers: authHeaders() });
  assertOk(res, "Failed to list folders");
  return res.json();
}

export async function createFolder(name: string, tags: string[] = [], parent_id?: string | null) {
  const res = await fetch(`${apiBase()}/folders`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ name, tags, parent_id }),
  });
  assertOk(res, "Create folder failed");
  return res.json();
}

export async function updateFolder(id: string, name: string, tags: string[], parent_id?: string | null) {
  const res = await fetch(`${apiBase()}/folder/${id}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ name, tags, parent_id }),
  });
  assertOk(res, "Update folder failed");
  return res.json();
}

export async function deleteFolder(id: string) {
  const res = await fetch(`${apiBase()}/folder/${id}`, { method: "DELETE", headers: authHeaders() });
  assertOk(res, "Delete folder failed");
  return res.json();
}

export async function downloadZip(opts: { asset_ids?: string[]; tag?: string; folder_id?: string; filename?: string }) {
  const res = await fetch(`${apiBase()}/download/zip`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(opts),
  });
  assertOk(res, "Download failed");
  return res;
}

export async function downloadFolderZip(folder_id: string) {
  const res = await fetch(`${apiBase()}/folder/${folder_id}/download`, { headers: authHeaders() });
  assertOk(res, "Folder download failed");
  return res;
}

export type HealthInfo = { ok: boolean; auth_required: boolean };

export async function apiHealth(): Promise<HealthInfo | null> {
  try {
    const res = await fetch(`${apiBase()}/health`, { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    return {
      ok: Boolean(data?.ok),
      auth_required: Boolean(data?.auth_required),
    };
  } catch {
    return null;
  }
}

export function getApiBase() {
  return apiBase();
}

export async function login(username: string, password: string): Promise<{ token: string; expires_in: number }> {
  const res = await fetch(`${apiBase()}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    let message = "Login failed";
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") message = data.detail;
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  return res.json();
}

export async function refreshToken(): Promise<{ token: string; expires_in: number }> {
  const res = await fetch(`${apiBase()}/refresh`, {
    method: "POST",
    headers: authHeaders(),
  });
  assertOk(res, "Token refresh failed");
  return res.json();
}

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

export async function getMountImportScan(): Promise<MountScan | null> {
  const res = await fetch(`${apiBase()}/settings/mount-import/scan`, { headers: authHeaders() });
  assertOk(res, "Failed to load mounted import scan");
  return res.json();
}

export async function rescanMountImport(): Promise<{ scan: MountScan; started: boolean }> {
  const res = await fetch(`${apiBase()}/settings/mount-import/rescan`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (res.status === 401) {
    throw new UnauthorizedError();
  }
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to start mounted import scan"));
  }
  return res.json();
}

export async function getStorageSettings(): Promise<StorageSettings> {
  const res = await fetch(`${apiBase()}/settings/storage`, { headers: authHeaders() });
  assertOk(res, "Failed to load storage settings");
  return res.json();
}

export async function updateStorageSettings(payload: {
  template: string;
  apply_existing: boolean;
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

export async function getContentIdentityJob(): Promise<ContentHashJob | null> {
  const res = await fetch(`${apiBase()}/settings/content-identity`, { headers: authHeaders() });
  assertOk(res, "Failed to load content identity status");
  return res.json();
}

export async function startContentIdentityBackfill(
  verifyAll = false
): Promise<{ job: ContentHashJob | null; started: boolean }> {
  const res = await fetch(`${apiBase()}/settings/content-identity/backfill`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ verify_all: verifyAll }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to start content verification"));
  }
  return res.json();
}
