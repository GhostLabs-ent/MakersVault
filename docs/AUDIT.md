# Audit log (Mf-s3z0)

MakerVault records every destructive, administrative and identity-changing action
in one append-only table. The table is the record; the API is the only writer.

## What it is

One mechanism, in three parts:

| Part | Where | What it does |
|---|---|---|
| one table | `audit_events`, created by migration 006 (`makervault/api/migrations.py`, `_migration_006_audit_log`) | every row is one action on one target, never updated or deleted |
| one emission point | `audit.stage(session, ctx, *events)` in `makervault/api/audit.py` | adds the row(s) to the mutation's own session; the caller commits |
| one drift guard | `audit.assert_audit_coverage()` in `main.lifespan` | refuses to boot when a mutating route is neither audited nor exempt with a reason |

`audit.record(*events, ctx=...)` is the second emission function and exists for
exactly two actions whose effect is outside the database (`trash.purge`,
`library.scan.start`); it opens its own session and commits. There is no third
way to write a row.

**The emission point is the action site, not `permissions.authorize()`.**
Authorization and events are different facts. `permissions.authorize()` decides
who may call a route: it runs before the mutation, has no target, and cannot see
what changed or whether the request succeeded. An event says what happened to
which target, and only the handler or service that performed the mutation knows
that. `authorize()` therefore stays the single *authorization* choke point and
emits nothing; the coverage table below plus `assert_audit_coverage()` is what
keeps a future route from escaping the log.

Files involved:

| File | Role |
|---|---|
| `makervault/api/audit.py` | taxonomy, `ROUTE_ACTIONS`, `EXEMPT_ROUTES`, `stage`, `record`, `list_events`, the drift guard |
| `makervault/api/request_id.py` | one request id per request (`X-Request-ID` middleware) |
| `makervault/api/models.py` | `AuditEvent`, describing the migration-created table (no `create_all` in this codebase) |
| `makervault/api/schemas/audit_log.py` | `AuditEventOut`, `AuditListOut` |
| `makervault/api/main.py` | `GET /audit`, the lifespan guard, and the emission call sites |
| `makervault/web/src/ui/AuditLog.tsx` | the admin view behind the sidebar "Audit log" button |

## Why migration 6 was needed

The log is a new persistent store. No existing table carries these columns -
`Asset`, `Folder`, `AssetFile`, `User`, `UserSession` and `AppConfig` all describe
current state, not history - and `schema_migration` is the only ledger in this
codebase, so the only honest way to add a table is a new immutable version.
Migrations 1-5 are untouched; 006 is appended to `MIGRATIONS`.

`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS` and
`CREATE TRIGGER IF NOT EXISTS` are used for every object, so applying 006 to a
database that already has these objects is harmless: it changes nothing that
exists. The ledger is what normally prevents a second application (the runner
skips a version already recorded in `schema_migration`, which is why
`python -m migrations` on an already-migrated database is a no-op); `IF NOT
EXISTS` covers the state the ledger cannot describe - objects present, ledger row
missing - so a partially or hand-applied schema cannot turn a recoverable state
into a boot failure. `tests/test_migration_006.py::test_migration_006_is_idempotent`
asserts both: a second `run_migrations` and a direct `migration.apply` leave the
rows and triggers unchanged.

There is no backfill: nothing happened before the log existed that the database
could honestly reconstruct.

## The action taxonomy

`audit.ACTIONS` holds exactly these 21 strings. Action names are stable and
`namespace.verb`; a reader of a row does not need the code to know what it means.

