// Folders; the tree itself is assembled client-side.

import { authHeaders } from "../auth";
import type { SnapshotNotice } from "./assets";
import { apiBase } from "./baseUrl";
import { UnauthorizedError, assertOk, readErrorMessage } from "./http";

// Folders -------------------------------------------------------

export type Folder = {
  id: string;
  name: string;
  tags: string[];
  parent_id?: string | null;
  storage_path?: string | null;
};

export type FolderDeletePreview = {
  folders: number;
  assets: number;
  files: number;
  bytes: number;
  in_trash: boolean;
  snapshot?: SnapshotNotice | null;
};

export type FolderDeleteResult = {
  ok: boolean;
  // null when the folder had no directory on disk (a scan-created row)
  trash_path: string | null;
  folders: number;
  assets: number;
  bytes: number;
  snapshot?: SnapshotNotice | null;
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
