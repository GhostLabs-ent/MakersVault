// Deleted-asset trash: listing and purge.

import { authHeaders } from "../auth";
import { apiBase } from "./baseUrl";
import { primeListGrants } from "./grantPriming";
import { assertOk } from "./http";

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

export async function getTrash(): Promise<TrashList> {
  const res = await fetch(`${apiBase()}/trash`, { headers: authHeaders() });
  assertOk(res, "Failed to load trash");
  const trash = await res.json();
  await primeListGrants(trash?.entries);
  return trash;
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