| Action | Route(s) that emit it | `target` | `detail` | Failure |
|---|---|---|---|---|
| `asset.delete` | `DELETE /asset/{asset_id}`; `POST /assets/batch/delete` (one row per asset) | asset id | `{"filename"}` | fail-closed |
| `asset.rename` | `POST /asset/{asset_id}/rename`; `POST /asset/{asset_id}/meta` (only when the name changes) | asset id | `{"from", "to"}` names | fail-closed |
| `asset.move` | `POST /asset/{asset_id}/folder`; `POST /assets/batch/folder` (one row per asset) | asset id | `{"folder_id"}` (new folder, or `null` for the root) | fail-closed |
| `asset.file.delete` | `DELETE /asset/{asset_id}/files/{file_id}` | asset id | `{"file_id", "filename"}` | fail-closed |
| `asset.file.rename` | `PATCH /asset/{asset_id}/files/{file_id}` (only when the name changes) | asset id | `{"file_id", "from", "to"}` names | fail-closed |
| `asset.file.reorder` | `PUT /asset/{asset_id}/files/order` (only when the order changes) | asset id | `{"order"}` - the file ids in their new order | fail-closed |
| `asset.prepared_print.delete` | `DELETE /asset/{asset_id}/prepared-print` | asset id | none | fail-closed |
| `folder.delete` | `DELETE /folder/{folder_id}` | folder id | `{"name", "folders", "assets", "bytes"}` counted before the delete | fail-closed |
| `folder.rename` | `PATCH /folder/{folder_id}` (only when the name changes) | folder id | `{"from", "to"}` names | fail-closed |
| `folder.move` | `PATCH /folder/{folder_id}` (only when the parent changes) | folder id | `{"from", "to"}` parent ids | fail-closed |
| `project.delete` | `DELETE /project/{project_id}` | project id | `{"name"}` | fail-closed |
| `project.rename` | `PATCH /project/{project_id}` (only when the name changes) | project id | `{"from", "to"}` names | fail-closed |
| `trash.purge` | `POST /trash/purge` | `"trash"` | `{"purged", "bytes", "failed"}` from `trash_service.purge()` | fail-loud |
| `settings.storage.update` | `POST /settings/storage` | `"storage_path_template"` | `{"from", "to"}` templates | fail-closed |
| `settings.mount_import.update` | `POST /settings/mount-import` | `"mount_import"` | `{"enabled", "copy_files"}` | fail-closed |
| `user.create` | `POST /users` | new username | `{"role", "user_id"}` | fail-closed |
| `user.role_change` | `PATCH /users/{user_id}` (only when the role changes) | username | `{"from", "to"}` roles | fail-closed |
| `user.disable` | `PATCH /users/{user_id}` (only when `disabled` goes false -> true) | username | `{"from", "to"}` booleans | fail-closed |
| `user.enable` | `PATCH /users/{user_id}` (only when `disabled` goes true -> false) | username | `{"from", "to"}` booleans | fail-closed |
| `library.scan.start` | `POST /library/scan` | `"library"` | none | fail-loud |
| `login.succeeded` | `POST /login` | the real username | `{"kind", "client_ip"}` | fail-closed |

Two routes can emit more than one row per request, because a request can change
more than one fact:

* `PATCH /users/{user_id}` - one row per changed field. Changing role and
  disabling in the same request writes `user.role_change` and `user.disable`.
* `PATCH /folder/{folder_id}` - renaming and reparenting in the same request
  writes `folder.rename` and `folder.move`. Tags are not audited (see below), so
  a tags-only PATCH writes nothing.

`detail` is small JSON written with sorted keys and rendered as an object by
`GET /audit`. It never holds a secret.

## Audited vs exempt routes

The rule `assert_audit_coverage()` enforces: **every route in
`permissions.ROUTE_PERMISSIONS` whose method is not `GET` must be in
`ROUTE_ACTIONS` or in `EXEMPT_ROUTES` with a non-empty reason.** `GET` routes are
out of scope by construction: they change nothing. The matrix has 64 routes, 24
of them `GET`; the remaining 40 split into 21 audited keys and 19 exempt keys.

The guard also refuses stale keys (an entry for a route that no longer exists), a
key in both tables, an action that is not in `ACTIONS`, and an exemption without
a reason. It collects every problem and raises one `RuntimeError`, so a single
startup line shows the whole drift.

Exempt routes and why:

