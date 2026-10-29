# Roles and permissions (Mf-2nbc)

MakerVault enforces three roles server-side, on every route. The web client is
not part of the security boundary: anything it hides (or forgets to hide) is
still refused by the API.

## Roles

| Role     | Intended for                          | Usable level                       |
|----------|---------------------------------------|------------------------------------|
| `admin`  | the operator of the deployment        | `admin` (everything)               |
| `editor` | someone who manages the library       | `write` (create/mutate/delete)     |
| `viewer` | read-only access (default for new accounts) | `read`                       |

Levels are ranked: `public` (0) < `read` (1) < `write` (2) < `admin` (3). A
principal may use every level at or below its own. A role that is unknown or
blank ranks as `public`, i.e. it is denied even reads - fail closed.

| Capability                                   | admin | editor | viewer |
|----------------------------------------------|:-----:|:------:|:------:|
| Browse assets, folders, tags, trash          |  yes  |  yes   |  yes   |
| Browse projects and their member assets      |  yes  |  yes   |  yes   |
| Download files, thumbnails, prepared prints  |  yes  |  yes   |  yes   |
| Download a zip of a selection/folder/tag     |  yes  |  yes   |  yes   |
| Poll library scan status                     |  yes  |  yes   |  yes   |
| Upload / import / rename / edit metadata     |  yes  |  yes   |   no   |
| Delete assets, folders (to the trash), supporting files |  yes  |  yes   |   no   |
| Bulk tag / move / delete / metadata          |  yes  |  yes   |   no   |
| Create / edit / delete projects, edit membership |  yes  |  yes   |   no   |
| Start a library scan                         |  yes  |  yes   |   no   |
| Change storage / mount-import settings       |  yes  |   no   |   no   |
| Create users, set roles, disable accounts    |  yes  |   no   |   no   |
| Read the audit log                           |  yes  |   no   |   no   |
| Purge the trash                              |  yes  |   no   |   no   |

## How enforcement works

`makervault/api/permissions.py` is the only mechanism. Each guarded route names
its level in the signature:

```python
@app.get("/assets", response_model=List[AssetOut])
def list_assets(..., _: Optional[AuthContext] = Depends(require_read)):
```

`require_read` / `require_write` / `require_admin` wrap `auth.require_auth` and
then call `permissions.authorize(request, context, level)`, which raises 403
when the principal's role does not reach the level. `require_auth` reads the
`Authorization: Bearer` header and nothing else: `?token=` was retired with the
file grants, so a session token in the query string is a 401 on every route,
the four file routes included. Two tests pin that in `makervault/api`:
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
`require_read` / `require_write` / `require_admin` and never consult `?sig=`.

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
`read` -> "Authentication required", `write` -> "Editor or administrator access
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
an `<img>` preview, an `<a download>` and the `makersvault-slicer://` OS
handoff are navigations, not fetches, and none of them can set `Authorization`.
What travels in the query now is not a session token but a **grant**:

* signed with a domain-separated subkey (`auth.file_grant_key()`): HMAC-SHA256
  over `AUTH_SECRET` with the info string `makervault/file-grant/v1`, so a grant
  never verifies as a session token and a session token never verifies as a
  grant;
* one path (`p`), read-only (`scope="file:read"`, `typ="file-grant"`,
  `aud="makervault:file-grant"`), 60 seconds (`FILE_GRANT_TTL_SECONDS`), with
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

Log posture: `web/nginx.conf` declares `log_format makervault` and binds it with
`access_log`; the format rebuilds the request line from `$request_method`,
`$uri` and `$server_protocol` (never `$request`), so the query never reaches the
log. `api/Dockerfile` runs uvicorn with `--no-access-log`, and
`scripts/container-smoke.sh` sends
`/api/health?token=<canary>&sig=<canary>` through the web proxy and fails if the
canary appears in either container's log. The design, its residual risks and its
rollback are in
[ADR 0005](../makervault/docs/adr/0005-file-grant-urls.md).

## The route matrix

Paths are FastAPI templates exactly as declared. 65 routes: 4 public, 22 read,
30 write, 9 admin.

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

### read (any authenticated role, viewers included)

| Method | Path                                   | Why |
|--------|----------------------------------------|-----|
| GET    | `/me`                                  | own profile |
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

### write (editor or admin)

| Method | Path                                        | Why |
|--------|---------------------------------------------|-----|
| POST   | `/upload`                                   | creates an asset |
| POST   | `/import`                                   | creates an asset from a URL |
| POST   | `/import/project`                           | import a URL into a new or existing project (one step) |
| POST   | `/import/inspect`                           | no mutation, but an outbound-fetch oracle (URL in, remote response out) |
| POST   | `/import/zip/entries`                       | same: outbound fetch, no mutation |
| POST   | `/import/zip`                               | creates assets from a zip |
| POST   | `/asset/{asset_id}/files`                   | uploads a supporting file |
| DELETE | `/asset/{asset_id}/files/{file_id}`         | deletes a supporting file |
| PATCH  | `/asset/{asset_id}/files/{file_id}`         | renames a supporting file (display only; the bytes never move) |
| PUT    | `/asset/{asset_id}/files/order`             | rewrites the supporting-file display order |
| DELETE | `/asset/{asset_id}/prepared-print`          | deletes a prepared print |
| POST   | `/asset/{asset_id}/thumbnail-generated`     | writes a thumbnail |
| POST   | `/assets/batch/tags`                        | bulk tag mutation |
| POST   | `/assets/batch/folder`                      | bulk move |
| POST   | `/assets/batch/delete`                      | bulk delete (to trash; confirmed by item count) |
| POST   | `/assets/batch/meta`                        | bulk creator/notes metadata edit |
| POST   | `/asset/{asset_id}/tags`                    | metadata mutation |
| POST   | `/asset/{asset_id}/meta`                    | metadata mutation (may rename on disk) |
| POST   | `/asset/{asset_id}/rename`                  | rename on disk |
| DELETE | `/asset/{asset_id}`                         | delete an asset (to trash; the file name must be confirmed) |
| POST   | `/folders`                                  | create a folder |
| PATCH  | `/folder/{folder_id}`                       | rename/move/retag a folder |
| DELETE | `/folder/{folder_id}`                       | delete a folder (to trash) |
| POST   | `/asset/{asset_id}/folder`                  | move an asset into a folder |
| POST   | `/projects`                                 | create a project (a row set, no files) |
| PATCH  | `/project/{project_id}`                     | rename / describe / set the cover of a project |
| DELETE | `/project/{project_id}`                     | delete a project and its memberships (never an asset) |
| POST   | `/project/{project_id}/assets`              | add project memberships |
| DELETE | `/project/{project_id}/assets`              | remove project memberships (the one DELETE with a JSON body) |
| POST   | `/library/scan`                             | starts a scan: registers files found on disk and refreshes `missing_since`; audited as `library.scan.start` |

