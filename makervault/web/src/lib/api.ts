import { appendTokenToUrl, authHeaders } from "./auth";
import { loadSettings } from "./settings";

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
  if (res.status === 403) {
    throw new Error("Your role does not allow this action.");
  }
  if (!res.ok) {
    throw new Error(message);
  }
}

/**
 * A non-2xx (or transport-level) failure from an XHR upload. `retryable` marks
 * failures the queue may safely re-attempt; a *seen* 4xx is never retryable.
 */
export class UploadRequestError extends Error {
  status?: number;
  retryable: boolean;
  constructor(message: string, status?: number, retryable = false) {
    super(message);
    this.name = "UploadRequestError";
    this.status = status;
    this.retryable = retryable;
  }
}

/** Parses an error body: JSON `detail` wins, otherwise the raw text (nginx HTML). */
function errorMessageFromBody(body: string, fallback: string): string {
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

async function readErrorMessage(res: Response, fallback: string) {
  try {
    return errorMessageFromBody(await res.text(), fallback);
  } catch {
    return fallback;
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
  format?: string | null;
  removable?: boolean;
};

export type AssetFile = {
  id: string;
  filename: string;
  mime: string;
  size: number;
  url: string;
};

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
  /** Only assets that belong to no project (the files-mode "unsorted pile"). */
  not_in_project?: boolean;
  limit?: number;
  offset?: number;
} = {}): Promise<ListAssetsResult> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.tags && params.tags.length) qs.set("tags", params.tags.join(","));
  if (params.folder_id) qs.set("folder_id", params.folder_id);
  if (params.not_in_project) qs.set("not_in_project", "true");
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

/** Generous ceiling so a stalled connection cannot hold a queue slot forever. */
const UPLOAD_TIMEOUT_MS = 15 * 60 * 1000;

function uploadAbortError(): UploadRequestError {
  const error = new UploadRequestError("Upload cancelled", undefined, false);
  // The queue keys off `name` to treat this as cancellation rather than failure.
  error.name = "AbortError";
  return error;
}

