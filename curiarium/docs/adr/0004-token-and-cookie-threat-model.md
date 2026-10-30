# ADR 0004: Bearer tokens in file URLs and proxied import cookies

**Status:** Superseded by [ADR 0005](0005-file-grant-urls.md).

**Accepted:** 2026-10-29

Superseded for the file-URL half only: decision 1's `?token=` file-URL interim
risk acceptance and decision 2's signed-grant migration target are implemented
by ADR 0005 and ticket `M3-7bb7`. Decision 3 (the import-cookie threat model,
MV-SEC-017) and the `localStorage` risk acceptance for MV-SEC-008 still stand,
and the record below is what was decided on 2026-10-29.

**Path note (2026-10-30):** The file paths quoted in this record are accurate as
written on 2026-10-29 and are left unchanged; two of them have since moved.
Batch 15 landed that same evening, after this ADR was accepted: `Mf-h8kp`
(`fcbe4e0`, 2026-10-29) split `web/src/lib/api.ts` into
`curiarium/web/src/lib/api/`, and `Mf-avo9` (`29330d6`, 2026-10-29) split
`api/schemas.py` into `curiarium/api/schemas/`. The import-cookie citation
`api/schemas.py:21-22` now lives at
`curiarium/api/schemas/imports.py:30-31` (`makerworld_cookie`,
`thingiverse_cookie` on `ImportRequest`), re-exported through the
`curiarium/api/schemas/__init__.py` barrel. The client citations
`web/src/lib/api.ts:876-880` (`fileUrl`), `:886-888` (`assetFilePreviewUrl`) and
`:901-904` (`stableFileUrl`) now live in
`curiarium/web/src/lib/api/mediaUrls.ts` at `:15`, `:27` and `:42`, behind the
`curiarium/web/src/lib/api/index.ts` barrel. The remaining citation,
`:918-922` (`renderFileUrl`), was *not* moved by the split: `ae076cf`
(`Mf-dhtm`, 2026-10-28) added it and `d7f72bd` (`M3-7bb7`, 2026-10-29) removed it
with the rest of the `?token=` file-URL machinery, before the split ran, so that
citation has no live counterpart — `web/src/lib/fileUrl.test.ts:182-183` pins
its absence from the `api` barrel. That same commit retired `appendTokenToUrl`,
the other client citation at `web/src/lib/auth.ts:96-107`, pinned by
`web/src/lib/fileGrants.test.ts:261-263`; the file itself still exists, without
that helper.

## Context

v5.1 has two credential flows that carry secrets outside an `Authorization`
header, and neither has ever been written down as a threat model. The first is
the file URL: the web client appends the caller's access JWT as a `?token=`
query parameter because `<img>`, `<iframe>`, `<a download>` and the
`curiarium-slicer://` OS protocol handoff cannot attach headers. The token
therefore travels wherever a URL travels — access logs, browser history,
copied links, screenshots and `Referer` headers. The second is the import
cookie: MakerWorld and Thingiverse gate anonymous downloads behind a session
cookie that the user pastes into the web client, and the API replays that
cookie on the user's behalf, which puts a third-party account credential into
the application's stored state.

The Gate 0 security revalidation already records both surfaces as MV-SEC-007,
MV-SEC-008 and MV-SEC-009, but "confirmed" is not a decision. This ADR records
what v5.1 accepts, what it does not, and which ticket closes the gap.

Verified facts at the time of this decision:

- `?token=` is accepted in exactly one place, `api/auth.py:180-187`:
  `token_param: Optional[str] = Query(default=None, alias="token")`, with the
  `Authorization` header winning when both are present. The alias is `token`
  only, never `access_token`. Because `api/permissions.py:104-110` routes every
  protected route through `require_auth`, every endpoint except the four
  PUBLIC ones (`/health`, `/login`, `/refresh`, `/logout`;
  `api/permissions.py:126-129`) accepts the query parameter.
- Client sites that put the session token in a URL: `web/src/lib/auth.ts:96-107`
  (`appendTokenToUrl`), `web/src/lib/api.ts:876-880` (`fileUrl`), `:886-888`
  (`assetFilePreviewUrl`), `:918-922` (`renderFileUrl`).
  `web/src/lib/api.ts:901-904` (`stableFileUrl`) is the token-less
  counterpart. The custom-protocol handoffs
  `web/src/ui/asset-grid/useAssetActions.ts:200-206,210-218` and
  `web/src/ui/ProjectLanding.tsx:311-315` pass a token-bearing `fileUrl` through
  `window.location.href` into `curiarium-slicer://open?url=...`.
- The access token lives in `localStorage` under `curiarium_auth_token`, the
  refresh token under `curiarium_auth_refresh_token`
  (`web/src/lib/auth.ts:1-3,10-17`). There is no httpOnly cookie, no `SameSite`
  and no CSRF machinery anywhere in application source.
