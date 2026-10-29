// Shared HTTP plumbing: the status checks (`assertOk`, `readErrorMessage`) and
// `UnauthorizedError`, the one definition of that class in the client.

import { apiBase } from "./baseUrl";

export class UnauthorizedError extends Error {
  constructor(message = "Unauthorized") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

/** The exact 403 message `assertOk` throws, so callers can match it once. */
export const FORBIDDEN_MESSAGE = "Your role does not allow this action.";

export function assertOk(res: Response, message: string) {
  if (res.status === 401) {
    throw new UnauthorizedError();
  }
  if (res.status === 403) {
    throw new Error(FORBIDDEN_MESSAGE);
  }
  if (!res.ok) {
    throw new Error(message);
  }
}

/** Parses an error body: JSON `detail` wins, otherwise the raw text (nginx HTML). */
export function errorMessageFromBody(body: string, fallback: string): string {
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

export async function readErrorMessage(res: Response, fallback: string) {
  try {
    return errorMessageFromBody(await res.text(), fallback);
  } catch {
    return fallback;
  }
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