function parseUploadResponse(body: string): unknown {
  if (!body.trim()) return null;
  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

export type UploadTransportOptions = {
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
};

export function uploadAsset(
  file: File,
  opts: { title?: string; notes?: string; tags?: string[]; folder_id?: string } = {},
  transport: UploadTransportOptions = {},
): Promise<unknown> {
  return new Promise<unknown>((resolve, reject) => {
    const fd = new FormData();
    fd.set("file", file);
    if (opts.title) fd.set("title", opts.title);
    if (opts.notes) fd.set("notes", opts.notes);
    if (opts.tags && opts.tags.length) fd.set("tags", opts.tags.join(","));
    if (opts.folder_id) fd.set("folder_id", opts.folder_id);

    const signal = transport.signal;
    if (signal?.aborted) {
      reject(uploadAbortError());
      return;
    }

    const xhr = new XMLHttpRequest();
    // The API authenticates with bearer tokens, never cookies.
    xhr.withCredentials = false;
    xhr.timeout = UPLOAD_TIMEOUT_MS;
    xhr.open("POST", `${apiBase()}/upload`);
    // Content-Type is intentionally omitted: the browser adds the multipart boundary.
    authHeaders().forEach((value, key) => xhr.setRequestHeader(key, value));

    xhr.upload.addEventListener("progress", event => {
      transport.onProgress?.(event.loaded, event.total || file.size);
    });

    const onSignalAbort = () => xhr.abort();
    const detachSignal = () => signal?.removeEventListener("abort", onSignalAbort);
    signal?.addEventListener("abort", onSignalAbort, { once: true });

    xhr.addEventListener("load", () => {
      detachSignal();
      const status = xhr.status;
      if (status === 401) {
        reject(new UnauthorizedError());
        return;
      }
      if (status >= 200 && status < 300) {
        resolve(parseUploadResponse(xhr.responseText));
        return;
      }
      // Retry safety: each POST creates a fresh asset row and the server removes the
      // row and its partial file on any failure, so a retried attempt cannot leave a
      // half-written asset; a response lost after a full commit surfaces as a
      // non-retryable 409 (unique filename index) rather than a duplicate row.
      const retryable = status >= 500 || status === 429 || status === 408;
      reject(
        new UploadRequestError(
          errorMessageFromBody(xhr.responseText || "", "Upload failed"),
          status,
          retryable,
        ),
      );
    });
    xhr.addEventListener("error", () => {
      detachSignal();
      // Status 0 or a mid-body server abort (e.g. MAX_UPLOAD_MB rejected before headers).
      reject(new UploadRequestError("Network error", undefined, true));
    });
    xhr.addEventListener("timeout", () => {
      detachSignal();
      reject(new UploadRequestError("Upload timed out", undefined, true));
    });
    xhr.addEventListener("abort", () => {
      detachSignal();
      reject(uploadAbortError());
    });

    xhr.send(fd);
  });
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

/**
 * Outcome of `POST /import/project`.
 *
 * `created` is false when the same model page had already been imported, so
 * the existing project was reused. `gated` means the model's files are behind
 * an account or a purchase: the project exists with the page's details, the
 * server's `message` explains it, and nothing was downloaded. `failed` lists
 * zip entries that did not import and may be retried.
 */
export type ImportProjectResult = {
  project: Project;
  created: boolean;
  assets: Asset[];
  added: string[];
  skipped: string[];
  failed: string[];
  gated: boolean;
  message: string;
};

/**
 * Imports a model page into a project: `project_id` adds the files to an
 * existing project, `project_name` names a new one, and omitting both lets the
 * server name the project from the page. Omitting `entries` keeps the whole
 * file/zip as one asset; an array extracts exactly those zip entries.
 */
export async function importToProject(payload: {
  url: string;
  project_id?: string;
  project_name?: string;
  entries?: string[];
  title?: string;
  notes?: string;
  tags?: string[];
  folder_id?: string;
  filename?: string;
  makerworld_cookie?: string;
  thingiverse_cookie?: string;
}): Promise<ImportProjectResult> {
  const res = await fetch(`${apiBase()}/import/project`, {
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

export async function setTags(id: string, tags: string[]) {
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

export async function listAssetFiles(id: string): Promise<AssetFile[]> {
  const res = await fetch(`${apiBase()}/asset/${id}/files`, { headers: authHeaders() });
  assertOk(res, "Failed to load supporting files");
  return res.json();
}

export async function uploadAssetFile(id: string, file: File): Promise<Asset> {
  const body = new FormData();
  body.set("file", file, file.name);
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

export function fileUrl(rel: string) {
  // API returns relative URLs. Join with API base.
  if (!rel) return rel;
  return appendTokenToUrl(`${apiBase()}${rel}`);
}

/**
 * Same join as `fileUrl`, minus the session token and with the same-origin
 * `/api` prefix that nginx proxies to the API.
 *
 * `fileUrl` appends the caller's *current* access token, which rotates every
 * 15 minutes, so it can never be written into project content; and
 * `getApiBase()` is always absolute (the shipped compose defaults it to
 * `http://localhost:8000`), which would bake an origin that is dead for every
 * remote viewer into the description. Use this for URLs that get persisted —
 * a markdown image reference in a project description (Mf-dhtm).
 */
export function stableFileUrl(rel: string): string {
  if (!rel) return rel;
  return `/api${rel}`;
}

/**
 * Counterpart of `stableFileUrl` for the render side: resolve a persisted
 * project-content URL for the *current* viewer.
 *
 * The stored markdown stays token-less and stable (`stableFileUrl`); a browser
 * `<img>` sends no `Authorization` header, so each viewer has to append their
 * own short-lived token here at render time or the request would 401. Only
 * same-origin `/api/...` srcs are touched, so foreign and absolute URLs pass
 * through untouched. `appendTokenToUrl` sets the param via `URLSearchParams`,
 * which makes this idempotent and replaces an author-injected `?token=` with
 * the viewer's own.
 */
export function renderFileUrl(src: string | undefined): string | undefined {
  if (!src) return src;
  if (!src.startsWith("/api/")) return src;
  return appendTokenToUrl(src);
}

// Folders -------------------------------------------------------

export type Folder = {
  id: string;
  name: string;
  tags: string[];
  parent_id?: string | null;
  storage_path?: string | null;
};

/** A collection of assets from any folder. Read-only here: creation is Mf-1sfc. */
export type Project = {
  id: string;
  name: string;
  description: string | null;
  creator: string | null;
  source_url: string | null;
  licence: string | null;
  licence_url: string | null;
  origin: string;
  cover_asset_id: string | null;
  cover_thumb_url: string | null;
  asset_count: number;
  /** Free-form per-project metadata as returned by the API (untrusted). */
  metadata_json: Record<string, unknown>;
  /** Sum of the member assets' sizes in bytes. */
  total_size: number;
  created_at: string;
  updated_at: string;
};

/** Partial project edit; an explicit `null` clears a nullable field. */
export type ProjectPatch = {
  name?: string;
  description?: string | null;
  cover_asset_id?: string | null;
  creator?: string | null;
  source_url?: string | null;
  licence?: string | null;
  licence_url?: string | null;
};

/**
 * New-project payload for `createProject`. The server's `ProjectIn` is
 * `extra="forbid"`, so only these fields may be sent; `origin` defaults to
 * "own" server-side.
 */
export type ProjectCreate = {
  name: string;
  description?: string | null;
  cover_asset_id?: string | null;
  creator?: string | null;
  source_url?: string | null;
  licence?: string | null;
  licence_url?: string | null;
  origin?: "own" | "imported";
};

export type ProjectMembersResult = {
  added: string[];
  skipped: string[];
  failed: BatchFailure[];
};

export type ProjectRemovalResult = {
  removed: string[];
  skipped: string[];
  failed: BatchFailure[];
};

export async function listProjects(): Promise<Project[]> {
  const res = await fetch(`${apiBase()}/projects`, { headers: authHeaders() });
  assertOk(res, "Failed to list projects");
  return res.json();
}

/** Creates a project. The route answers 201, which `res.ok` already covers. */
export async function createProject(payload: ProjectCreate): Promise<Project> {
  const res = await fetch(`${apiBase()}/projects`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Project creation failed"));
  }
  return res.json();
}

export async function listProjectAssets(params: {
  projectId: string;
  q?: string;
  tags?: string[];
  limit?: number;
  offset?: number;
}): Promise<ListAssetsResult> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.tags && params.tags.length) qs.set("tags", params.tags.join(","));
  if (typeof params.limit === "number") qs.set("limit", String(params.limit));
  if (typeof params.offset === "number") qs.set("offset", String(params.offset));
  const res = await fetch(
    `${apiBase()}/project/${encodeURIComponent(params.projectId)}/assets?${qs.toString()}`,
    { headers: authHeaders() },
  );
  assertOk(res, "Failed to list project assets");
  const items = await res.json();
  const hasMore = (res.headers.get("X-Has-More") || "").toLowerCase() === "true";
  const nextOffsetRaw = res.headers.get("X-Next-Offset");
  const nextOffset = nextOffsetRaw ? Number(nextOffsetRaw) : undefined;
  return { items, hasMore, nextOffset };
}

export async function updateProject(id: string, patch: ProjectPatch): Promise<Project> {
  const res = await fetch(`${apiBase()}/project/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(patch),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Project update failed"));
  }
  return res.json();
}

export async function deleteProject(id: string): Promise<void> {
  const res = await fetch(`${apiBase()}/project/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  assertOk(res, "Delete project failed");
}

/** Adds assets to a project; per-asset results are reported, not thrown. */
export async function addProjectAssets(
  projectId: string,
  assetIds: string[],
): Promise<ProjectMembersResult> {
  const res = await fetch(`${apiBase()}/project/${encodeURIComponent(projectId)}/assets`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ asset_ids: assetIds }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Adding assets to the project failed"));
  }
  return res.json();
}

/**
 * Removes assets from a project. This DELETE deliberately carries a JSON body,
 * so it has to be sent explicitly (the assets themselves are never deleted).
 */
export async function removeProjectAssets(
  projectId: string,
  assetIds: string[],
): Promise<ProjectRemovalResult> {
  const res = await fetch(`${apiBase()}/project/${encodeURIComponent(projectId)}/assets`, {
    method: "DELETE",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ asset_ids: assetIds }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Removing assets from the project failed"));
  }
  return res.json();
}

export type FolderDeletePreview = {
  folders: number;
  assets: number;
  files: number;
  bytes: number;
  in_trash: boolean;
};

export type FolderDeleteResult = {
  ok: boolean;
  // null when the folder had no directory on disk (a scan-created row)
  trash_path: string | null;
  folders: number;
  assets: number;
  bytes: number;
};

export type TrashEntry = {
  path: string;
  name: string;
  size: number;
  mtime: string;
};

export type TrashList = {
  entries: TrashEntry[];
  total_size: number;
};

export type TrashPurgeResult = {
  purged: number;
  bytes: number;
  failed: string[];
};

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

export async function deleteFolder(id: string, confirmName: string): Promise<FolderDeleteResult> {
  const qs = new URLSearchParams({ confirm_name: confirmName });
  const res = await fetch(`${apiBase()}/folder/${id}?${qs.toString()}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    // Surface the server's 400 (mismatched confirm_name) / 409 detail in the dialog.
    throw new Error(await readErrorMessage(res, "Delete folder failed"));
  }
  return res.json();
}

export async function getFolderDeletePreview(id: string): Promise<FolderDeletePreview> {
  const res = await fetch(`${apiBase()}/folder/${id}/delete-preview`, { headers: authHeaders() });
  assertOk(res, "Failed to load delete preview");
  return res.json();
}

export async function getTrash(): Promise<TrashList> {
  const res = await fetch(`${apiBase()}/trash`, { headers: authHeaders() });
  assertOk(res, "Failed to load trash");
  return res.json();
}

export async function purgeTrash(olderThanDays?: number): Promise<TrashPurgeResult> {
  const qs = new URLSearchParams();
  if (typeof olderThanDays === "number") qs.set("older_than_days", String(olderThanDays));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const res = await fetch(`${apiBase()}/trash/purge${suffix}`, {
    method: "POST",
    headers: authHeaders(),
  });
  assertOk(res, "Failed to empty trash");
  return res.json();
}

export async function downloadZip(opts: {
  asset_ids?: string[];
  tag?: string;
  folder_id?: string;
  project_id?: string;
  filename?: string;
}) {
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

/**
 * Fetches a single asset's bytes (401 becomes `UnauthorizedError`); pair it with
 * `saveResponseToDisk` from `./download` to write the file.
 */
export async function downloadAsset(asset: Asset): Promise<Response> {
  const res = await fetch(fileUrl(asset.url));
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error("Download failed");
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

export type AuthTokens = {
  token: string;
  expires_in: number;
  refresh_token?: string;
  token_type?: string;
};

export async function login(username: string, password: string): Promise<AuthTokens> {
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

export async function refreshToken(refresh: string): Promise<AuthTokens> {
  const res = await fetch(`${apiBase()}/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  assertOk(res, "Token refresh failed");
  return res.json();
}

/** Best-effort server-side revocation; the caller clears local storage either way. */
export async function logout(refresh: string): Promise<void> {
  try {
    await fetch(`${apiBase()}/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
  } catch {
    // offline or already signed out: nothing left to revoke
  }
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

export type AuditEvent = {
  id: string;
  created_at: string;
  actor: string;
  actor_user_id: string | null;
  actor_role: string;
  actor_kind: string;
  action: string;
  target: string;
  detail: Record<string, unknown> | null;
  request_id: string;
  method: string;
  path: string;
};

export type AuditQuery = {
  actor?: string;
  action?: string;
  target?: string;
  /** ISO-8601; a bare `YYYY-MM-DD` is widened to the whole day server-side. */
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
};

export type AuditPage = {
  events: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
};

/** Admin-only: the API answers 403 for everyone else (see `assertOk`). */
export async function listAuditEvents(params: AuditQuery = {}): Promise<AuditPage> {
  const qs = new URLSearchParams();
  if (params.actor) qs.set("actor", params.actor);
  if (params.action) qs.set("action", params.action);
  if (params.target) qs.set("target", params.target);
  if (params.since) qs.set("since", params.since);
  if (params.until) qs.set("until", params.until);
  if (typeof params.limit === "number") qs.set("limit", String(params.limit));
  if (typeof params.offset === "number") qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const res = await fetch(`${apiBase()}/audit${suffix}`, { headers: authHeaders() });
  assertOk(res, "Failed to load the audit log");
  return res.json();
}