### admin (administrators only)

| Method | Path                           | Why |
|--------|--------------------------------|-----|
| GET    | `/audit`                       | reading the audit trail is administration |
| GET    | `/settings/mount-import`       | settings namespace is admin-only |
| POST   | `/settings/mount-import`       | mutates settings |
| GET    | `/settings/storage`            | settings namespace is admin-only |
| POST   | `/settings/storage`            | storage template governs every future upload |
| POST   | `/users`                       | user administration |
| GET    | `/users`                       | user administration |
| PATCH  | `/users/{user_id}`             | user administration (including role changes) |
| POST   | `/trash/purge`                 | destroying deleted data is irreversible |

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
  "File grants" above).
* **Break-glass admin**: the env credentials authenticate as the `admin` role -
  but only while the users table is **empty**. The first `POST /users` revokes
  the break-glass sessions in the same transaction as the insert, and after that
  the env credentials are refused. This is why the last-admin invariant below is
  enforced in code rather than relying on an escape hatch.
* **Auth disabled**: `auth.require_auth` returns `None` and
  `permissions.authorize` treats `None` as "no authentication on this
  deployment", so every route stays open exactly as it was before authorization
  existed. `/login`, `/refresh` and `/logout` answer 503 in that mode, and so do
  `/me` and the `/users` routes.

## Changing roles and accounts

`PATCH /users/{user_id}` (admin only):

* body: `{"disabled": true|false}` and/or `{"role": "admin"|"editor"|"viewer"}`;
  unknown fields are rejected (`extra="forbid"`);
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
  because every client polls the status. A viewer clicking the same "Re-scan"
  action still gets a 403: starting a scan is not a viewer action.
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
* **Editors act on every asset.** There is no per-asset ownership in this
  ticket; Mf-arm6 owns that, and it will need a per-record check inside the
  handlers (the level stays `write`).
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
* **Write surfaces are gated client-side as of Mf-3r90.** The write capability
  is `roleAtLeast(role, "editor")` (`lib/auth.ts`), derived once in
  `ui/App.tsx` from the same `/me` role cache and threaded down as a
  **required** `canWrite` prop to `ui/UploadBar.tsx`, `ui/asset-grid/*`
  (including `AssetCard` and `useAssetDrop`), `ui/BulkActionBar.tsx`,
  `ui/ProjectView.tsx`, `ui/ProjectLanding.tsx`,
  `ui/project-attach/useAttachDrop.ts`, and `ui/UploadQueuePanel.tsx` is
  rendered by `App` only when the capability is present (its only action is a
  retry, which is a write). `ui/Sidebar.tsx`
  and `ui/settings/Settings.tsx` keep receiving `role` and derive the same
  capability internally, so there is one threshold in one helper rather than a
  second comparison per surface. `role` is `null` until `/me` answers, so an
  unknown role has no write access (fail closed), and a demotion lands on the
  next `/me` refresh.
  A viewer loses the upload bar, drag-and-drop upload, folder
  create/rename/delete, asset edit/tags/move/delete/add-to-project, per-file
  mutation/re-scan/forget, the bulk write actions, project
  edit/delete/cover/attach/remove-member, the local folder-scan card and the
  upload-queue panel. A viewer keeps search, sort and filters, breadcrumbs,
  subfolder tiles, downloads (including folder ZIP export), preview, the
  slicer, project browsing, the read-only mount-import run history and the
  cookie preferences (client-side settings, not API writes). The upload-queue
  panel is gated too because its only action is a retry: a queued upload still
  running when the role drops would otherwise leave a visible control whose
  click answers with a raw 403.
  The client is still not the boundary: a stale or tampered role cache only
  hides or shows a button, it cannot change what the API allows.
* **No direct-visit not-permitted state is needed for the WRITE surfaces.**
  There is no client router and no write-only view or route, so there is
  nothing to visit directly: the only mixed section is Settings → Imports,
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
* Mf-4c24 - OIDC / external identity.
* Mf-lg02 - MFA.
* Mf-7op4 - session UI (device list, revoke-this-session).

## Migrations

None. `users.role` and `users.disabled` already exist (migration 005); this
ticket adds enforcement and the mutation path, not schema.

Migration 006 (`audit_events`) belongs to Mf-s3z0 and adds no permission column;
it is described in [`AUDIT.md`](AUDIT.md).