- Access tokens last 15 minutes (`AUTH_ACCESS_TOKEN_TTL`, default `900`,
  `api/auth.py:25`) and refresh tokens 30 days (`AUTH_REFRESH_TTL_SECONDS`,
  `api/auth.py:26`); `AUTH_TOKEN_TTL` (`api/auth.py:24`) is a deprecated,
  ignored name. Refresh is single-use and rotation-backed by a server-side
  revocation store (`api/sessions.py:118-145` `rotate()`, `:148-154`
  `revoke()`), and an access token is only accepted while its `sid` maps to a
  live `UserSession` row (`api/auth.py:196-203`).
- Application code adds no URL sink to any log: `api/main.py:123-131` registers
  only CORS and a request-id middleware, there is no access logger and no
  redaction helper in `curiarium/api`, and the audit table stores
  `request.url.path` only, never the query (`api/audit.py:126-131`). The bridge
  redacts: `slicer-bridge/cmd/slicer-bridge/main.go:424-435` (`redactURL`
  rewrites `token=REDACTED`), used on the open path (`main.go:129`) and in
  download errors (`slicer-bridge/cmd/slicer-bridge/safe_download.go:174,280-286`),
  pinned by `main_test.go:24-28`.
- The log surface is nonetheless open: `web/nginx.conf` declares no
  `access_log` or `log_format` at all, so Nginx inherits its compiled default
  `combined`, whose format includes `"$request"` — the full request line,
  `?token=` included. `api/Dockerfile:31` runs plain `uvicorn main:app` with no
  `--no-access-log`, so uvicorn's default access log records the request line
  too.
- Import cookies: session-scoped in `sessionStorage` under
  `curiarium_session_cookies` by default (`web/src/lib/settings.ts:153-175`),
  copied into the persisted `curiarium_settings` blob only when
  `imports.rememberCookies` is true (`settings.ts:111,367-381`); they reach the
  API as JSON body fields, never a header (`api/schemas.py:21-22`); the API
  proxies them only to a closed host registry
  (`api/import_policy.py:45-48,86-95`, with `makerworld.com` plus subdomains and
  the exact `thingiverse.com`/`www.thingiverse.com` set in
  `api/import_resolvers.py:457-464,655-657`), through a single entry point
  (`api/import_service.py:63-82` `import_request_headers`), re-derived per hop
  (`:98,153-160`), and stripped on cross-origin redirect
  (`api/safe_http.py:45,160-161`). They are never persisted server-side and
  never logged, pinned by `api/tests/test_import_policy.py:230-248` and `:251`.
- `curiarium/docs/security/GATE_0_REVALIDATION.md` records MV-SEC-007 and
  MV-SEC-008 as `CONFIRMED`, but has no row at all for the import cookies, and
  the cookie machinery post-dates that review (Mf-vesa, landed `baf2b78`). This
  ADR adds MV-SEC-017 for them.
- `curiarium/docs/ARCHITECTURE_RUNBOOK.md` truth-ledger row T-007 already
  records the intended consequence, "Replace broad reusable bearer URLs with
  narrow, short-lived grants", and the ADR queue item 4 is "File-scoped
  browser-to-bridge handoff grants".

## Decision

1. **Risk-accept for the v5.1 line, with named compensating controls — interim,
   not end state.** `?token=` remains the file-URL credential and the primary
   access JWT remains in `localStorage` for v5.1, because `<img>`, `<iframe>`,
   `<a download>` and the `curiarium-slicer://` OS protocol handoff cannot
   attach an `Authorization` header, and the MV-SEC-007/008 preferred
   remediation (an HttpOnly session cookie) cannot authorize the bridge handoff
   and would add CSRF machinery to a bearer-style API. The exposure is bounded
   today by: 15-minute access tokens (`AUTH_ACCESS_TOKEN_TTL`, default 900),
   single-use rotating refresh tokens backed by a server-side revocation store
   (`api/sessions.py`), render-time token injection that keeps tokens out of
   persisted project markdown (`stableFileUrl` vs `fileUrl`), bridge log
   redaction (`redactURL`, test-pinned), no URL logging in API code, and an
   audit trail that stores request paths only.

   The residual exposure this ADR accepts, stated plainly: Nginx's
   compiled-default `combined` access log and uvicorn's default access log both
   record the full request line including `?token=`; browser history, copied
   URLs, screenshots and `Referer` are unmitigated; a leaked access token is
   replayable for up to 15 minutes and rotation does nothing for a leak inside
   that window; refresh-token replay is not yet treated as theft (Mf-7op4); and
   no CSP baseline exists (MV-SEC-015), which compounds the `localStorage` XSS
   exposure rather than mitigating it. Declining the HttpOnly-cookie remediation
   for MV-SEC-008 is therefore an explicit v5.1 risk decision under the
   single-admin model, not an oversight.

2. **Adopt short-lived, file-scoped signed grants as the migration target.**
   Ticket-minted URLs — file scope, read-only scope, short expiry, signing
   independent of the session token — replace the session JWT in file URLs and
   browser-to-bridge handoffs. This is the MV-SEC-007 signed-URL remediation, it
   is runbook queue item 4, and it formalises truth-ledger T-007.
   Implementation, including the Nginx `access_log`/`log_format` and uvicorn
   access-log changes that take `?token=` out of server logs, is deferred to
   ticket `M3-7bb7` and is explicitly out of scope here.