| Route | Reason |
|---|---|
| `POST /upload` | creates an asset; not destructive or administrative |
| `POST /import` | creates an asset from a URL |
| `POST /import/project` | creates a project and imports files from a URL |
| `POST /import/inspect` | outbound fetch, no mutation |
| `POST /import/zip/entries` | outbound fetch, no mutation |
| `POST /import/zip` | creates assets from a zip |
| `POST /asset/{asset_id}/files` | uploads a supporting file |
| `POST /asset/{asset_id}/thumbnail-generated` | derived cache artifact |
| `POST /asset/{asset_id}/tags` | metadata edit; rename and move are the audited edits |
| `POST /assets/batch/tags` | metadata edit; rename and move are the audited edits |
| `POST /assets/batch/meta` | creator/notes metadata edit; rename and move are the audited edits |
| `POST /folders` | creates a folder |
| `POST /projects` | creates a project |
| `POST /project/{project_id}/assets` | membership edit; deletes no files or asset rows |
| `DELETE /project/{project_id}/assets` | membership edit; deletes no files or asset rows |
| `POST /refresh` | session-token bookkeeping; the abusable surface is `POST /login` |
| `POST /logout` | session-token bookkeeping |
| `POST /download/zip` | streams a temp zip; stores nothing |
| `POST /file-grants` | mints a short-lived read-only file grant; mutates nothing |

The classes behind those rows: **creation** (an upload, an import, a new folder -
the object that gets created can be destroyed later, and that destruction is what
is recorded), **derived artifacts** (a thumbnail is a cache; losing it costs a
regeneration), **outbound fetch** (the two `/import` inspectors read a remote URL
and write nothing), **metadata that is not rename or move** (tags are a label
list, not identity or location), **session-token bookkeeping** (`/refresh` and
`/logout` rotate or revoke a token; the surface worth watching is the credential
check on `POST /login`), and **credential minting** (`/file-grants` signs a
60-second read-only URL for one existing file; it writes no row, changes no row
and grants nothing a viewer could not already read).

## A request that changes nothing writes nothing

The log records what happened, not what was asked. These requests return success
and write no row:

| Request | Why no row |
|---|---|
| rename to the name the asset already has | nothing changed |
| move an asset to the folder it is already in | nothing changed |
| `PATCH /users/{user_id}` re-sending the current role | nothing changed |
| `PATCH /users/{user_id}` re-sending the current `disabled` value | nothing changed |
| `PATCH /folder/{folder_id}` that changes only tags | tags are an exempt metadata class |
| `PATCH /project/{project_id}` that changes only the description, the cover, or the provenance fields (`creator`, `source_url`, `licence`, `licence_url`) | none of them is a rename |

The services compare against the pre-change values they already hold
(`asset_service.move_asset_to_folder_by_id` compares `folder_id`,
`folder_service._stage_folder_changes` compares name and parent, the
`PATCH /users/{user_id}` handler snapshots the row before `accounts.update_user`)
and stage zero events when nothing differs.
`tests/test_audit_log.py::test_no_op_requests_write_nothing` pins the rename,
move, same-role and tags-only cases.

## Failure semantics

An audit write must never be silently swallowed. The mechanism differs by whether
there is a row to roll back.

**Fail-closed: every row-mutating action.** The audit row is inserted into the
same session as the mutation and committed with it, so the row set and its audit
row are one atomic fact. If the insert or the commit fails, the whole transaction
rolls back: the mutation did not happen and the caller gets an error. This is not
a new rollback path - the existing undo logic already fires on any commit
failure:

| Site | Undo that runs on a failed commit |
|---|---|
| `main.py` rename / `POST /asset/{asset_id}/meta` | `asset_service.restore_moved_file` puts the renamed bytes back |
| `asset_service.move_asset_to_folder_by_id` | `restore_moved_file` undoes the cross-folder move |
| `folder_service.move_folder` | `os.rename(target, source)` undoes the directory move |
| `trash_service.trash_folder` | `_undo_moves` reverses every move into `.trash`, then 500 |
| `trash_service.trash_asset` | `_undo_moves` reverses the primary-file and sidecar moves, `_prune_empty_entry` removes the emptied entry, then 500 |

