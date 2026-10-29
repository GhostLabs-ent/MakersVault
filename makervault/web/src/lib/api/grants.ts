// The grant transport itself (`mintFileGrants`) plus its injection into
// `../fileGrants` via `configureGrantMinter`. The injection stays a top-level
// side effect of importing this module, exactly as it was in the old `api.ts`.

import { authHeaders } from "../auth";
import { configureGrantMinter, rememberGrants } from "../fileGrants";
import type { Grant } from "../fileGrants";
import { apiBase } from "./baseUrl";
import { UnauthorizedError, readErrorMessage } from "./http";

/**
 * Mints short-lived, file-scoped, read-only grants for `paths` through
 * `POST /file-grants` and stores them in `./fileGrants`.
 *
 * Injected rather than imported there (`configureGrantMinter`, below): that
 * module cannot import this one without a cycle, and a test that mocks this
 * module wholesale must leave minting disabled.
 */
export async function mintFileGrants(paths: string[]): Promise<void> {
  const res = await fetch(`${apiBase()}/file-grants`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ paths }),
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) throw new Error(await readErrorMessage(res, "File grant request failed"));
  const data = (await res.json()) as { grants?: Grant[] } | null;
  rememberGrants(Array.isArray(data?.grants) ? data.grants : []);
}

configureGrantMinter(mintFileGrants);