3. **Keep the import-cookie design and record its threat model.** MakerWorld and
   Thingiverse session cookies stay session-scoped (`sessionStorage`) by
   default, move into the persisted settings blob only on the explicit
   "remember cookies" opt-in, travel as JSON body fields, and are proxied only
   to the closed host registry above with per-hop re-derivation and cross-origin
   redirect stripping. They are never logged and never persisted server-side,
   and paid or gated content is refused before any request is built. The
   residual exposure this ADR accepts: a remembered cookie is readable by any
   JavaScript on the application origin, and it is a live third-party account
   credential — a bigger prize than the application's own JWT — while HttpOnly
   isolation is unavailable for a cookie the browser must hand to a proxy. The
   "remember" toggle is the explicit risk decision; the default keeps the value
   tab-scoped. Because the v5.1 security analysis predates this machinery, the
   finding is recorded as MV-SEC-017 in the Gate 0 revalidation.

## Consequences

v5.1 ships with a documented, tested and time-bounded exposure rather than an
unowned one: the compensating controls in the decision are each pinned by a
test, so a silent removal fails the suite instead of quietly widening the
surface.

The log-leak fix and the signed-grant migration are one owned ticket, `M3-7bb7`,
rather than a wish attached to an old review. Until it lands, the ADR itself is
the record that the access logs still carry `?token=`, so nobody can claim the
surface is closed by reading a document that does not mention it.

Treating the import cookie as a documented credential changes how it is
reviewed: the session-scoped default and the closed host registry are now
invariants to preserve, and the "remember cookies" toggle is the one place a
user accepts the residual risk.

Truth-ledger row T-007 stops being a promise nothing tracks. It points at this
ADR and at the implementation ticket, and the Gate 0 table gains MV-SEC-017 so
the cookie machinery is no longer outside the review that covers the rest of
the auth surface.

## Alternatives considered

- An HttpOnly `SameSite=Strict` session cookie for authentication. Rejected: it
  cannot authorize the `curiarium-slicer://` handoff, which is an OS protocol
  navigation that carries no cookie jar contract, it needs CSRF tokens on an API
  that currently speaks bearer tokens, and it changes the auth model the whole
  API and the bridge already implement.
- `Authorization` header only, with no query parameter. Rejected: `<img>`,
  `<iframe>` and `<a download>` cannot attach headers, so the file surface would
  stop working for authenticated installs.
  `api/tests/test_auth_users.py:423-428` pins the query parameter as deliberate.
- Leave token-in-URL unchanged with no written decision. Rejected: it leaves a
  confirmed P0/P1 finding unowned, contradicts runbook T-007, and makes the
  access-log leak invisible to anyone reading the docs.
- Implement the signed grants inside this ticket. Rejected: it touches the API,
  the web client, the bridge, `web/nginx.conf` and `api/Dockerfile`. That is a
  feature with its own verification story, not a documentation decision, and
  bundling it here would ship the larger change with the smaller review.
- Drop the import-cookie feature. Rejected: it reverses the Mf-vesa decision
  that the machinery may stay for anonymous download limits, and it removes a
  working capability instead of defining it.

## Rollback

This ADR changes no behaviour, so rollback is reverting the documentation
commit: the ADR, the runbook annotations and the Gate 0 rows. The only
executable artefact is the drift test
(`api/tests/test_adr_threat_model.py`); deleting that test alongside the ADR
restores the previous state exactly.

Rolling back fixes nothing. Reverting the ADR re-opens the finding it closes and
returns MV-SEC-007, MV-SEC-008 and the import cookies to an unowned state, so a
rollback must re-open the finding and assign a new owner rather than assume the
exposure went away.

## Verification

- `api/tests/test_adr_threat_model.py` is this ADR's drift guard: it binds the
  three documents together, pins the decision's migration target, and fails if
  any one of them drops the follow-up ticket reference.
- `api/tests/test_auth_users.py:423-428` (`test_query_token_still_authorizes`)
  pins the interim state as deliberate, so a silent removal of `?token=` is
  caught as a behaviour change rather than misread as progress.
- `api/tests/test_import_policy.py:230-248` pins that the import cookie never
  reaches a log line, and `:251` pins the refusal path.
- `slicer-bridge/cmd/slicer-bridge/main_test.go:24-28` pins bridge log
  redaction of `token=`.
- `web/src/lib/auth.test.ts:76-96` pins the `localStorage` token model itself:
  the refresh token round-trips and sign-out clears both tokens and the cached
  role.
- `web/src/lib/fileUrl.test.ts:53-63,105-111` pin render-time token injection,
  including that a viewer's token overwrites an author-injected one rather than
  trusting it.

## Superseding conditions

This ADR is superseded when `M3-7bb7` lands the short-lived file-scoped signed
grants; write the replacement grant ADR at that point and record how the access
logs, the browser history and the bridge handoff are covered. It is also
superseded if v5.1 ships a CSP baseline, so the `localStorage` exposure is
bounded by policy rather than accepted outright, if the application moves to a
cookie-based session, or if MakerWorld and Thingiverse introduce per-request
credentials that make the stored session cookie unnecessary.