Batch delete is fail-closed per asset: the failed item lands in the response's
`failed` list, its row and its bytes survive, so one broken item does not
silently vanish and its neighbours are not rolled back.

**Fail-loud: `POST /trash/purge` and `POST /library/scan`.** Both destroy or
launch something that carries no database row, so there is nothing to roll back.
`audit.record` writes immediately after the action and raises on failure, after
`log.exception`; the caller gets a 500 and the log line names the action that
could not be recorded. The bytes/scan are already gone/started at that point - see
the residual windows below.

`tests/test_audit_log.py` injects a failure at the single insert seam
(`audit._add`) and asserts each of these: the asset row still exists after a
failed delete, the batch response reports the failure per asset, purge returns
500 and logs, and a failed login leaves no session row behind.

### Residual windows

The database is the authority; the filesystem is best-effort with existing undo.
These windows existed before the audit log and are neither widened nor fixed by
it. They are listed so nobody assumes more atomicity than there is.

* **`AssetFile` rows deleted before the asset row (`cleanup_asset` only).**
  `asset_service.cleanup_asset`, the failed-upload path, calls
  `delete_all_asset_files` in its own session first, then deletes the asset row
  in a second transaction. The user-facing delete no longer has this window:
  `trash_service.trash_asset` deletes the `AssetFile` rows, the asset row and
  the audit row in one transaction.
* **A filesystem rename or move precedes the commit.** The bytes move before
  `session.commit()` on every rename/move route. A commit failure (audit
  included) is undone by `restore_moved_file`, `os.rename` or `_undo_moves`, and
  those undos are themselves best-effort and logged rather than raised: a crash
  in that window leaves disk and rows out of sync. The asset-move undo is itself
  no-clobber (it uses the same link-first primitive as the move). If the vacated
  old path has been claimed in that window, the undo leaves the bytes at the new
  path and logs rather than overwriting, so the row may point at the old name
  while the bytes sit at the new one. The folder-move forward rename maps a
  destination that appears after its pre-check to the standard 409 (POSIX
  `ENOTEMPTY`/`ENOTDIR`, Windows `EEXIST`); POSIX may still replace an existing
  *empty* destination directory without an error, which cannot lose bytes and is
  caught at the record level by the unique `storage_path` index.
  `folder_service.move_folder`'s commit-failure undo `os.rename(target, source)`
  has the same theoretical clobber window and is deliberately not changed here.
* **Post-commit cleanup is best-effort.** In `trash_service.trash_asset` and
  `trash_service.trash_folder` the thumbnail unlink and the emptied-directory
  `rmdir` run after the commit, each `except OSError: pass`. Bytes and
  thumbnails can therefore outlive their rows, and an emptied directory can be
  left behind. The audit row records the authoritative row deletion, which did
  happen.
* **The purge/scan window.** For `POST /trash/purge` the bytes are removed before
  the audit row is written; for `POST /library/scan` the background thread is
  already running. If the audit write then fails, the action happened and is not
  in the log. The response is a 500 and the failure is logged, so the gap is
  visible rather than silent.

## The `IntegrityError` -> 409 caveat

The rename and move paths translate a commit-time `IntegrityError` into a 409
"storage path already exists" (`main.py` rename and `POST /asset/{asset_id}/meta`,
`asset_service.move_asset_to_folder_by_id`, `folder_service.move_folder`). An
`IntegrityError` raised by the *audit* insert would be caught by the same handler
and reported as a misleading 409.

It is near-impossible: the audit primary key is a server-generated `uuid4` and
the table has no other unique constraint, so the insert cannot collide. It is
documented rather than hidden, and it has one consequence for tests: failure
injection raises a generic `Exception` (`tests/test_audit_log.py::explode`),
never an `IntegrityError`, so the test exercises the rollback path and not the
conflict classifier.

