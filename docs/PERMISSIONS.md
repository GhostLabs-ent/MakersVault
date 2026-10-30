# Roles and permissions (Mf-2nbc)

Curiarium enforces four roles server-side, on every route. The web client is
not part of the security boundary: anything it hides (or forgets to hide) is
still refused by the API.

## Roles

| Role          | Intended for                          | Usable level                    |
|---------------|---------------------------------------|---------------------------------|
| `admin`       | the operator of the deployment        | `admin` (everything)            |
| `editor`      | someone who manages the library       | `write` (rename/move/delete)    |
| `contributor` | family members who add to and organise the library but must never destroy it | `contribute` (upload/edit, no destroy) |
| `viewer`      | read-only access (default for new accounts; the SSO default is `OIDC_DEFAULT_ROLE`) | `read`                    |

Levels are ranked: `public` (0) < `read` (1) < `contribute` (2) < `write` (3) <
`admin` (4). A principal may use every level at or below its own. A role that is
unknown or blank ranks as `public`, i.e. it is denied even reads - fail closed.

| Capability                                           | admin | editor | contributor | viewer |
|------------------------------------------------------|:-----:|:------:|:-----------:|:------:|
| Browse assets, folders, tags, trash                  |  yes  |  yes   |     yes     |  yes   |
| Browse projects and their member assets              |  yes  |  yes   |     yes     |  yes   |
| Download files, thumbnails, prepared prints          |  yes  |  yes   |     yes     |  yes   |
| Download a zip of a selection/folder/tag             |  yes  |  yes   |     yes     |  yes   |
| Poll library scan status                             |  yes  |  yes   |     yes     |  yes   |
| View and browse snapshots                            |  yes  |  yes   |     yes     |  yes   |
| List and revoke own sessions (devices)               |  yes  |  yes   |     yes     |  yes   |
| Upload, and import from a URL, a zip or a project    |  yes  |  yes   |     yes     |   no   |
| Tag / notes / creator / collection edits             |  yes  |  yes   |     yes     |   no   |
| Add a supporting file, generate a thumbnail          |  yes  |  yes   |     yes     |   no   |
| Rename or reorder supporting files (display only)    |  yes  |  yes   |     yes     |   no   |
| Create folders                                       |  yes  |  yes   |     yes     |   no   |
| Create a project, edit its details, add/remove members |  yes  |  yes   |     yes     |   no   |
| Rename an asset on disk                             |  yes  |  yes   |     no      |   no   |
| Move an asset between folders                        |  yes  |  yes   |     no      |   no   |
| Rename or move a folder (it carries its tags)        |  yes  |  yes   |     no      |   no   |
| Delete assets, folders (to the trash), supporting files or prepared prints |  yes  |  yes   |     no      |   no   |
| Bulk move or bulk delete of assets                   |  yes  |  yes   |     no      |   no   |
| Start a library scan                                 |  yes  |  yes   |     no      |   no   |
| Take or restore a snapshot                           |  yes  |  yes   |     no      |   no   |
| Manage retention, delete a snapshot, read scheduler status |  yes  |   no   |     no      |   no   |
| Change storage / mount-import settings               |  yes  |   no   |     no      |   no   |
| List and revoke any user's sessions                  |  yes  |   no   |     no      |   no   |
| Create users, set roles, disable accounts            |  yes  |   no   |     no      |   no   |
| Read the audit log                                   |  yes  |   no   |     no      |   no   |
| Purge the trash                                      |  yes  |   no   |     no      |   no   |

The rows are split so that no single row spans the contribute/write line: one
row that conflated an upload with a rename would make the `contributor` column
unreadable, which is the whole point of the column. Everything reversible that
adds to or organises the library is `contribute`; anything that destroys or
renames a file on disk is `write`.

The Settings snapshot card is **admin-only in the UI** -- the storage section that
mounts it is shown to admins -- while `POST /snapshots` and
`POST /snapshots/{name}/restore` are editor-level in the matrix above. So an
editor holds capability the UI never offers: the matrix, not the UI, is the
authorization contract. Deleting a snapshot, reading or changing the retention
policy and reading the scheduler status are admin on both sides.

## How enforcement works

`curiarium/api/permissions.py` is the only mechanism. Each guarded route names
its level in the signature:

```python
@app.get("/assets", response_model=List[AssetOut])
def list_assets(..., _: Optional[AuthContext] = Depends(require_read)):
```

`require_read` / `require_contribute` / `require_write` / `require_admin` wrap
`auth.require_auth` and then call `permissions.authorize(request, context, level)`,
which raises 403
when the principal's role does not reach the level. `require_auth` reads the
`Authorization: Bearer` header and nothing else: `?token=` was retired with the
file grants, so a session token in the query string is a 401 on every route,
the four file routes included. Two tests pin that in `curiarium/api`:
`tests/test_auth_users.py::test_query_token_no_longer_authorizes` and
`tests/test_file_grants.py::test_a_session_token_in_the_query_is_retired_on_every_file_route`.
The declaration *is* the enforcement: there is no second place to look for a
permission check.

