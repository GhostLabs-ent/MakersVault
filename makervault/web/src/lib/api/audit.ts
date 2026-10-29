// Audit-log queries.

import { authHeaders } from "../auth";
import { apiBase } from "./baseUrl";
import { assertOk } from "./http";

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
