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
| Bulk tag / move / delete                     |  yes  |  yes   |   no   |
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

`require_read` / `require_write` / `require_admin` wrap `auth.require_auth`
(unchanged: same `?token=` fallback, same 401s) and then call
`permissions.authorize(request, context, level)`, which raises 403 when the
principal's role does not reach the level. The declaration *is* the enforcement:
there is no second place to look for a permission check.

Because a per-route dependency is easy to forget, `ROUTE_PERMISSIONS` in the same
module records the audited matrix, and `assert_routes_classified(app)` proves the
two agree. It runs in `main.lifespan` **before** migrations and before the
server accepts connections, so a route that ships without a level - or with a
level the matrix does not expect - fails the boot instead of failing open. The
same function is called from the tests, and the permission sweeps
(`tests/test_permissions_matrix.py`) are parametrised from `ROUTE_PERMISSIONS`,
so the table that documents the rules is the table the tests enforce.

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

## The route matrix

Paths are FastAPI templates exactly as declared. 58 routes: 4 public, 18 read,
27 write, 9 admin.

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
| GET    | `/asset/{asset_id}/prepared-print`      | download a prepared print |
| GET    | `/thumb/{asset_id}.jpg`                 | thumbnail |
| GET    | `/assets`                               | list assets |
| GET    | `/tags`                                 | list tags |
| POST   | `/download/zip`                         | POST-for-download: it builds a temp zip and streams it, nothing is stored |
| GET    | `/folders`                              | list folders |
| GET    | `/folder/{folder_id}/delete-preview`    | pure SELECT that counts what a delete would remove |
| GET    | `/folder/{folder_id}/download`          | download a folder as a zip |
| GET    | `/projects`                             | list projects with their member counts |
| GET    | `/project/{project_id}/assets`          | list one project's member assets |
| GET    | `/trash`                                | list the trash |

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
| DELETE | `/asset/{asset_id}/prepared-print`          | deletes a prepared print |
| POST   | `/asset/{asset_id}/thumbnail-generated`     | writes a thumbnail |
| POST   | `/assets/batch/tags`                        | bulk tag mutation |
| POST   | `/assets/batch/folder`                      | bulk move |
| POST   | `/assets/batch/delete`                      | bulk delete (to trash; confirmed by item count) |
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
  needs a bearer token; `require_auth` re-reads the session row and the account
  on every request, so a revoked session or a disabled account stops working
  immediately.
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
* **Settings reads are admin**, so an editor opening the Settings panel sees
  "Failed to load storage settings." rather than a populated form. That is
  honest: they cannot change it either.
* **Editors act on every asset.** There is no per-asset ownership in this
  ticket; Mf-arm6 owns that, and it will need a per-record check inside the
  handlers (the level stays `write`).
* **The web client** maps a 403 to "Your role does not allow this action."
  (`lib/api.ts`, `assertOk`). Nothing else in the UI is role-aware yet.
* **Audit.** Every audited action now writes one row (one per affected asset on
  the batch routes) in the same transaction as the mutation, so an audit write
  failure is a failed mutation - fail-closed, except for the two filesystem-only
  actions (`trash.purge`, `library.scan.start`), which are fail-loud. That costs
  one insert per audited action and grants nothing new: the actor is the
  principal the request already carried, or `local` when auth is disabled.
  `GET /audit` is an admin read, and the sidebar "Audit log" button is visible to
  every signed-in user while the API answers 403 - the client is not the
  security boundary. Details in [`AUDIT.md`](AUDIT.md).

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