`require_file_read` is the one route-level exception
(`api/permissions.py`, `require_permission(READ, require_auth_or_file_grant)`).
It declares the same READ level and adopts a second authenticator,
`auth.require_auth_or_file_grant`, and it is attached only to the four
file-serving routes - `GET /file/{asset_id}/{name}`,
`GET /asset/{asset_id}/files/{file_id}`, `GET /thumb/{asset_id}.jpg` and
`GET /asset/{asset_id}/prepared-print`. The level is unchanged, so a grant is
read-only through the ordinary rank ladder; the scope is what keeps it away
from every list, write and admin route, because those carry plain
`require_read` / `require_contribute` / `require_write` / `require_admin` and
never consult `?sig=`.

Because a per-route dependency is easy to forget, `ROUTE_PERMISSIONS` in the same
module records the audited matrix, and `assert_routes_classified(routes)` proves
the two agree. `routes` is the route list enumerated from the routers we own,
`permissions.router_routes(*main.API_ROUTERS)` - not `app.routes`, which under
current fastapi is a lazy tree that hides the included routes and would check
nothing. `main.API_ROUTERS` drives both that enumeration and the `include_router`
loop, so a served router cannot go unchecked. The check runs in `main.lifespan`
**before** migrations and before the server accepts connections, so a route that
ships without a level - or with a level the matrix does not expect - fails the
boot instead of failing open. The matrix tests cross-check the enumeration
against fastapi's own walk of `app.routes` and assert the route count equals the
matrix key count, so a partial or empty enumeration fails there instead of
passing vacuously; the permission sweeps (`tests/test_permissions_matrix.py`)
are parametrised from `ROUTE_PERMISSIONS`, so the table that documents the rules
is the table the tests enforce.

The startup check reports all drift at once:

* a route that declares a level must match the matrix for that `(method, path)`;
* a route that declares no level must be `public` in the matrix;
* a route must never declare two levels;
* every route must be in the matrix, and every matrix key must be a real route
  (no stale entries).

403 details are per level and say what was needed, not what exists:
`read` -> "Authentication required", `contribute` -> "Contributor, editor or
administrator access required", `write` -> "Editor or administrator access
required", `admin` -> "Administrator access required".

**Authorization is not auditing (Mf-s3z0).** `permissions.authorize()` decides;
it does not emit audit events. It runs before the mutation, has no target, and
cannot see what changed or whether the request succeeded, so it cannot record an
event that is true. Audit rows are written at the action site instead, in the
same transaction as the mutation, and `audit.assert_audit_coverage()` in
`main.lifespan` (right after `assert_routes_classified`) refuses to boot when a
mutating route is neither audited nor exempt with a reason. See
[`AUDIT.md`](AUDIT.md).

### File grants (`?sig=`)

A URL credential still exists because a browser surface cannot carry a header:
an `<img>` preview, an `<a download>` and the `curiarium-slicer://` OS
handoff are navigations, not fetches, and none of them can set `Authorization`.
What travels in the query now is not a session token but a **grant**:

* signed with a domain-separated subkey (`auth.file_grant_key()`): HMAC-SHA256
  over `AUTH_SECRET` with the info string `curiarium/file-grant/v1`, so a grant
  never verifies as a session token and a session token never verifies as a
  grant;
* one path (`p`), read-only (`scope="file:read"`, `typ="file-grant"`,
  `aud="curiarium:file-grant"`), 60 seconds (`FILE_GRANT_TTL_SECONDS`), with
  the verifier independently refusing any grant whose `exp - iat` exceeds 300
  (`FILE_GRANT_MAX_TTL_SECONDS`);
* bound to a live session (`sid`), so signing out invalidates every outstanding
  grant;
* minted by `POST /file-grants`, which is itself READ - a viewer may mint one,
  and the grants it produces reach nothing but the four file routes.

**The session JWT is no longer accepted in a URL at all.** `require_auth` is
header-only, and the grant verifier matches `request.url.path` against the `p`
claim and allows only `sig`, `v` and `inline` alongside it, so a grant cannot be
replayed on another path or with another route's parameters.

The mint is an allow-list, not a signing oracle. Exactly four templates are
grantable (`api/routers/asset_files.py`, `_FILE_GRANT_TEMPLATES`), each is
existence-checked against the database before it is signed, and anything else -
a path outside the four, an empty batch, more than 50 paths, an unknown query
key, `inline` on a route that does not take it - is a 400; an unknown asset or
file is a 404. `POST /file-grants` is in `ROUTE_PERMISSIONS` as READ and in
`audit.EXEMPT_ROUTES` with the reason "mints a short-lived read-only file grant;
mutates nothing". It also answers 200 when `AUTH_ENABLED` is false, minting with
`sid=None`, unlike the token endpoints that 503.