## Append-only enforcement

Two SQLite triggers, created by migration 006, are the guarantee:

```sql
CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
```

This is enforced by the database, not by the convention that no helper updates or
deletes a row: `audit.py` exposes no update or delete function, and a
`tests/test_audit_log.py` assertion pins that public surface, but the triggers are
what hold when someone writes SQL by hand.
`tests/test_migration_006.py::test_audit_events_are_append_only` asserts that both
`UPDATE` and `DELETE` raise `IntegrityError` and that the row is unchanged
afterwards.

What that means for the tests: rows cannot be truncated between tests. Audit
assertions are therefore scoped by request id - the client sends
`X-Request-ID` and the test looks up the rows carrying that value - so a shared,
growing table does not make them order-dependent. `tests/test_audit_log.py` says
so in its module docstring and never cleans up.

Surviving gap, stated plainly: a DBA with raw file access can open the SQLite
file, drop the triggers and edit history. Append-only here means "no code path
and no SQL statement issued through this application can rewrite the log".

## Who is recorded

`audit.context_for(request, context)` derives the actor from the request and
never raises. Three modes:

| Mode | `actor` | `actor_user_id` | `actor_role` | `actor_kind` |
|---|---|---|---|---|
| password login | the real `User.username` from the live session row (`auth.AuthContext`) | the user id | the role in force for this request (`sessions.role_for`) | `password` |
| break-glass env admin | the `AUTH_USERNAME` value | `NULL` | `admin` | `break-glass` |
| authentication disabled | `local` (`audit.ACTOR_DISABLED_USERNAME`) | `NULL` | `auth-disabled` | `auth-disabled` |

`actor` and `actor_role` are denormalised copies taken at write time, for the
same reason `sessions.username` is: the row is a historical record and must still
read correctly after the account is renamed, re-roled or deleted. `actor_role` is
what the actor was allowed to do when they did it, not what they are now - a join
to `users` would silently rewrite history.

Authentication disabled is a deliberate deployment mode, not a bypass: it must
keep working, so `context_for` returns the fixed `local` principal instead of
failing, and `GET /audit` answers 200 in that mode like every other route
(`tests/test_audit_log.py::test_auth_disabled_records_local_and_never_500s`).

