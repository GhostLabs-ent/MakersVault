# ADR 0005: Short-lived, file-scoped signed grants for URL credentials

**Status:** Accepted

**Accepted:** 2026-10-29

**Supersedes:** [ADR 0004](0004-token-and-cookie-threat-model.md) for the
MV-SEC-007 file-URL design and its interim risk acceptance. ADR 0004's
import-cookie decision (MV-SEC-017) and its `localStorage` risk acceptance
(MV-SEC-008) still stand.

**Implementation:** ticket `M3-7bb7`; error-log closure in `Mf-c80i`;
deferred-interaction re-mint in `Mf-1vxh`.

**Path note (2026-10-30):** The paths quoted below are accurate as written on
2026-10-29 and are left unchanged; one of them has since moved. Batch 15 landed
that evening, after this ADR was accepted: `Mf-h8kp` (`fcbe4e0`, 2026-10-29)
split `web/src/lib/api.ts` into `makervault/web/src/lib/api/`. Every reference to
that file in this record therefore now resolves against the package: the
transport injection `configureGrantMinter(mintFileGrants)` is at
`makervault/web/src/lib/api/grants.ts:31`, `fileUrl` and `assetFilePreviewUrl`
are at `makervault/web/src/lib/api/mediaUrls.ts:15` and `:27`, and
`downloadAsset` is at `makervault/web/src/lib/api/downloads.ts:35`;
`fileUrl`, `assetFilePreviewUrl`, `downloadAsset` and `mintFileGrants` are
re-exported from the `makervault/web/src/lib/api/index.ts` barrel
(`configureGrantMinter` itself stays in `web/src/lib/fileGrants.ts`, from where
`grants.ts` imports it), which is also what the later `web/src/lib/api`
reference in the deferred-interaction material names — that one is the package
path, not the deleted file, so it still resolves as written.

## Context

Some file loads are navigations, not fetches. An `<img>` thumbnail, an
`<a download>`, an `<iframe>` preview of a supporting file and the
`makersvault-slicer://open?url=...` OS handoff all reach the API without
control over headers, so a credential for them can only travel in the URL. ADR
0004 accepted spending the caller's access JWT there as an interim v5.1
decision and named the fix: short-lived, file-scoped signed grants.

The cost of the interim state was concrete. A `?token=` URL carried a
15-minute, all-routes session credential into everything a URL reaches: browser
history, copied links, screenshots, `Referer` headers, and the container logs.
The logs were the worst of it. `web/nginx.conf` declared no `access_log` and no
`log_format`, so Nginx inherited its compiled-in `combined` format, which logs
`"$request"` — the whole request line, query string included — and
`api/Dockerfile` ran plain `uvicorn main:app` with its default access log on.
Anyone who could read `docker compose logs` could lift a working token out of a
thumbnail request.

Verified facts at the time of this decision:

- `auth.require_auth` in `api/auth.py` accepted `token_param` in the query as
  well as the `Authorization` header, and every guarded route went through it,
  so the query credential worked against every route except the four `PUBLIC`
  ones.
- The web client minted those URLs at render time: `appendTokenToUrl` in
  `web/src/lib/auth.ts`, `fileUrl`/`assetFilePreviewUrl`/`renderFileUrl` in
  `web/src/lib/api.ts`. `web/src/ui/asset-grid/useAssetActions.ts` and
  `web/src/ui/ProjectLanding.tsx` passed a token-bearing `fileUrl` into
  `window.location.href`, so the same credential reached an OS protocol handler.
- The bridge already redacted on the way back out
  (`slicer-bridge/cmd/slicer-bridge/main.go` `redactURL`), but only `token=`;
  a replacement credential in `sig=` would have been logged in the clear.
- Four file routes serve the bytes: `GET /file/{asset_id}/{name}`,
  `GET /asset/{asset_id}/files/{file_id}` (with an `?inline=1` preview
  disposition), `GET /thumb/{asset_id}.jpg` and
  `GET /asset/{asset_id}/prepared-print`, all in
  `api/routers/asset_files.py`. No other route serves user file bytes.

## Decision