Log posture: `web/nginx.conf` declares `log_format curiarium` and binds it with
`access_log`; the format rebuilds the request line from `$request_method`,
`$uri` and `$server_protocol` (never `$request`), so the query never reaches the
access log, and adds the query-free `$upstream_addr`/`$upstream_status`. The same
file sets `error_log /dev/null` because nginx has no error-log format and embeds
the whole request line - query included - in upstream-failure and
malformed-request messages; request-time error text is deliberately traded for
that guarantee. `api/Dockerfile` runs uvicorn with `--no-access-log`, and
`scripts/container-smoke.sh` sends `/api/health?token=<canary>&sig=<canary>`
through the live proxy, then stops the API and sends the same query shape again,
failing if the canary, `?token=` or `?sig=` appears in any container log. The
design, its residual risks and its rollback are in
[ADR 0005](../curiarium/docs/adr/0005-file-grant-urls.md).

### OIDC / external identity (Mf-4c24)

SSO is a second front door, not a replacement for the first: with
`OIDC_ENABLED=false` (the default) the four routes below answer 503 and local
password login, the break-glass environment admin, the login throttle and the
file-grant path are exactly as they were. With it on, the provider says *who you
are* and the local `users` row still says *what you may do* — no claim ever
becomes a permission:

* **Identity binds only on `(issuer, subject)`.** The new `oidc_identities`
  table (migration 10) has a unique constraint on that pair and `api/oidc.py`
  resolves an SSO login by it and nothing else. A `preferred_username` or an
  `email` claim is display material: neither is looked up, so neither can be used
  to take over an existing local account.
* **A new SSO user gets the configured default role** (`OIDC_DEFAULT_ROLE`,
  default `viewer`) with `password_hash = NULL`, so the account cannot be
  replayed against `POST /login`. The accepted set is every role in
  `accounts.ROLES` except `admin`, derived at call time rather than listed
  twice, and `admin` is refused at boot.
* **`editor` is the highest a group match can grant, and it comes only from
  `OIDC_EDITOR_GROUPS`** — a group match on the claim named by
  `OIDC_GROUPS_CLAIM`. It beats a lower `OIDC_DEFAULT_ROLE` at provisioning time.
* **A claim cannot mint a `contributor` per principal.** The role a non-matching
  principal is provisioned with is **operator configuration**, not an IdP
  decision: it is `OIDC_DEFAULT_ROLE` (`viewer` unless the deployment says
  otherwise), read once when the account is created. Only an `editor` group match
  is honoured, so no claim can choose `contributor` for one person and not for
  another. A stored role is never rewritten on re-login, so a role set locally
  survives every later sign-in, and a later `PATCH /users/{user_id}` overrides
  whatever the default provisioned. A third *claim* tier (an
  `OIDC_CONTRIBUTOR_GROUPS`) would hand an authorization decision to the IdP,
  which is exactly why there is none.
* **`admin` is unreachable from claims.** `OIDC_ADMIN_GROUPS` is refused at boot
  if it is non-empty, `OIDC_DEFAULT_ROLE=admin` is refused the same way, and an
  existing account's `users.role` is **never** rewritten by a claim on re-login.
  Promotion is `PATCH /users/{user_id}` by an admin, with the last-admin
  invariant and a `user.role_change` audit row.
* **The two allow-lists compose with AND.** When `OIDC_ALLOWED_GROUPS` and
  `OIDC_ALLOWED_DOMAINS` are both set a principal must satisfy both; a security
  control composes restrictively, and OR would fail open. A boot with neither set
  is refused.
* **Provisioning needs an enabled admin first.** `POST /auth/oidc/exchange`
  refuses to create the first SSO account unless an enabled `admin` already
  exists (`sso_error=no_admin_bootstrap`), because a provisioned account of any
  default role empties the users table's break-glass path while leaving zero
  admins.
* **The handoff code is a URL fragment, single-use, and lives 120 seconds.**
  The callback redirects with `#sso_code=`, never `?sso_code=`, so the code never
  reaches browser history, `Referer`, the access log or the proxy; the exchange
  pops it before looking it up, so it cannot be redeemed twice.

The flow, the claim policy, the threat model and the in-process-store limitation
are in
[ADR 0006](../curiarium/docs/adr/0006-oidc-sso-flow-and-role-policy.md).

## The route matrix

Paths are FastAPI templates exactly as declared. 90 routes: 9 public, 33 read,
19 contribute, 13 write, 16 admin.

The collection/instance templates are deliberately asymmetric: the collection is
`/projects` while one project is `/project/{project_id}`, exactly like `/folders`
vs `/folder/{folder_id}`. Match on the template, not on the noun.

### public (no authentication)

