// Zip and asset downloads; these hand the caller a `Response` to save or stream.

import { authHeaders } from "../auth";
import type { Asset } from "./assets";
import { apiBase } from "./baseUrl";
import { UnauthorizedError, assertOk } from "./http";
import { fileUrl } from "./mediaUrls";

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
  // The bearer header wins over any cached grant: this is a real fetch, not an
  // `<img>`, so it need not spend a URL credential at all.
  const res = await fetch(fileUrl(asset.url), { headers: authHeaders() });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error("Download failed");
  return res;
}