1. **A URL credential stays, but it is a grant, not a session token.**
   `POST /file-grants` (in `api/routers/asset_files.py`, deliberately not a new
   router so `main.py` gains no include) takes `{"paths": [...]}` — 1 to 50
   API-relative paths — and answers `{"grants": [{"path", "url",
   "expires_at"}]}`. `path` echoes the request string verbatim, query included,
   so the client can key its cache by the exact relative URL it holds; `url` is
   that path plus `?sig=`/`&sig=`. The mint requires ordinary READ
   (`require_read`), so a viewer may mint; a grant confers nothing a viewer did
   not already have.

2. **Grants are cryptographically separated from session tokens and read-only
   by construction.** `auth.file_grant_key()` derives the signing key as
   `HMAC-SHA256(AUTH_SECRET, b"makervault/file-grant/v1")`, so a grant never
   verifies as an access token and an access token never verifies as a grant —
   isolation by key, not by a claim a caller could omit. Claims: `aud =
   "makervault:file-grant"`, `typ = "file-grant"`, `scope = "file:read"`, `p`
   (the bound path), `sid`, `sub`, `iat`, `exp`, plus `inline` only when minted
   for the inline preview. `FILE_GRANT_TTL_SECONDS = 60`, and the verifier
   independently rejects any grant whose `exp - iat` exceeds
   `FILE_GRANT_MAX_TTL_SECONDS = 300`, so a future mint cannot hand out a
   long-lived grant without failing the verifier.

3. **A grant names exactly one path and only works there.**
   `auth.require_auth_or_file_grant` verifies the signature and the fixed claims,
   requires `request.url.path == p`, allows only `sig`, `v` and `inline` as
   additional query keys, requires the request's `inline` to equal the claim, and
   requires the `sid` claim to still map to a live `UserSession` — so signing out
   invalidates outstanding grants, and a disabled account stops working
   immediately. It returns `AuthContext(role="viewer", kind="file_grant")`, and
   the existing rank ladder keeps that read-only even if it ever reached a
   dependency it was not meant for. When both an `Authorization` header and a
   `sig` are present the header wins; a malformed header is a 401 and never a
   silent fallback to the grant.

4. **`require_file_read` is the only route-level exception.**
   `permissions.require_permission(level, authenticate=require_auth)` is now
   parametrised, and `require_file_read =
   require_permission(READ, require_auth_or_file_grant)` is attached to the four
   file routes and to nothing else. It still declares exactly one level, so
   `assert_routes_classified()` and the permission sweeps read it as READ. Every
   other route keeps plain `require_read`/`require_write`/`require_admin` and
   therefore never consults `?sig=`, which is what stops a grant from being used
   against a list, write or admin route.

5. **`?token=` is retired outright.** `auth.require_auth` no longer takes a
   `token_param`; it is header-only, so a session token in a query string is a
   401 on every route, the four file routes included. This is a single release
   with no compatibility window, which is stated as a residual risk below.

6. **The mint is an allow-list, not a signing oracle.** Exactly four templates
   are grantable (`_FILE_GRANT_TEMPLATES` in `api/routers/asset_files.py`), and
   each is existence-checked against the database before it is signed: `GET
   /file/{asset_id}/{name}`, `GET /asset/{asset_id}/files/{file_id}`
   (optionally `?inline=1`, which must be exactly `1` and only on this route),
   `GET /thumb/{asset_id}.jpg` and `GET /asset/{asset_id}/prepared-print`. A
   non-grantable path, an empty or oversized batch, an unknown query key, or
   `inline` on a route that does not take it is a 400; an unknown asset or file
   is a 404. The mint also answers 200 when `AUTH_ENABLED` is false, signing
   with `sid = None`, unlike the token endpoints, which 503 — an
   auth-disabled deployment has no session to bind and no credential to
   protect.