| Method | Path       | Why |
|--------|------------|-----|
| GET    | `/health`  | liveness; reports `auth_required` |
| POST   | `/login`   | issues tokens (503 when auth is disabled) |
| POST   | `/refresh` | rotates tokens (503 when auth is disabled) |
| POST   | `/logout`  | revokes by refresh token (503 when auth is disabled) |
| GET    | `/auth/oidc/status` | reports whether SSO is enabled (503 when auth is disabled) |
| GET    | `/auth/oidc/start` | begins the Authorization Code + PKCE flow (503 when auth is disabled) |
| GET    | `/auth/oidc/callback` | IdP redirect target; parks a single-use handoff code (503 when auth is disabled) |
| POST   | `/auth/oidc/exchange` | the only mutation: provisions/links, opens a session, writes the audit row (503 when auth is disabled) |
| POST   | `/mfa/verify` | trades the five-minute challenge `/login` minted for the real token pair; it runs before a session exists, so it cannot carry a bearer token (503 when auth is disabled) |

### read (any authenticated role, viewers included)

| Method | Path                                   | Why |
|--------|----------------------------------------|-----|
| GET    | `/me`                                  | own profile |
| GET    | `/me/sessions`                         | own active sessions; ownership scoping is a data constraint |
| DELETE | `/me/sessions/{session_id}`            | revoke one of your own sessions; a foreign id is a 404, never a 403 |
| GET    | `/mfa`                                 | own two-factor status (enrolled, recovery codes left, policy, `can_enrol`) |
| POST   | `/mfa/enrol`                           | mints a candidate TOTP secret; persists nothing, sudo-gated by the body password |
| POST   | `/mfa/confirm`                         | stores the seed the caller proved they can use and returns ten recovery codes once |
| POST   | `/mfa/step-up`                         | proves a code for the *current* session; the one route an admin who did not come through `/login` needs |
| DELETE | `/mfa`                                 | disables two-factor for the caller; refused while the admin policy depends on it |
| POST   | `/mfa/recovery-codes`                  | replaces the caller's ten recovery codes; the plaintext is returned once |
| GET    | `/library/scan`                        | status poll every client uses; no secrets |
| GET    | `/imports/runs`                         | mount-import history; same disclosure class as scan errors |
| GET    | `/imports/runs/{run_id}`                | one run with its bounded per-file errors |
| GET    | `/file/{asset_id}/{name}`               | download |
| GET    | `/asset/{asset_id}/files`               | list supporting files |
| GET    | `/asset/{asset_id}/files/{file_id}`     | download a supporting file |
| GET    | `/asset/{asset_id}/files/limits`        | supporting-file count/total against the caps; no secrets |
| GET    | `/asset/{asset_id}/prepared-print`      | download a prepared print |
| GET    | `/thumb/{asset_id}.jpg`                 | thumbnail |
| POST   | `/file-grants`                          | mints a short-lived read-only signed file grant; nothing mutates |
| GET    | `/assets`                               | list assets |
| GET    | `/assets/delete-preview`                | pure SELECT that counts a bulk delete, and reports whether a pre-delete snapshot will be taken |
| GET    | `/tags`                                 | list tags |
| GET    | `/creators`                             | list the distinct creator facet |
| POST   | `/download/zip`                         | POST-for-download: it builds a temp zip and streams it, nothing is stored |
| GET    | `/folders`                              | list folders |
| GET    | `/folder/{folder_id}/delete-preview`    | pure SELECT that counts what a delete would remove |
| GET    | `/folder/{folder_id}/download`          | download a folder as a zip |
| GET    | `/projects`                             | list projects with their member counts |
| GET    | `/project/{project_id}/assets`          | list one project's member assets |
| GET    | `/trash`                                | list the trash |
| GET    | `/storage/capabilities`                 | read-only filesystem capability report; creates nothing |
| GET    | `/snapshots`                           | lists the snapshots this volume has; reads the provider view, creates nothing |
| GET    | `/snapshots/{name}/browse`             | browses one snapshot read-only; creates nothing |

### contribute (contributor, editor or admin)

Everything here adds to or organises the library and is reversible from the
library's point of view: it creates rows, writes metadata, or uploads new bytes.
Nothing in this table deletes or renames anything already on disk - that is the
`write` table below - which is exactly the line the `contributor` role is built
on.

| Method | Path                                        | Why |
|--------|---------------------------------------------|-----|
| POST   | `/upload`                                   | creates an asset: new bytes in, nothing existing touched |
| POST   | `/import`                                   | creates an asset from a URL |
| POST   | `/import/project`                           | import a URL into a new or existing project (one step) |
| POST   | `/import/inspect`                           | no mutation, but an outbound-fetch oracle (URL in, remote response out). Contribute rather than read because the client's link-import flow calls it immediately before `/import`: whoever may start an import needs it, and nobody below contributor starts one |
| POST   | `/import/zip/entries`                       | same: outbound fetch, no mutation, and the zip-import dialog calls it to list entries before `/import/zip` |
| POST   | `/import/zip`                               | creates assets from a zip |
| POST   | `/asset/{asset_id}/files`                   | uploads a supporting file next to an asset; removes nothing |
| PATCH  | `/asset/{asset_id}/files/{file_id}`         | renames a supporting file (display only; the bytes never move) |
| PUT    | `/asset/{asset_id}/files/order`             | rewrites the supporting-file display order (display only; the bytes never move) |
| POST   | `/asset/{asset_id}/thumbnail-generated`     | writes a thumbnail |
| POST   | `/assets/batch/tags`                        | bulk tag mutation |
| POST   | `/assets/batch/meta`                        | bulk creator/notes edit; the route has no title/name field, so no batch can rename on disk |
| POST   | `/asset/{asset_id}/tags`                    | metadata mutation |
| POST   | `/asset/{asset_id}/meta`                    | notes/creator/collection edits do not touch the file; the route **escalates to write when `name` or `title` is in the body**, because those rename the asset on disk (`permissions.authorize_metadata_edit`) |
| POST   | `/folders`                                  | create a folder |
| POST   | `/projects`                                 | create a project (a row set, no files) |
| PATCH  | `/project/{project_id}`                     | rename / describe / set the cover of a project: its rows, not its assets |
| POST   | `/project/{project_id}/assets`              | add project memberships |
| DELETE | `/project/{project_id}/assets`              | removes a membership row, not an asset; the bytes stay (the one DELETE with a JSON body) |