**No secret is ever written.** No password, access token, refresh token, cookie
or hash reaches `actor`, `target` or `detail`: `login.succeeded` records the
username, the login kind and the client IP, and nothing from the request body.
The do-not-log list is
`makervault/docs/MakersVault_v5.1_Security_Analysis.md` section 9 ("Audit
Logging"): passwords, JWTs, session cookies, MakerWorld cookies, Thingiverse
cookies, MFA secrets, recovery codes.

## Request ids

`makervault/api/request_id.py` assigns one id per request, before any route
dependency runs, and echoes it back.

| Property | Behaviour |
|---|---|
| header | `X-Request-ID` |
| accepted value | `^[A-Za-z0-9._:-]{1,64}$` |
| absent | `uuid.uuid4().hex` (32 lowercase hex characters) is generated |
| hostile | a value that does not match - junk, spaces, 500 characters, a control byte, non-ASCII - is replaced by a generated id |
| echo | always set on the response, including 4xx and 5xx |
| browser access | `X-Request-ID` is in the CORS `expose_headers` list, so client JavaScript can read it |
| storage | `scope["state"]["request_id"]`, read back by `request_id.get(request)` (`"-"` only if the middleware never ran) |

It is a pure ASGI middleware (`RequestIDMiddleware`, added in `main.py` next to
the CORS middleware) rather than a per-route dependency, because it has to cover
every route including the public ones - `POST /login` has no permission
dependency and is one of the actions being audited. The header is untrusted
input: a client cannot choose what lands in the table or the logs.

Every row carries `request_id` plus `method` and `path` (`request.url.path`, the
resolved path with real ids, not the route template), so a row ties back to one
HTTP request. To investigate, take the `X-Request-ID` from the browser's network
panel or from a user's bug report and search the table for it - `GET /audit` has
no request-id parameter, so narrow with `actor`, `target` or a `since`/`until`
window and read the `request_id` column, or query `audit_events` directly with
SQLite. One request that changes two facts writes two rows sharing one request
id - that is how a role change plus a disable in one PATCH is read back as one
request.

## Reading the log

`GET /audit`, admin only (`permissions.ADMIN`; reading the audit trail is
administration).

| Parameter | Type | Semantics |
|---|---|---|
| `actor` | string | exact match, case-insensitive (both sides lowered, value stripped) |
| `action` | string | exact match, case-sensitive - one of the 21 names above |
| `target` | string | case-sensitive substring match; `%`, `_` and `\` are escaped, so it is a literal substring |
| `since` | string | `created_at >= value` |
| `until` | string | `created_at <= value` |
| `limit` | int, 1..200, default 50 | page size |
| `offset` | int, >= 0, default 0 | page start |

`created_at` is ISO-8601 UTC written by Python with microsecond precision
(`2026-01-31T12:00:00.123456+00:00`), and the date bounds are compared
lexicographically against that string - which is why the format is fixed. A bare
`YYYY-MM-DD` is widened to the whole UTC day (`since` -> `T00:00:00`, `until` ->
`T23:59:59.999999+00:00`), which is what the web filter's `<input type="date">`
sends. Any other value is compared as given, so pass UTC: a `Z` suffix or a
non-UTC offset is not converted and does not order the same way as the stored
`+00:00` strings.

Results are newest first (`created_at DESC, id DESC` - the id breaks ties between
rows written in the same microsecond). The response is
`{"events": [...], "total": N, "limit": L, "offset": O}`; `total` is the count of
all rows matching the filters, ignoring paging, so a client can paginate from it.
Each event carries every column except `detail_json`, plus `detail` parsed from
that JSON (`null` when the action recorded none).

`tests/test_audit_log.py::test_admin_view_filters_page_and_sorts_newest_first`
covers the filters, paging and ordering;
`::test_the_view_rejects_editor_viewer_and_anonymous` covers 403 for editor and
viewer and 401 for anonymous.

**The web client is not the security boundary.** As of Mf-5tyz the client holds
the role `/me` last reported (`makervault/web/src/lib/auth.ts`,
`ui/useSessionRole.ts`), so the sidebar "Audit log" entry and the admin-only
settings entries are hidden below `admin` and a direct visit to the audit view
renders a not-permitted state (`ui/NotPermitted.tsx`) instead of the raw 403.
That is honesty, not enforcement: the API answers 403 "Administrator access
required" and remains the control, `AuditLog.tsx` keeps its inline 403 handling
as the race handler, and the role cache is only a cache - a stale or tampered
value can hide or reveal a button but cannot change what the API allows. Write
surfaces are gated the same way as of Mf-3r90: `roleAtLeast(role, "editor")` is
derived once in `ui/App.tsx` and threaded down as a required `canWrite` prop,
`role === null` fails closed until `/me` answers, and the upload-queue panel is
gated too because its only action is a retry - that closes the demotion-race
path where a queued upload still running when the role drops leaves a visible
control that answers with a raw 403.

## Scope and follow-ups

* **`login.succeeded` only.** Failed logins are not audited in this ticket. The
  failure path is already throttled (`login_throttle`) and logs loudly with the
  username and client IP, and writing a row before a 401 would make an audit
  failure a 500 on the *rejection* path. A `login.failed` action is the obvious
  follow-up, not something forgotten.
* **No per-record ownership.** Every actor can act on every asset until Mf-arm6
  lands; the audit row records who did it, not who was allowed to.
* **No export, no retention policy.** Nothing rotates, archives or prunes audit
  rows in this ticket; the append-only triggers refuse deletion by design.
* **No log for reads.** Only mutations and identity events are recorded; who
  looked at what is not part of this ticket.
* **`GET /audit` is the only new route**, and the only place the log is read.