7. **The client caches, batches and primes grants.**
   `web/src/lib/fileGrants.ts` holds a per-path cache (`Map<rel,
   {url, exp}>`) and a queue flushed in one microtask, at most 50 paths per
   request. `isGrantable` mirrors the server's four templates and the `v`/
   `inline` key set: the client filters because the server 400s a whole batch
   for one bad path, so one odd field would otherwise cost every URL in a list
   its grant. The data fetchers (`listAssets`, `listAssetFiles`,
   `listProjectAssets`, `listProjects`, `getTrash`) `await primeGrants(...)`
   before returning, so grants exist before the first render; a markdown image
   stored as an `/api/...` path resolves per viewer through
   `useGrantedFileUrl`. `fileUrl` and `assetFilePreviewUrl` stay synchronous: a
   cache hit yields the signed URL and a miss yields the plain joined URL, which
   is why the surfaces that render one on a deferred interaction — the grid's
   cards, the two preview dialogs and the three download links — re-mint on
   interaction (item 10) instead of relying on the fetch-time prime alone. The
   transport is injected from `api.ts` (`configureGrantMinter(mintFileGrants)`)
   so the module has no import cycle, and with no minter — a test that mocks
   `api.ts` — everything degrades to a miss. `downloadAsset` keeps sending
   `authHeaders()`: a real fetch need not spend a URL credential. The two
   `window.location.href` OS handoffs
   (`web/src/ui/asset-grid/useAssetActions.ts`,
   `web/src/ui/ProjectLanding.tsx`) `await primeGrants([...])` before
   navigating, so `makersvault-slicer://open?url=...` carries a 60-second grant
   instead of a session JWT.

8. **Both nginx logs stop recording the query, and the smoke test proves it.**
   `web/nginx.conf` declares `log_format makervault` in `http` context and binds
   it with `access_log /var/log/nginx/access.log makervault;`. The format
   rebuilds the request line from `$request_method $uri $server_protocol` and
   never uses `$request`, `$request_uri`, `$args` or `$http_referer`; `$uri` is
   the normalised path with the query removed. It also carries the query-free
   `$upstream_addr` and `$upstream_status`, so an unreachable API is still
   visible after the error log is silenced. The access log alone was not
   enough: nginx has no error-log format directive, and its error log embeds the
   whole request line - and the `upstream:` URL - in every upstream failure and
   malformed request, at every level down to `emerg`. A static upstream does not
   avoid it, because a dead address fails in `connect()` and logs the same
   request line; it would also break the build-time `nginx -t`, where no `api`
   host exists. `web/nginx.conf` therefore sets `error_log /dev/null;` at `http`
   scope, so request-time errors are not written anywhere; the access log's
   status and upstream fields are the diagnostic record. `api/Dockerfile`'s
   runtime `CMD` gains `--no-access-log`, so uvicorn writes no request line
   either. `scripts/container-smoke.sh` first requests
   `/api/health?token=<canary>&sig=<canary>` against the live proxy, then stops
   the `api` service, sends a second canary through the same query shape, and
   fails the run if either canary, `?token=` or `?sig=` appears in any
   container's `compose logs`; it also requires the query-free
   `"GET /health HTTP/1.1" 5xx` access line that proves the error path ran. A
   future edit to the config or the script is caught by the gate rather than by
   a leak. (`Mf-c80i` closed the error-log half; `M3-7bb7` closed the access
   log.)

9. **The bridge redacts the new parameter too.**
   `slicer-bridge/cmd/slicer-bridge/main.go` `redactURL` rewrites `sig=` as well
   as `token=`, pinned by `main_test.go`. The old parameter stays in the
   redaction set because an old client, a saved link or an old log line may still
   contain one.