### write (editor or admin)

Destroy or rename on disk - the editor line. Every route here either moves bytes
out of the library, renames a file the library owns, or rescans the volume.

| Method | Path                                        | Why |
|--------|---------------------------------------------|-----|
| POST   | `/asset/{asset_id}/rename`                  | rename on disk |
| POST   | `/asset/{asset_id}/folder`                  | move an asset into a folder |
| POST   | `/assets/batch/folder`                      | bulk move |
| POST   | `/assets/batch/delete`                      | bulk delete (to trash; confirmed by item count) |
| DELETE | `/asset/{asset_id}`                         | delete an asset (to trash; the file name must be confirmed) |
| DELETE | `/asset/{asset_id}/files/{file_id}`         | deletes a supporting file |
| DELETE | `/asset/{asset_id}/prepared-print`          | deletes a prepared print |
| PATCH  | `/folder/{folder_id}`                       | rename/move a folder - and it carries the folder's tags in the same body, which is why a contributor cannot retag one (see "Known consequences") |
| DELETE | `/folder/{folder_id}`                       | delete a folder (to trash) |
| DELETE | `/project/{project_id}`                     | delete a project and its memberships (never an asset) |
| POST   | `/library/scan`                             | starts a scan: registers files found on disk and refreshes `missing_since`; audited as `library.scan.start` |
| POST   | `/snapshots`                                | takes a snapshot of the library; an editor's library action |
| POST   | `/snapshots/{name}/restore`                 | copies snapshot bytes into `recovered/`; never overwrites |

### admin (administrators only)

| Method | Path                           | Why |
|--------|--------------------------------|-----|
| GET    | `/audit`                       | reading the audit trail is administration |
| GET    | `/settings/mount-import`       | settings namespace is admin-only |
| POST   | `/settings/mount-import`       | mutates settings |
| POST   | `/settings/mfa`                | the MFA policy decides what every admin route demands, so changing it is administration |
| GET    | `/settings/storage`            | settings namespace is admin-only |
| POST   | `/settings/storage`            | storage template governs every future upload |
| POST   | `/users`                       | user administration |
| GET    | `/users`                       | user administration |
| PATCH  | `/users/{user_id}`             | user administration (including role changes) |
| GET    | `/users/{user_id}/sessions`    | session administration over another principal |
| DELETE | `/sessions/{session_id}`       | revoking another principal's device is administration |
| POST   | `/trash/purge`                 | destroying deleted data is irreversible |
| GET    | `/snapshots/retention`         | retention decides what history survives; admin namespace |
| POST   | `/snapshots/retention`         | mutates retention |
| GET    | `/snapshots/schedule`          | the scheduler's status report: last attempt, count, retention echo, warnings; operates nothing |
| DELETE | `/snapshots/{name}`            | deleting a snapshot decides what history survives |

## Destructive confirmations

Deleting is recoverable, but it still asks the caller to prove it meant the
object it named. These gates are enforced by the API, not by the web client, and
they are deliberately declared as optional fields: a missing value is a readable
`400`, never a FastAPI `422`.

| Route | Gate |
|---|---|
| `DELETE /folder/{folder_id}` | `?confirm_name=<folder name>` must match exactly |
| `DELETE /asset/{asset_id}` | `?confirm_name=<file name>` must match exactly |
| `POST /assets/batch/delete` | `confirm_count` must equal the number of ids |

The asset gate compares the file name rather than the model name because
`Asset.name` may be empty, which would make the gate a no-op. A batch confirms
with a count instead of one name per id: typing N names is absurd, while a count
still proves the client is deleting exactly the rows it showed the user.

## Authentication modes

* **Auth enabled** (`AUTH_USERNAME` and `AUTH_PASSWORD` set): every guarded route
  needs a bearer token in the `Authorization` header - there is no `?token=`
  fallback on any route; `require_auth` re-reads the session row and the account
  on every request, so a revoked session or a disabled account stops working
  immediately. The four file routes additionally accept a `?sig=` grant (see
  "File grants" above). Session lifecycle (rotation, the 60-second grace window
  and refresh replay) is described in
  [ADR 0007](../curiarium/docs/adr/0007-session-lifecycle-and-refresh-replay.md).
