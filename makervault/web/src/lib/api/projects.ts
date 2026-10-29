// Projects and their asset membership.

import { authHeaders } from "../auth";
import type { BatchFailure, ListAssetsResult } from "./assets";
import { apiBase } from "./baseUrl";
import { primeListGrants } from "./grantPriming";
import { UnauthorizedError, assertOk, readErrorMessage } from "./http";

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
  const projects = await res.json();
  await primeListGrants(projects);
  return projects;
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
  /** Exact creator, case-insensitive; blank is ignored by the server. */
  creator?: string;
  sort?: "name" | "size" | "creator";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}): Promise<ListAssetsResult> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.tags && params.tags.length) qs.set("tags", params.tags.join(","));
  if (params.creator) qs.set("creator", params.creator);
  if (params.sort) qs.set("sort", params.sort);
  if (params.order) qs.set("order", params.order);
  if (typeof params.limit === "number") qs.set("limit", String(params.limit));
  if (typeof params.offset === "number") qs.set("offset", String(params.offset));
  const res = await fetch(
    `${apiBase()}/project/${encodeURIComponent(params.projectId)}/assets?${qs.toString()}`,
    { headers: authHeaders() },
  );
  assertOk(res, "Failed to list project assets");
  const items = await res.json();
  await primeListGrants(items);
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