10. **The client re-mints on interaction and never extends a grant.**
    `FILE_GRANT_TTL_SECONDS` is unchanged at 60: the fix for `Mf-1vxh` is that
    the client stops relying on the fetch-time prime alone.
    `web/src/lib/useFileGrants.ts` primes what a mounted component needs,
    re-mints each grant five seconds before it expires (a re-mint buys its own
    60 seconds; the old grant is left to expire), then repaints only where it
    must. A re-mint that fails is retried every ten seconds rather than
    disarming the keeper, because an outage spanning an expiry would otherwise
    leave a mounted element stale until it is next remounted — the same broken
    link this decision removes. A mint that fails on the first attempt for these
    paths still leaves the plain URL, as it always has. Its two variants differ
    in exactly that: `useFileGrants` leaves the render alone unless a grant it
    was missing has arrived, because re-rendering an `<img src>` with a new
    `sig` re-downloads bytes the browser already holds and would make a mounted
    `ModelViewer` re-fetch and re-parse its model every minute;
    `useLiveFileGrants` re-renders on every scheduled re-mint (a failed one
    repaints the same href) and exists for markup that holds the URL string
    itself — `web/src/ui/FileDownloadLink.tsx`, the component all three
    `<a download>` surfaces now use (the preview dialog, the supporting-file
    dialog and the card's supporting-file row). The
    virtualized grid needed the mount prime because `AssetGridBody` keys rows by
    index: a row that scrolls out unmounts its cards and a row that scrolls back
    remounts them with a cold cache, and a card that merely re-renders after the
    minute (a selection toggle) would otherwise swap a working `src` for an
    unsigned one. The two preview dialogs additionally gate their body on the
    first mint (`Preparing preview...`), so an open after the window never fires
    an unsigned request at all. `useGrantedFileUrl` keeps its own timer for
    persisted markdown images. With no minter configured — a test that mocks
    `web/src/lib/api` wholesale — everything degrades to a no-op and nothing is
    scheduled.

## Consequences

The blast radius of a leaked file URL drops from "a 15-minute credential for
every route" to "read one file's bytes, once, within 60 seconds, while the
session that minted it is still live". The credential is visible in exactly the
places a URL is visible — history, copied links, screenshots, `Referer` — but
what it can do there is now bounded, and the server-side log no longer keeps a
copy at all.

The route matrix gains one key, `("POST", "/file-grants") = READ`, and the
matrix is now 64 routes: 4 public, 21 read, 30 write, 9 admin. It is exempt from
auditing with the reason "mints a short-lived read-only file grant; mutates
nothing", so the exempt set is 19 keys and the audited set stays 21.

Costs paid deliberately:

- **One extra round trip per fetch.** `primeGrants` mints before a list
  renders. It is one request per fetch (grants are cached per path and live 60
  s, so a refresh inside the minute re-mints nothing), and an empty or
  grant-less list costs no request at all.
- **Two credential formats to reason about.** The isolation is cryptographic,
  but a reader now has to know that `Authorization` beats `?sig=`, that
  `?sig=` works on four routes only, and that `?token=` works nowhere.
- **A second place a route's level could drift.** `require_file_read` is pinned
  by `ROUTE_PERMISSIONS` and the permission sweeps like every other dependency;
  the drift guard reports a mismatched level at boot.

Residual risks, stated plainly:

- **No compatibility window.** A tab loaded before the upgrade holds a rendered
  `?token=` URL and gets 401s on its images and downloads until it reloads; a
  bridge handoff already in flight fails the same way. That was accepted: the
  alternative is keeping a query-string session token alive to serve one stale
  tab.
- **nginx request-time error logs are off.** The error log has no format
  directive and embeds the request line with its query, so `error_log /dev/null;`
  is the only stock-nginx guarantee. The access log still records the method,
  path, status, duration and upstream address/status, but the error text (for
  example "connection refused" versus "timed out") is lost. That is the price of
  keeping the credential out of every log at every level.
- **A 60-second grant against a long-lived DOM.** The signed URL sits in the
  `src`, the `href` and the clipboard for as long as the element lives, so a
  screenshot or a copied link still carries a credential — just an expired one.
  Mitigations: the byte responses carry `Cache-Control` (`private,
  max-age=86400` on `/file/...`, `private, max-age=31536000, immutable` on
  `/thumb/...`), so a rendered image does not need to re-fetch; priming means
  the first paint already has a fresh grant; and every deferred interaction
  (a remounted grid row, a preview dialog opened late, a download link
  clicked minutes after the list fetch) re-mints on mount and again five
  seconds before each expiry (decision 10), so an element that is already
  on screen is no longer left holding an unsigned URL. The lifetime is not
  widened anywhere: an element that outlives its grant is refreshed, never
  extended. `evictGrant(rel)` stays the invalidation seam for a URL that
  expired before it could be refreshed; nothing calls it automatically
  outside `useGrantedFileUrl`'s own timer.
- **Surfaces the re-mint does not cover yet.** Decision 10 covers the asset
  grid, the two preview dialogs and the three download links — the deferred
  interactions `Mf-1vxh` names. A file URL rendered by `ProjectLanding`'s
  gallery and hero cover, `ProjectSidebar`, `ProjectView` or
  `ImagePickerDialog` still resolves through `fileUrl` at render with no
  refresh, so a page left idle for more than a minute can still show an
  unsigned thumbnail there and get a 401. The harm there is not only a blank
  image: `ProjectLanding` wraps each gallery thumbnail in a `target="_blank"`
  anchor to the full file, so clicking one of those stale links navigates to a
  URL that 401s. Each is a one-line adoption of `useFileGrants`; they are named
  here so the gap is tracked rather than rediscovered.
- **An async handoff.** Both OS handoffs now `await` a mint before navigating.
  A mint that fails (401, 400, offline) leaves the plain URL, exactly as a
  grant-less render would, and the OS handler sees a 401 rather than a token.
  `primeGrants` never rejects, so no render path can be broken by it.
- **The query allow-list must grow with the routes.** If one of the four
  grantable routes gains a parameter that changes what is served, the verifier's
  `FILE_GRANT_QUERY_KEYS` (and `isGrantable` in the client) must learn it, or
  every request that uses it becomes a 401. That is the intended direction —
  a new parameter is a new decision about what a grant covers.
- **No CSP baseline** (MV-SEC-015), so the `localStorage` session token is still
  exposed to origin JavaScript; that risk is MV-SEC-008 and stays accepted in
  ADR 0004. A grant does not compound it: a stolen grant is read-only, single
  path and short-lived, and an XSS that can read `localStorage` did not need the
  URL credential anyway.

Deliberately out of scope: no data migration and no schema change (grants are
minted, never stored), no Compose change, no CSP, and no change to the
`localStorage` token model. `MV-SEC-008` stays a `CONFIRMED` v5.1 acceptance,
and the import-cookie decision (MV-SEC-017) is untouched.

## Alternatives considered

- **Keep `?token=` with a shorter TTL.** Rejected: it leaves a credential that
  works on every route, and the log leak is a property of the parameter, not of
  the expiry.
- **`Authorization` header only, no URL credential.** Rejected: `<img>`,
  `<a download>` and the OS protocol handoff cannot attach headers, so
  authenticated file rendering would simply stop working.
- **An HttpOnly session cookie.** Rejected for the same reason ADR 0004 gives:
  it cannot authorize the `makersvault-slicer://` handoff, which is an OS
  protocol navigation with no cookie jar contract, and it needs CSRF machinery
  on an API that speaks bearer tokens.
- **Sign grants with `AUTH_SECRET` directly, distinguished by a `typ` claim.**
  Rejected: a claim is checked by the verifier that already trusts the issuer,
  so one forgotten check makes the formats interchangeable. Key separation
  makes the confusion impossible rather than unlikely.
- **A grant per route family rather than per path.** Rejected: "read the
  thumbnails" is a broader credential than any single render needs, and the
  path claim is what makes a leaked URL useless for the next file.
- **One long-lived grant per session, cached in `sessionStorage`.** Rejected:
  that is the `?token=` problem with extra steps, and it would put the injection
  point back on the render path.
- **Mint through a new router.** Rejected: `main.py` is a hotspot (runbook
  T-017), and the four grantable routes already live in
  `api/routers/asset_files.py`, so the allow-list and the routes it names sit in
  one file.
- **Leave the access log as ADR 0004 found it.** Rejected: it was the one
  mitigation that made the leak *invisible* rather than merely possible, and it
  is a two-file change with a smoke-test canary that keeps it fixed.

## Rollback

Revert the `M3-7bb7` commit. That restores `?token=` acceptance in
`auth.require_auth`, removes `POST /file-grants` (and its two table entries),
makes the four file routes carry plain `require_read`, restores the client's
`appendTokenToUrl` render-time injection, restores the compiled-default Nginx
access log and uvicorn's access log, and drops the canary from the smoke test.

Rolling back re-opens MV-SEC-007 and returns the access-log leak, so a rollback
must re-open the finding and name a new owner rather than assume the exposure
went away. There is nothing else to unwind: no migration runs, no row is
written, and a grant that outlives the rollback (at most 60 seconds) is simply
never checked again.

## Verification

API:

- `api/tests/test_file_grants.py` — mint then use on all four templates; the
  400/404 matrix (non-grantable path, unknown query key, `inline` on the wrong
  route, empty and oversized batches); expiry and the over-`MAX_TTL` refusal;
  tampering and path swapping; `?token=` rejected on all four file routes; a
  grant rejected as `Authorization: Bearer` on `/assets` and `/me`; both
  directions of cryptographic isolation; sign-out invalidating outstanding
  grants; query-key and `inline` matching; the auth-disabled mint; viewer may
  mint, anonymous may not.
- `api/tests/test_auth_users.py::test_query_token_no_longer_authorizes` — the
  header-only contract at the authenticator.
- `api/tests/test_operator_log_hygiene.py` — pins `web/nginx.conf`'s
  `log_format`/`access_log`, `api/Dockerfile`'s `--no-access-log`, the smoke
  canary, and the retirement of the `token=` query credential. It also pins
  `error_log /dev/null` (request-time error logging disabled) and the query-free
  `$upstream_addr`/`$upstream_status` access fields.
- `api/tests/test_permissions_matrix.py` — pins the 64-route matrix as the
  documented size, adds `POST /file-grants` to the READ sweep (a viewer is
  allowed, an anonymous caller is refused, a viewer is still denied every write
  and admin route), and pins the 200 the mint answers when auth is disabled.

Web:

- `web/src/lib/fileGrants.test.ts` — the grantable filter, batch coalescing,
  the >50 split, inline priming, freshness, eviction, expired/ISO expiries, the
  rejecting minter, the no-minter degradation, `useGrantedFileUrl`, and the
  absence of `appendTokenToUrl`.
- `web/src/lib/fileUrl.test.ts` — a primed path renders the signed URL, an
  unprimed or evicted path renders the plain join, `?inline=1` resolves its own
  grant, the session token is never appended even when signed in, and
  `renderFileUrl` is gone.
- `web/src/ui/deferredFileGrants.test.tsx` — advances the clock past
  `FILE_GRANT_TTL_SECONDS` and exercises each deferred interaction: a
  virtualized-grid row remount (unmount then remount a card), a card that
  re-renders while mounted after the minute, a preview dialog opened after the
  grant expired, and all three `<a download>` links as they re-mint; it also
  pins that the slicer handoff re-mints at click time.
- `web/src/lib/useFileGrants.test.ts` — the mount prime (cold and warm), the
  silent refresh (the cache stays warm, the component does not repaint), the
  live variant's re-render, the no-minter degradation (nothing scheduled), the
  failed-mint settle, the ten-second retry that heals a renewal which failed
  across an expiry, the per-rels-key gate (a swapped asset is not painted
  unsigned), and that two consumers of one rel coalesce into one mint.

Ops:

- `scripts/container-smoke.sh` — the live canary request through the web proxy,
  the two `compose logs` assertions, and the dead-upstream canary: stop the
  `api` service, send the query-shaped canary again, require a 5xx plus the
  query-free access line, and fail if any container log contains the canary,
  `?token=` or `?sig=`.
- `slicer-bridge/cmd/slicer-bridge/main_test.go` — `redactURL` rewrites both
  `token=` and `sig=`.

Docs:

- `api/tests/test_adr_threat_model.py` — pins this ADR's title, status, required
  sections and ticket, and pins ADR 0004's supersession link so the interim
  decision cannot be quietly deleted.

## Superseding conditions

This ADR supersedes ADR 0004 for the MV-SEC-007 design and its `?token=`
interim acceptance. ADR 0004 remains the record of the import-cookie decision
(MV-SEC-017) and of the `localStorage` risk acceptance (MV-SEC-008); a change to
either belongs in a new ADR, not in an edit here.

This ADR is superseded if the API moves to a cookie-based session (which changes
what an `Authorization`-less request can carry), if a CSP baseline plus another
URL-credential design lands (e.g. a grant confined to a sandboxed origin), if
MakerWorld/Thingiverse-style per-request remote credentials make the OS handoff
unnecessary, or if the four grantable routes stop covering the file surfaces the
client actually renders — at which point the allow-list, not the credential,
needs the decision.