* **Break-glass admin**: the env credentials authenticate as the `admin` role -
  but only while the users table is **empty**. The first `POST /users` revokes
  the break-glass sessions in the same transaction as the insert, and after that
  the env credentials are refused. This is why the last-admin invariant below is
  enforced in code rather than relying on an escape hatch.
* **Auth disabled**: `auth.require_auth` returns `None` and
  `permissions.authorize` treats `None` as "no authentication on this
  deployment", so every route stays open exactly as it was before authorization
  existed. `/login`, `/refresh` and `/logout` answer 503 in that mode, and so do
  `/me`, the `/users` routes and all eight `/mfa*` routes.

## Multi-factor authentication

Two-factor is TOTP (RFC 6238: HMAC-SHA1, six digits, thirty-second steps) and it
is self-service: every `/mfa*` route is READ, because it acts on the caller's own
account exactly like `/me/sessions`, while the admin-wide policy is one ADMIN
route. The design and its threat model are in
[ADR 0008](../curiarium/docs/adr/0008-mfa-totp-enrolment.md).

**The policy.** `mfa_require_admin` is an appconfig setting, `false` by default,
and `POST /settings/mfa` (`{"require_admin": true|false}`) is the only way to
change it; the change is audited as `settings.mfa_require_admin.update`, even
when the value is unchanged. While it is on, `permissions.enforce_admin_mfa` runs
after the ordinary rank check in `authorize()` and refuses an ADMIN call unless
the *session* carries `sessions.mfa_verified_at`. A viewer or editor never
reaches it: they are refused by the rank check first, with the ordinary 403.

**The 403 and its header.** Both "this session has not stepped up" and "this
account has no factor" answer 403 `"Multi-factor authentication required"` -
deliberately not the `"Administrator access required"` string, because the
caller *is* an admin and the session is the problem. The second case adds
`X-MFA-Enrolment-Required: 1`, which is the client's cue to show an enrol-now
panel rather than a dead end. The eight `/mfa*` routes are READ, not ADMIN, so
they stay reachable from the very session that just received the 403: the header
would be useless if the fix required the permission being denied.

**Step-up.** `POST /mfa/step-up` proves a code against the caller's own seed and
sets `mfa_verified_at` on the *current* session. This is what an OIDC login
needs: an SSO exchange opens a session without a marker and never passes through
the `/login` challenge, but it is not exempt from the policy either - the IdP
authenticated a person, it did not prove a second factor to this application.
A password login on an enrolled account is already `mfa_ok` because `/login`
returns a challenge and `/mfa/verify` opens the session with the marker set.

**Break-glass is exempt.** `permissions.enforce_admin_mfa` returns for
`context.kind == sessions.BREAK_GLASS_KIND` before it reads the policy. The
break-glass principal has `user_id = None`, so there is nowhere to store a seed,
and gating the bootstrap path on a secret that needs a user row is circular.

**No lockout is reachable through the switch.** Enabling the policy is a 409
unless the calling session is already `mfa_ok` *and* the caller's account is
enrolled (`"Enrol two-factor authentication and step up before turning this
policy on"`), so the admin who flips it can satisfy it. `DELETE /mfa` is a 409
for an admin while the policy is on
(`"An administrator with the MFA policy on cannot disable two-factor
authentication"`), so the factor cannot be removed from under the policy;
turning the policy off is the way out, and that call is itself an admin route, so
it needs an `mfa_ok` session - the same precondition, which an enrolled admin can
re-establish through `/login` at any time. Both guards are code, not prose.

**Enrolment is sudo-gated.** `POST /mfa/enrol`, `POST /mfa/confirm`,
`DELETE /mfa` and `POST /mfa/recovery-codes` carry the caller's password and
re-check it, so a wrong password is a 403 and a hijacked session cannot plant or
swap a second factor; while an account is enrolled, enrolment is a 409. An
SSO-only account (`password_hash IS NULL`) is a 409: its credential lives at the
IdP, so there is no local password to confirm - and, consequently, no local
seed to enrol. `POST /mfa/verify` is the one new public route, because it runs
before a session exists; it is throttled per challenge subject by a second
`LoginThrottle` instance, so TOTP guesses cannot lock the password login out and
vice versa.

## Changing roles and accounts

`PATCH /users/{user_id}` (admin only):

* body: `{"disabled": true|false}` and/or
  `{"role": "admin"|"editor"|"contributor"|"viewer"}`; unknown fields are
  rejected (`extra="forbid"`);
* both fields are optional, but an empty patch is a **422**
  ("provide disabled and/or role") rather than a silent no-op;
* an unknown role is a **422** from the same validator that guards
  `POST /users`;
* both changes are applied in one transaction with the guard below.

**Last-admin invariant (409).** A change that would leave the deployment with no
enabled administrator is refused with
`"at least one enabled administrator is required"`. It covers **both** paths to
the same footgun:

* demoting the last enabled admin (`role` -> `editor`/`viewer`);
* disabling the last enabled admin (`disabled` -> `true`).

The guard evaluates the target's *post-change* viability (`role == admin and not
disabled`), excludes the target from the count of other enabled admins, and runs
in the same transaction as the mutation. Self-demotion is allowed as soon as
another enabled admin exists. It is not cosmetic: once the users table is
non-empty the break-glass env admin no longer authenticates, so a demoted last
admin cannot be recovered through the API.

**Accepted risk (not fixed): a TOCTOU window on concurrent demotions.** Two
requests that demote the last two admins can both read a count that still
includes the other, both pass the guard, and both commit, leaving zero admins.
SQLite serialises commits, not the count reads. For a single-operator,
self-hosted deployment the window requires two simultaneous admin requests and
is accepted rather than paid for with a second lock or a unique-index trick.
Say it out loud in the report if this ever bites.

**Role changes do not revoke sessions.** `require_auth` calls
`sessions.role_for()` and re-reads `users.role` from the database on every
request; the `role` claim in the JWT is informational and never trusted. A
demotion therefore takes effect on the demoted account's next request while its
sessions stay valid.

## Known consequences worth knowing

* **`POST /library/scan` is write**, while `GET /library/scan` is read. A scan
  is library work - it walks storage, registers files found on disk and
  refreshes `missing_since` - not an administration job, so editors may start
  one and it is still audited as `library.scan.start`. The GET stays read
  because every client polls the status. A viewer *or a contributor* clicking
  the same "Re-scan" action still gets a 403: starting a scan is not a
  contribute action, and the missing-file banner only offers Re-scan to
  editors.
* **`GET /library/scan` returns `errors: List[str]`** that may contain storage
  filenames. That is the same disclosure class as `storage_path` on `AssetOut`
  and `FolderOut`, which viewers already receive, so it is not a new leak.
* **`GET /imports/runs` discloses run telemetry.** A row carries the mount
  root, per-file relative paths in its error list, and the run mode/counters.
  That is the same disclosure class as the storage filenames in
  `GET /library/scan` errors, which viewers already receive; it is read-only and
  grants no new action.
* **Settings reads are admin**, and the client no longer makes a non-admin pay
  for it: the Storage Structure card is hidden from the settings menu and the
  mount-import card from the Imports section below `admin`, and the reads behind
  them are never issued (`settings/Settings.tsx` passes `enabled: isAdmin` to
  `useStorageSettings`/`useMountImportSettings`). The storage section still
  renders a not-permitted state if reached directly, but the menu does not offer
  it. That is honest: they cannot change it either.
* **A contributor cannot retag a folder.** `PATCH /folder/{folder_id}` carries
  the name, the parent and the tags in one body, and renaming or moving a folder
  is `write`, so the whole route is `write` and the tag half goes with it. A
  contributor therefore has no way to edit a folder's tags even though tags on
  an *asset* are theirs. Splitting that route into a tag-only `contribute` call
  and a name/parent `write` call is deliberately out of scope for Mf-01f0: it is
  a second route, not a permission change.
* **Editors act on every asset.** There is no per-asset ownership in this
  ticket; Mf-arm6 owns that, and it will need a per-record check inside the
  handlers (the level stays `write`). A contributor acts on every asset too.
* **The web client** maps a 403 to "Your role does not allow this action."
  (`lib/api/http.ts`, `assertOk`) and gates the admin-only surfaces on the role
  `GET /me` reports: the sidebar "Audit log" entry, the Storage Structure
  settings entry and the mount-import card in the Imports section are hidden
  below `admin`, and a direct visit to the audit view renders a not-permitted
  state instead of the raw 403 (`lib/auth.ts` `roleAtLeast`,
  `ui/SidebarFooter.tsx`, `ui/useSessionRole.ts`, `ui/NotPermitted.tsx`,
  `ui/settings/Settings.tsx`). That is honesty, not enforcement: the API
  remains the control, and every hidden or ungated control is still refused by
  it.
* **Write surfaces are gated client-side, as two capabilities since Mf-01f0.**
  The `contribute` and `write` thresholds live in one helper,
  `roleAtLeast(role, ...)` (`lib/auth.ts`), and the app shell derives both once
  in `ui/App.tsx` from the same `/me` role cache:
  `canContribute = roleAtLeast(role, "contributor")` and
  `canDelete = roleAtLeast(role, "editor")`. Both are threaded as **required**
  props: `ui/UploadBar.tsx` receives only `canContribute` (its only write is an
  upload/import), while `ui/asset-grid/*` (`AssetGrid`, `AssetCard`,
  `useAssetDrop`), `ui/BulkActionBar.tsx`, `ui/ProjectView.tsx`,
  `ui/ProjectLanding.tsx` and `ui/project-attach/useAttachDrop.ts` receive
  both. `ui/UploadQueuePanel.tsx` is rendered by `App` only when
  `canContribute` is set. `ui/Sidebar.tsx` receives `role` and derives both
  capabilities locally, and `ui/settings/Settings.tsx` (which passes it on to
  `ui/settings/ImportsSection.tsx`) deliberately keeps a single
  `canWrite = roleAtLeast(role, "editor")`: its one mutating control is the
  folder-scan card (`POST /library/scan`), which is still `write`. One threshold
  in one helper rather than a comparison per surface. `role` is `null` until
  `/me` answers, so an unknown role has neither capability (fail closed), and a
  demotion lands on the next `/me` refresh.
  A viewer loses the upload bar, drag-and-drop upload, folder
  create/rename/delete, asset edit/tags/move/delete/add-to-project, per-file
  mutation/re-scan/forget, the bulk write actions, project
  edit/delete/cover/attach/remove-member, the local folder-scan card and the
  upload-queue panel. A viewer keeps search, sort and filters, breadcrumbs,
  subfolder tiles, downloads (including folder ZIP export), preview, the
  slicer, project browsing, the read-only mount-import run history and the
  cookie preferences (client-side settings, not API writes).
  A contributor sits between the two, and the UI shows it: they gain the upload
  bar, drag-and-drop upload (grid and sidebar), link/zip/project import, asset
  tag and notes/creator/collection edits, folder create and subfolder create,
  project create/edit/add-member/remove-member, attaching files to a project,
  adding a supporting file, the display-only supporting-file rename and
  reorder, thumbnail generation, the contribute half of the bulk bar (tags and
  metadata) and the upload-queue panel (a retry of an upload is a contribute,
  not a write). They still lose folder rename and move (and therefore folder
  retagging), asset rename, moving an asset between folders, folder delete,
  asset delete, supporting-file delete, prepared-print delete, batch move and
  batch delete, the local folder-scan card and snapshot actions. The client is
  still not the boundary: a stale or tampered role cache only hides or shows a
  button, it cannot change what the API allows.
* **No direct-visit not-permitted state is needed for the contribute or write
  surfaces.** Both capabilities only show or hide controls inside views every
  role may open. There is no client router and no contribute-only or write-only
  view or route, so there is nothing to visit directly: the only mixed section
  is Settings → Imports,
  which hides the scan card while the read-only import-run history and the
  cookie cards stay. The audit and storage `NotPermitted` states from Mf-5tyz
  are unchanged.
* **Audit.** Every audited action now writes one row (one per affected asset on
  the batch routes) in the same transaction as the mutation, so an audit write
  failure is a failed mutation - fail-closed, except for the two filesystem-only
  actions (`trash.purge`, `library.scan.start`), which are fail-loud. That costs
  one insert per audited action and grants nothing new: the actor is the
  principal the request already carried, or `local` when auth is disabled.
  `GET /audit` is an admin read; the sidebar "Audit log" entry is shown only
  when `/me` reports `admin`, and a non-admin who reaches the audit view anyway
  gets a not-permitted state while the API still answers 403 - the client is not
  the security boundary. Details in [`AUDIT.md`](AUDIT.md).

## Non-goals (owned by other tickets)

* Mf-arm6 - per-asset ownership (editors act on all assets until then).

## Migrations

None for roles. `users.role` and `users.disabled` already exist (migration 005);
the roles ticket adds enforcement and the mutation path, not schema.

Migration 006 (`audit_events`) belongs to Mf-s3z0 and adds no permission column;
it is described in [`AUDIT.md`](AUDIT.md).

Migration 010 (`oidc_identities`) belongs to Mf-4c24 and adds no permission
column either. It adds one table — `(issuer, subject)` under a unique
constraint, the local `user_id`, and the timestamps — which is what makes an
external identity a persisted fact rather than a claim compared at login time.
No role is stored there: the account's role stays on `users.role`, so a claim
set can never be the authority for what an SSO user may do.

Migration 011 (`session_rotation_history`) belongs to Mf-7op4 and adds no
permission column. It appends two nullable columns to `sessions` —
`previous_refresh_token_hash` (one superseded hash, never a token) and
`rotated_at` — plus a non-unique index on the former. They back the one-
generation grace window in ADR 0007; the session routes themselves needed no
schema change, because `device`, `user_agent` and `client_ip` have been recorded
since migration 005.

Migration 012 (`mfa_totp`) belongs to Mf-lg02 and adds no permission column
either. It appends three nullable columns to `users` — `totp_secret` (AES-256-GCM
ciphertext under an `AUTH_SECRET` subkey; NULL means not enrolled),
`totp_enrolled_at` and `totp_last_step` (the counter of the last accepted TOTP
code) —
one nullable column to `sessions` (`mfa_verified_at`, the per-session proof the
admin policy reads), and a `mfa_recovery_codes` table with a unique
`(user_id, code_hmac)` index. Every object is `IF NOT EXISTS`/`_add_column`
guarded, so re-applying 012 is harmless. The schema and the reasoning are in
[ADR 0008](../curiarium/docs/adr/0008-mfa-totp-enrolment.md).
