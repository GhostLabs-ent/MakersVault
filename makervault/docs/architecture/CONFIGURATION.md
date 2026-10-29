# MakersVault Configuration Inventory

**Baseline:** Gate 0, 2026-08-13

This inventory records configuration ownership. It does not replace the secure
deployment guidance required by Gate 1.

## Canonical deployment files

| Use | File |
|---|---|
| Local source build | `makervault/docker-compose.yml` |
| Production images | `makervault/docker-compose.deploy.yml` |
| Historical production alias | `makervault/docker-deploy.yml` |
| API example environment | `makervault/api/.env.example` |

The production manifest forwards every operator-tunable setting listed below
with the code default as its `${VAR:-default}` fallback, so overriding a
variable in `.env` is enough to change it. The deliberate exceptions are
disclosed in the rows below: `ASSET_FILE_MAX_MB` is forwarded empty so it keeps
following `IMPORT_MAX_MB` (the cap in force is the smaller of the two), the
deprecated `AUTH_TOKEN_TTL` is not forwarded at all because it is a no-op, and
the `SNAPSHOT_BTRFS_SIDECAR_*` keys are forwarded nowhere because they belong to
the opt-in sidecar and its override, not to the shipped manifests. The guard
that keeps these forwards and fallbacks honest is
`makervault/api/tests/test_deploy_manifest_env.py`.

## API and container settings

| Variable | Current default | Owner and effect |
|---|---|---|
| `PUID`, `PGID` | `1000` | API entrypoint; runtime file ownership. |
| `CHOWN_MODE` | `minimal` | API entrypoint; `recursive` opts into a full data-tree ownership repair. |
| `FILE_STORAGE` | `./storage` in code; `/app/storage` in Compose | Managed primary, thumbnail, and bundle root. |
| `DB_URL` | `sqlite:///./app.db` in code | SQLAlchemy database URL; Compose uses `/app/data/app.db`. |
| `AUTH_USERNAME` | `admin` | Username of the break-glass admin, accepted only while the users table is empty, so a real user account always disables it. |
| `AUTH_PASSWORD` | `super-secret` | Single-admin bootstrap secret; the API refuses to start while this published sample value is still active. |
| `AUTH_SECRET` | `changeme-secret` | JWT signing secret; the API refuses to start while this published sample value is still active. |
| `AUTH_ALLOW_INSECURE_DEFAULTS` | unset (false) | Opts out of the startup guard that refuses the published sample credentials while auth is enabled. |
| `AUTH_ACCESS_TOKEN_TTL` | `900` | Access-token (JWT) lifetime in seconds; the token also stops working as soon as its session row stops being live. |
| `AUTH_REFRESH_TTL_SECONDS` | `2592000` | Refresh-token lifetime in seconds (30 days). Only the sha256 of the opaque token is stored, and rotation is single-use. |
| `AUTH_TOKEN_TTL` | ignored | Deprecated no-op kept so an old `.env` still starts; the value does nothing. |
| `PUBLIC_URL` | empty | Public browser origin; also allows web runtime API derivation. |
| `CORS_ORIGINS` | derived or localhost | Comma-separated browser origins accepted by API CORS middleware. |
| `API_PORT` | `8000` | Published API port. |
| `WEB_PORT` | `5173` | Published web port. |

## Authentication and sessions

Owned by `api/auth.py` and `api/sessions.py`.

- An access token is a 15-minute HS256 JWT (`AUTH_ACCESS_TOKEN_TTL`, default
  `900` seconds). It carries `sub`, `sid`, `typ=access`, `role`, `username`,
  `iat` and `exp`, but it is not a self-contained identity: `sid` must still map
  to a live `UserSession` row, and role plus disabled state are re-read on every
  request. Signing out or revoking a session sets `revoked_at`, which kills the
  access token on its next use, and a disabled user is locked out immediately.
- A refresh token is an opaque `secrets.token_urlsafe(32)` value of which only
  the sha256 hash is stored. Rotation is single-use per session, and the token
  expires after 30 days (`AUTH_REFRESH_TTL_SECONDS`, default `2592000`
  seconds).
- The `AUTH_USERNAME`/`AUTH_PASSWORD` environment admin is break-glass only: it
  is accepted while the users table is empty, so a real user account always wins
  over the published sample credentials.
- At startup, `validate_auth_configuration()` refuses to run while
  `AUTH_PASSWORD` or `AUTH_SECRET` are still the published sample values, unless
  `AUTH_ALLOW_INSECURE_DEFAULTS` is set. `AUTH_TOKEN_TTL` is deprecated and
  ignored; it is read only so an existing environment keeps starting.

## Login throttle settings

Owned by `api/login_throttle.py` and wired through `api/config.py`. Failures are
counted per submitted username (proxy headers are not trusted); repeated
failures lock the single admin account out with escalating backoff. Empty values
fall back to the defaults below.

| Variable | Current default | Effect |
|---|---|---|
| `LOGIN_THROTTLE_ENABLED` | `true` | Master switch for failed-login throttling. |
| `LOGIN_MAX_FAILURES` | `5` | Failures allowed inside the window before a lockout starts. |
| `LOGIN_FAILURE_WINDOW_SECONDS` | `900` | Rolling window in which failures are counted. |
| `LOGIN_LOCKOUT_SECONDS` | `300` | First lockout duration; later lockouts escalate. |
| `LOGIN_MAX_LOCKOUT_SECONDS` | `3600` | Ceiling for the escalating lockout. |

## Remote import settings

| Variable | Current default | Effect |
|---|---|---|
| `IMPORT_TIMEOUT_SECONDS` | `30` | Remote request time budget. |
| `IMPORT_MAX_REDIRECTS` | `5` | Maximum redirect hops followed while fetching a remote import; each hop is validated before connecting. |
| `IMPORT_MAX_MB` | `512` | Maximum remote response size for link imports, and the per-entry cap for each entry extracted from a zip. |
| `IMPORT_ZIP_MAX_MB` | `2048` | Cumulative expanded-size budget for the entries selected from one zip import. A selection whose declared sizes exceed it is rejected with 413 before anything is written; if an entry understates its size, the whole request is rolled back and rejected once the streamed bytes cross the budget. |
| `MAX_UPLOAD_MB` | `4096` | Direct upload cap enforced by the API; the reverse proxy needs a matching `client_max_body_size`. |
| `ASSET_FILE_MAX_MB` | `IMPORT_MAX_MB` (`512`) | Per-supporting-file cap. The cap in force is the smaller of this and `IMPORT_MAX_MB`, so an existing deployment keeps refusing what it refused before. `0` removes this cap, but `IMPORT_MAX_MB` still applies. |
| `ASSET_FILE_TOTAL_MAX_MB` | `2048` | Total bytes across one model's supporting files. An upload that would cross it is rejected with 413 inside the write transaction, leaving no row and no bytes. `0` disables it. |
| `ASSET_FILE_MAX_COUNT` | `50` | Maximum supporting files on one model. The next upload is rejected with 413; `0` disables it. |
| `IMPORT_HTML_MAX_KB` | `4096` | Maximum resolver HTML size. |
| `MAKERWORLD_COOKIE` | empty | Optional server-side source credential. Browser-provided values are not persisted by the API. |
| `THINGIVERSE_COOKIE` | empty | Optional server-side source credential. Browser-provided values are not persisted by the API. |

Upload bodies are streamed straight into storage: a body lands in
`<storage>/.incoming/<uuid>` and is renamed atomically into its rendered path
once the form fields that shape that path have arrived. Nothing is spooled into
container temp, so a 2 GB upload needs one 2 GB file rather than 2 GB of
scratch. `MAX_UPLOAD_MB` is enforced while the body streams, so an oversize
upload is cut off as soon as the cap is crossed. The generated-thumbnail route
(`POST /asset/{id}/thumbnail-generated`) streams the same way - a staging file
consumed in place - with a fixed 8 MiB cap enforced mid-stream and no
environment knob.

## Mounted import settings

| Variable | Current default | Effect |
|---|---|---|
| `IMPORT_MOUNT_PATH` | empty in canonical production manifest | Container path eligible for scanning. Legacy alias `MOUNT_IMPORT_PATH` is also read by the API. A mount that contains or sits inside the storage root is refused (copy mode tolerates an identical root by registering in place), and the skip is logged at startup. |
| `IMPORT_MOUNT_PATH_HOST` | `./imports` | Read-only host path mounted at `/imports` by production Compose. |
| `IMPORT_MOUNT_EXTS` | built-in supported list | Comma-separated eligible extensions. |
| `IMPORT_MOUNT_INCLUDE_HIDDEN` | `false` | Whether hidden paths are scanned. |
| `IMPORT_MOUNT_ON_STARTUP` | `false` in canonical production manifest | Enables the startup scan. The code default remains `true` when a path is configured, so configuring a mount path is what opts a deployment in. |
| `IMPORT_MOUNT_COPY` | `true` | Copy into managed storage instead of indexing in place. Copy mode mirrors the mount's relative directory structure into the storage root (a mount holding `a/b/c.stl` registers `a/b/c.stl` and the folder chain `a` -> `a/b`); reference mode registers `is_reference` rows that point at the mount and copy nothing. |

Each attempt is recorded in the `import_run` table (status, mode, counters and
bounded per-file errors) and readable at `GET /imports/runs`. The table keeps the
newest 50 runs; skipped runs are recorded too, with their reason.

## Storage snapshot capabilities

`GET /storage/capabilities` reports, per storage volume, the filesystem type and
whether a snapshot method is actually usable. It requires the read permission
(the admin-only storage settings section in the UI mounts the badge, but a
viewer may read the same report). The route is read-only and creates nothing: it
takes no snapshot, writes no probe file and makes no directory.

Each entry has `roles`, `path`, `fstype`, `mount_point`, `snapshot_method`,
`usable` and `reason`. The library volume and the sqlite database directory are
reported separately; when both sit on the same `st_dev` they are merged into one
entry whose `roles` is `["library", "database"]`, because that is one
filesystem. The merged entry is a report, not a promise: `database_directory()`
is called only inside `detect()`, and every provider snapshots the library root
alone. So a library snapshot does **not** cover the SQLite database, even when
the two share a volume -- pair it with a database backup.

`fstype` comes from the `statfs(2)` magic, cross-checked against
`/proc/self/mounts` (longest-prefix match, then `st_dev`). The magics it names are
CephFS `0x00C36400`, Btrfs `0x9123683E`, and ZFS `0x2FC12FC1`, plus ext, tmpfs,
overlay, nfs, cifs, xfs and fuse; anything else reports `unknown`.

`snapshot_method` is one of:

| Method | What it needs |
|---|---|
| `cephfs_snapdir` | `<root>/.snap` must already exist and be writable by the process. The probe never creates it. |
| `zfs_dataset` | the `zfs` binary, the library root as the dataset mountpoint, and delegated `snapshot`, `destroy` and `mount` rights on that dataset. The probe is bounded at 10 s and runs under `LC_ALL=C`, so a translated `zfs allow` listing cannot be misread. |
| `btrfs_subvol` | detected, but taking a snapshot needs `CAP_SYS_ADMIN`, which the API container does not have, so it is reported unusable unless the operator opts into the privileged sidecar described in "Snapshots (BTRFS sidecar)" below. Without that sidecar the method is still detected, the reason names this document, and no socket is opened. |
| `none` | no snapshot method for this filesystem; the reason names the `fstype`. |

The `zfs_dataset` and `btrfs_subvol` answers are not a second opinion: the `zfs`
arm of the report calls `snapshot_zfs.probe_zfs` and the `btrfs` arm calls
`snapshot_btrfs.probe_sidecar`, the same probes the providers use, so what the
badge says and what a create would do are one answer. A state either probe
refuses is therefore never reported `usable`, and its prose reason (the missing
permission, the subdirectory root) travels into the badge.

`os.access` is always true for root, so the CephFS writability check is weakest
for a root container: it reports what the process could do, not what the
deployment's service principal was granted. No snapshot is taken in this slice.

## Snapshot policy settings

S3 (`makervault/api/snapshot_guard.py`) is the slice that takes them. Three
destructive operations ask for a pre-operation snapshot before they mutate
anything: a folder delete (`DELETE /folder/{folder_id}`), a trash purge
(`POST /trash/purge`) and a bulk asset delete (`POST /assets/batch/delete`). A
single-asset delete takes no snapshot: the trash keeps it restorable. Retention
from S2 (`snapshot_keep_last_n`, `snapshot_keep_daily`, `snapshot_max_age_days`,
`snapshot_hard_cap`) still bounds every snapshot these operations create, and it
runs on create with no opt-out.

| Variable | Current default | Meaning |
|---|---|---|
| `SNAPSHOT_POLICY_PREDELETE` | `warn` | Policy for the folder delete. |
| `SNAPSHOT_POLICY_PREPURGE` | `strict` | Policy for the trash purge. |
| `SNAPSHOT_POLICY_PREBULK` | `strict` | Policy for the bulk asset delete. |
| `SNAPSHOT_REQUIRE_CAPABILITY` | `false` | Whether `strict` refuses a volume that has no usable snapshot method. |

Each policy is `warn` or `strict`, validated when `config` is imported: any other
value fails the boot, so a typo cannot leave a policy inert. `warn` proceeds
without a snapshot and reports it; `strict` does the same for an advertised
absence unless `SNAPSHOT_REQUIRE_CAPABILITY=true`. That switch is the point: on
ext4 or tmpfs there is no snapshot method at all, so refusing by default would
make Empty trash impossible on a perfectly ordinary deployment. The absence is
audited either way (`destructive.snapshot_missed`), so "no snapshot was taken"
is a recorded fact rather than a silent one. A real failure while taking a
snapshot is never a capability miss: a path defect, a name collision or a
vanished `.snap` directory is refused under `strict` and reported under `warn`.

## Scheduled snapshots

S8 (`makervault/api/snapshot_schedule.py`) is the slice that takes them on a
schedule. When `SNAPSHOT_SCHEDULE_ENABLED` is true, `main.lifespan` starts one
daemon thread as the last step of the boot sequence, so it is provably after
migrations and after both boot guards. The thread sleeps
`SNAPSHOT_SCHEDULE_START_DELAY_SECONDS`, then ticks every
`SNAPSHOT_SCHEDULE_CHECK_SECONDS`. A tick takes a library snapshot with reason
`scheduled` when the newest scheduled snapshot is older than
`SNAPSHOT_SCHEDULE_HOURS` (and immediately when there is none). It hands S2's
provider a hand-built system audit context, so the provider's own
`snapshot.create` and `snapshot.prune` rows record the work: a successful tick
adds no new audit action.

Retention is read, never re-declared. The thread rebuilds the provider on every
tick, so a retention edit through `POST /snapshots/retention` takes effect
without a restart, and the scheduler itself never issues a delete; retention
runs inside create.

The status surface is `GET /snapshots/schedule` (ADMIN). It reports the last
attempt and its outcome, the snapshot count, the oldest and newest snapshot, a
24-hour count, the retention policy in force, `warnings[]` and a
`database_caveat`. It reports rather than operates: on a volume with no
snapshot method, or with a corrupt stored retention row, it still answers 200
and says so in `warnings[]`. `last_attempt` and `last_outcome` are in-process
and reset on restart; the snapshot names on disk are the durable record.

The one thing an operator must not miss: **a library snapshot covers the
filesystem only and does not cover the SQLite database.** A daily snapshot plus
a database backup is the complete restore story; backup and restore procedure is
Mf-ljld's and is not repeated here.

| Variable | Current default | Meaning |
|---|---|---|
| `SNAPSHOT_SCHEDULE_ENABLED` | `false` | Whether the API starts the scheduled-snapshot thread at boot. |
| `SNAPSHOT_SCHEDULE_HOURS` | `24` | Take a snapshot when the newest scheduled one is older than this many hours. |
| `SNAPSHOT_SCHEDULE_CHECK_SECONDS` | `300` | How often the thread asks whether one is due. |
| `SNAPSHOT_SCHEDULE_START_DELAY_SECONDS` | `60` | Delay before the first tick, keeping it clear of migrations and the boot guards. |

A `SNAPSHOT_SCHEDULE_HOURS` of `0` or less makes every tick due; the retention
policy is what bounds the count.

## Web runtime settings

| Variable | Current default | Effect |
|---|---|---|
| `VITE_API_URL` | empty in production | Browser-reachable API URL written to `runtime-config.js`; source build defaults to localhost. |
| `VITE_ALLOWED_HOSTS` | empty | Vite-only host policy during source development/preview. It does not configure Nginx. |
| `PUBLIC_URL` | empty | When set and `VITE_API_URL` is empty, runtime API URL becomes `<PUBLIC_URL>/api`. |

## Web security header settings

Owned by `web/30-security-headers.sh`, which regenerates
`/etc/nginx/security-headers.conf` at container start and is included by the
Nginx server block and by every location that declares its own `add_header`.
An empty value means "use the built-in default"; the literal value `off` omits
that one header.

| Variable | Current default | Effect |
|---|---|---|
| `SECURITY_HEADERS_ENABLED` | `true` | Master switch. `false` writes an empty header file so no security header is sent. |
| `SECURITY_HEADERS_CONTENT_TYPE_OPTIONS` | `nosniff` | `X-Content-Type-Options` value. |
| `SECURITY_HEADERS_REFERRER_POLICY` | `strict-origin-when-cross-origin` | `Referrer-Policy` value. |
| `SECURITY_HEADERS_FRAME_OPTIONS` | `DENY` | `X-Frame-Options` value. The default CSP also sets `frame-ancestors 'none'`. |
| `SECURITY_HEADERS_PERMISSIONS_POLICY` | `camera=(), microphone=(), geolocation=()` | `Permissions-Policy` value. |
| `SECURITY_HEADERS_HSTS` | `max-age=31536000` | `Strict-Transport-Security` value. No `includeSubDomains`, no `preload` by default. |
| `SECURITY_HEADERS_CSP` | built-in policy | `Content-Security-Policy` value. The built-in policy allows `'self'` plus the origin of an absolute `VITE_API_URL` (or `<PUBLIC_URL>/api`) in `connect-src`. |

Values are validated before they are written into Nginx configuration: a value
containing a double quote, `$`, a backslash, or control characters is rejected
with a `[security-headers]` warning and that header falls back to its default.

The production web image is a static Vite build served by unprivileged Nginx.
Only `web/30-security-headers.sh` (security headers) and `web/40-runtime-config.sh`
(runtime API URL) participate in its runtime configuration. The old Node
development entrypoint is not part of the production image.

## Browser-local settings

The browser stores theme, preview mode, selected slicer/engraver, the network
override, and the import "remember" preference in local storage. The
MakerWorld/Thingiverse session cookie is session-scoped by default (it lives in
the current tab and is forgotten when the tab closes) and is written to local
storage only when the user opts in with "Remember import cookies on this device".
These are per-browser and are not server `AppConfig` values; the optional
`MAKERWORLD_COOKIE`/`THINGIVERSE_COOKIE` variables are process environment, not
`AppConfig`. Gate 1 re-evaluates authentication-token storage separately.

## Server `AppConfig` settings

The current database-backed settings are mounted-import enable/copy behavior, the
managed-storage template, and snapshot retention. These settings are shared by
the instance. Mounted import run history is a table (`import_run`), not an
`AppConfig` value, so it is bounded separately and never parsed as a setting.

Snapshot retention is the policy of the snapshot provider layer. The provider
resolves it once, at construction, and applies it only to the snapshots that
layer wrote, so an edit is picked up by the next provider built -- the scheduler
builds one per tick, which is why an edit takes effect there without a restart.
It does not decide whether a snapshot can be taken (that is the capability
report above) and it adds no environment variable and no schema change; it does
add two routes, `GET /snapshots/retention` and `POST /snapshots/retention`, and
the update is audited as `settings.snapshot_retention.update`:

| Key | Default | Effect |
|---|---|---|
| `snapshot_keep_last_n` | `20` | Always keep the newest N snapshots. |
| `snapshot_keep_daily` | `7` | Also keep the newest snapshot of each of the last N days that has one. |
| `snapshot_max_age_days` | `30` | Prune anything older than N days. |
| `snapshot_hard_cap` | `100` | Prune the oldest until at most N remain. |

The cascade is age, then keep, then hard cap: a snapshot older than
`snapshot_max_age_days` is pruned even when a keep rule would have protected it;
the two keep keys are a union, so the newest `snapshot_keep_last_n` snapshots and
one snapshot per day for `snapshot_keep_daily` days both survive; and the hard cap
is the last resort that bounds the directory. Retention runs inside `create()`
and cannot be switched off. The snapshot being created is never pruned, a name
the layer did not write is never pruned, and the policy refuses what it cannot
honour: `snapshot_keep_daily` is non-negative, the other three keys are positive,
so a refused stored value is an error rather than a silently replaced default.

## Snapshots (ZFS)

`zfs_dataset` (see "Storage snapshot capabilities") is served by
`makervault/api/snapshot_zfs.py`, which drives the `zfs` CLI. It needs no root
privileges: the service principal is given exactly three rights on one dataset
by delegation, and everything else -- naming, retention, containment, listing --
comes from the shared provider layer, so a ZFS deployment behaves like the CephFS
one. Snapshot names are `<UTC stamp>-<reason>-<random suffix>`, used verbatim as
the ZFS snapshot name.

The library root itself must be the dataset mountpoint, not a directory inside a
dataset. A subdirectory has no `.zfs` snapshot view of its own, so there is
nowhere for a snapshot store to live: the provider is still constructed
(construction is probe-free, so nothing fails until work is asked of it), the
first `create()` answers 409, and the probe reports `library_not_mountpoint` so
the capability report says so before an operator ever tries:

```
zfs create -o mountpoint=<library> <pool>/<name>
```

Delegating the rights, as root, once per dataset (the probe's remedy is this
same command with the running user and the resolved dataset filled in):

```
zfs allow -u <user> snapshot,destroy,mount <dataset>
```

`mount` is delegated even though nothing here mounts anything: `zfs destroy`
inspects the dataset's descendants before it removes a snapshot, and that check
fails without it. All three are required; a deployment that grants only
`snapshot` can take snapshots it cannot prune, which the probe reports rather
than discovering at delete time.

One probe answers both. `GET /storage/capabilities` calls
`snapshot_zfs.probe_zfs` -- the standalone, read-only, four-state answer for a
ZFS root -- exactly as the btrfs arm asks its sidecar, so the badge and the
manual procedure below cannot disagree and a state the probe refuses can never
report `usable`. The probe takes no snapshot and creates nothing, and it reports
one of four states:

* `delegated` -- the dataset behind the library root delegates `snapshot`,
  `destroy` and `mount` to this principal. Snapshots can be taken and pruned.
* `available_but_not_delegated` -- the volume is ZFS and the dataset resolves,
  but at least one required permission is missing. The reason names the missing
  permissions and the remedy is the `zfs allow` line above.
* `unavailable` -- the root is not on a mounted volume, is not ZFS, the dataset
  could not be resolved, or `zfs` could not be run at all.
* `library_not_mountpoint` -- the root is a subdirectory of the dataset mounted
  above it; the remedy is the `zfs create -o mountpoint=...` line above.

Two deployment caveats matter in containers:

* `/dev/zfs` must be present in the API container. The `zfs` userspace tool talks
  to the kernel module through that device node; without it every `zfs` call
  fails and the probe reports `unavailable` even on a ZFS host.
* the `snapdir` property controls whether the snapshot directory is listed in a
  plain readdir of the dataset root (`hidden` is the default on most pools, and
  `visible` is the other setting). Snapshot access is unaffected, because
  reading `<root>/.zfs/snapshot/...` by name works either way; only an
  operator's `ls` of the mount point shows the difference.

Browsing is read-only: `<root>/.zfs/snapshot/<name>` is the kernel's view of one
snapshot, and it is never written to. A restore copies out of that view into the
live tree; this module never runs `zfs rollback`, because a rollback rewinds the
whole dataset -- including everything this application did not write -- to the
snapshot's state, which is not a restore of the files somebody asked for.

Only snapshots this application wrote are listed and pruned. `list()` reads the
snapshot view and keeps the names its own parser recognises, so snapshots taken
by `zfs-auto-snapshot`, `sanoid`, a backup job or a cron line are invisible to
the UI and immune to retention even though they live on the same dataset. This
module never enumerates the dataset, so it cannot prune a snapshot it did not
name.

### Real-pool verification (MANUAL)

Delegation, `/dev/zfs` and `snapdir` visibility cannot be exercised without a
real pool, so verifying them is a manual procedure on a real deployment, not CI
evidence. On a host with ZFS, as root, create a scratch dataset mounted on a
temporary library root and delegate the three rights to the service principal:

```
zfs create -o mountpoint=/srv/zfs-check tank/zfs-check
zfs allow -u <user> snapshot,destroy,mount tank/zfs-check
```

Then, as the service principal, check the probe, take a snapshot, browse and
restore it, and delete it. The probe lives in the API tree, so run it from
`makervault/api`; the snapshot name must follow the application's scheme
(`<UTC stamp>-<reason>-<random suffix>`) or the app will not list the snapshot it
creates:

```
cd makervault/api
python -c "import snapshot_zfs; print(snapshot_zfs.probe_zfs())"
zfs snapshot tank/zfs-check@20260101T000000Z-manual-abc123
ls /srv/zfs-check/.zfs/snapshot
cp /srv/zfs-check/.zfs/snapshot/20260101T000000Z-manual-abc123/<file> /srv/zfs-check/<file>
zfs destroy tank/zfs-check@20260101T000000Z-manual-abc123
zfs unallow -u <user> snapshot,destroy,mount tank/zfs-check
zfs destroy tank/zfs-check
```

Expected: the probe reports `delegated`; the snapshot appears both under
`.zfs/snapshot` and in `zfs list -t snapshot`; browsing shows the file contents
as of the snapshot; the copy restores them; the destroy removes the snapshot
without `-r`. A snapshot taken by another tool left on the dataset at the same
time must not appear in the application's snapshot list. Record the run in the
deployment notes; it is operator evidence, not a substitute for the unit tests.

Real-pool verification is manual, and the container's `/dev/zfs` is the first
thing to check when the probe reports `unavailable` on a host that has ZFS.

## Snapshots (BTRFS sidecar)

BTRFS gives an unprivileged process no way to take a snapshot: `btrfs subvolume
snapshot` needs `CAP_SYS_ADMIN`, and the API container deliberately runs without
it. So `btrfs_subvol` (see "Storage snapshot capabilities") is served by a small
opt-in helper container that holds the capability and the library mount, and the
API talks to it over the compose network on port 8765. An empty
`SNAPSHOT_BTRFS_SIDECAR_URL` is the normal, supported state: no sidecar is
configured, and nothing else in the product changes.

With no sidecar configured the app degrades cleanly. `btrfs_subvol` is still
detected as the method for the volume, it is simply not usable, the capability
report's `reason` says so and names this document, and no socket is opened, so a
deployment that never opted in pays nothing for capability detection. The helper
reports one of three states, and the capability report's `reason` uses the same
words:

* `ready` -- the sidecar answered `GET /health` with `"state": "ready"` and
  reports a store this API can read, so the volume reports `btrfs_subvol` usable
  and create, list and delete all go through the sidecar.
* `disabled` -- `SNAPSHOT_BTRFS_SIDECAR_URL` is empty. Nothing is broken: the
  volume reports `btrfs_subvol` unusable and the reason says the sidecar is not
  configured.
* `unreachable` -- the URL is set but the sidecar did not answer, answered with
  a non-2xx status, answered a body that does not say `"state": "ready"`, or
  reported ready while writing a store this API does not read (the two services
  are not sharing the library directory). The reason carries the URL and what
  actually happened, and the fix is on the sidecar or on the two bind mounts,
  not in the API.

The sidecar and the API share the same `snapshots` name scheme, and the store is
the dot-directory `.snap` inside the mount, so the library scan keeps ignoring it
exactly as it ignores CephFS's `.snap` store.

The helper is a separate build (`makervault/snapshot-sidecar`) carrying only
`btrfs-progs` and the two stdlib modules `guard.py` and `server.py`. A clearly
marked example override, opt-in and not part of any shipped manifest:

```yaml
# docker-compose.override.yml -- opt-in BTRFS snapshot sidecar (example)
services:
  api:
    environment:
      FILE_STORAGE: /app/storage
      SNAPSHOT_BTRFS_SIDECAR_URL: http://snapshot-sidecar:8765
      SNAPSHOT_BTRFS_SIDECAR_TOKEN: ${SNAPSHOT_BTRFS_SIDECAR_TOKEN:?the sidecar token is required}
    volumes:
      # The same host directory the sidecar mounts below, at the path the API reads.
      - /srv/makersvault/library:/app/storage
  snapshot-sidecar:
    build: ./snapshot-sidecar
    cap_add:
      - SYS_ADMIN
    cap_drop:
      - ALL
    read_only: true
    environment:
      SNAPSHOT_BTRFS_SIDECAR_TOKEN: ${SNAPSHOT_BTRFS_SIDECAR_TOKEN:?the sidecar token is required}
      SNAPSHOT_BTRFS_SIDECAR_MOUNT: /library
    volumes:
      # The one host path the sidecar may touch: the library subvolume, read-write.
      - /srv/makersvault/library:/library
```

**The invariant that makes this work:** the sidecar's mount and the API's
`FILE_STORAGE` must be the same directory, seen at two paths. The sidecar writes
`<mount>/.snap/<name>` and the provider's `list()` reads `<FILE_STORAGE>/.snap`.
If those are two different directories every symptom is silent: the capability
report says `usable`, every create succeeds, `list()` stays empty, browse,
restore and delete are unreachable, retention can never prune, and a scheduled
snapshot leaves one unprunable subvolume behind per day. `probe_sidecar`
compares the store the sidecar reports on `GET /health` with the store this API
reads, and answers `unreachable` with both paths in the reason when they
disagree. That is why the `api` service appears in the override at all: its
`/app/storage` has to be the host library directory, not the named volume the
shipped manifests give it.

A Docker **named volume** cannot be the store on either side. A named volume is
a plain directory on the host filesystem, not a btrfs subvolume, so
`btrfs subvolume show` fails inside it and the sidecar refuses to boot -- that
command is the only proof that the mount really is the subvolume it is supposed
to be -- and subvolumes created under it would live in the wrong place anyway.
The library has to be a bind mount of a real btrfs subvolume, and it has to be
the same bind mount in both services.

There are deliberately no published ports: the sidecar is reachable only on the
compose network, so nothing outside the deployment can send it a token or a
name. The token is required to boot (the helper exits non-zero when
`SNAPSHOT_BTRFS_SIDECAR_TOKEN` is empty, and compares it in constant time), and
it must be the same value in the API and in the sidecar. `read_only: true` is
the third layer: the container's own filesystem is immutable, so the bind mount
is the only writable path in it, and it is the one library subvolume.

### What the sidecar is allowed to do

`CAP_SYS_ADMIN` is the largest privilege grant in this product. In a container it
is close to root on the host kernel's surface: an abused helper could mount,
snapshot or delete filesystems rather than the one library subvolume, which is
exactly the danger the CephFS and ZFS providers avoid by never needing root at
all. The grant is contained on purpose:

* the sidecar sees one host path -- the library subvolume, bind-mounted
  read-write at `/library`. There is no other mount, no docker socket, no host
  root, and the container's own root filesystem is read-only.
* the API never sends a path, and the name is the only client-supplied field in
  the whole API. A name must match the `snapshots` name scheme, and the helper
  re-validates it and resolves the destination before proving it is still
  strictly inside the mount, so `..`, a slash, a backslash, a NUL byte, a
  leading `-`, an absolute path and a planted symlink are all refused before any
  command runs. A request body carrying any key other than `name` is refused
  with 400 and no action.
* the only commands it can build are `btrfs subvolume snapshot -r`, whose `-r`
  makes every snapshot read-only, and `btrfs subvolume delete` for one name
  inside `.snap`. They are argv lists handed to `subprocess.run` with
  `shell=False`, never shell strings, so no name is ever interpreted by a shell.
* it publishes no ports, so it is reachable only from the compose network, and
  it refuses to boot without `SNAPSHOT_BTRFS_SIDECAR_TOKEN`. The token is never
  logged and never echoed in a response.
* every other capability is dropped (`cap_drop: [ALL]`), so `SYS_ADMIN` is the
  only one it has, and the API container itself never gains the capability: the
  API process cannot snapshot anything, not even by mistake.

| Key | Default | Effect |
|---|---|---|
| `SNAPSHOT_BTRFS_SIDECAR_URL` | empty (disabled) | Base URL of the sidecar, for example `http://snapshot-sidecar:8765`. Empty means no sidecar is configured: `btrfs_subvol` stays detected but unusable and no socket is opened. Not forwarded by a shipped manifest -- set it in the sidecar override. |
| `SNAPSHOT_BTRFS_SIDECAR_TOKEN` | empty | The bearer token the API sends and the sidecar requires; it must equal the sidecar's own `SNAPSHOT_BTRFS_SIDECAR_TOKEN`. The sidecar refuses to boot without one, and a mismatch makes the volume report `unreachable`. Not forwarded -- set it in the sidecar override. |
| `SNAPSHOT_BTRFS_SIDECAR_MOUNT` | `/library` | The sidecar's own library mount, read by `server.py`. It is not an API setting: the API never learns this path, which is why the probe compares the store the sidecar reports instead. Not forwarded -- set it in the sidecar override. |
| `SNAPSHOT_BTRFS_SIDECAR_PORT` | `8765` | The port the sidecar listens on, read by `server.py`; empty keeps the default, and a value that is not a number between 1 and 65535 refuses to boot with a `BootError`. Change it only together with `SNAPSHOT_BTRFS_SIDECAR_URL` in the API, and with the compose network alias. Not forwarded -- set it in the sidecar override. |

The health probe is bounded at a hardcoded 1 second
(`SNAPSHOT_BTRFS_TIMEOUT_SECONDS`); it is not an environment key, because it
runs inside every capability detection and a slow sidecar must not stall the
report.

### Real-btrfs verification (MANUAL)

None of this can be exercised in CI: the sidecar needs `CAP_SYS_ADMIN` and a real
btrfs filesystem, so a real deployment is the only place to prove it. On a host
with btrfs, as root, create a scratch filesystem with a library subvolume and
mount it:

```
mkfs.btrfs /dev/sdX
mount /dev/sdX /mnt/btrfs-check
btrfs subvolume create /mnt/btrfs-check/library
```

Start the sidecar against that mount -- same image, same capability, same token
as the override above -- and check that it is up. The documented service
publishes no ports, so `localhost:8765` only answers for a scratch container
started by hand with a one-off port mapping (`docker run --rm -p
127.0.0.1:8765:8765` with `SYS_ADMIN`, the token and the bind mount):

```
curl -H "Authorization: Bearer $SNAPSHOT_BTRFS_SIDECAR_TOKEN" http://localhost:8765/health
```

Expected: `"state": "ready"` plus the mount and whether `.snap` exists. Point
`SNAPSHOT_BTRFS_SIDECAR_URL` at it, take a snapshot through the API (or post the
name straight to the sidecar), and confirm what the filesystem thinks happened:

```
curl -X POST -H "Authorization: Bearer $SNAPSHOT_BTRFS_SIDECAR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "20260101T000000Z-manual-abc123"}' http://localhost:8765/snapshots
btrfs subvolume list -o /mnt/btrfs-check/library/.snap
btrfs property get -ts /mnt/btrfs-check/library/.snap/20260101T000000Z-manual-abc123 ro
```

Expected: the name is created, `btrfs subvolume list -o <mount>/.snap` shows it
under the store, and `btrfs property get` prints `ro=true`, so the snapshot is
read-only and cannot be modified through the store. Delete it again, then confirm
that a hostile name and a `path` key are both refused with 400 and no action:

```
curl -X DELETE -H "Authorization: Bearer $SNAPSHOT_BTRFS_SIDECAR_TOKEN" \
  http://localhost:8765/snapshots/20260101T000000Z-manual-abc123
curl -X POST -H "Authorization: Bearer $SNAPSHOT_BTRFS_SIDECAR_TOKEN" \
  -d '{"name": "../etc/passwd"}' http://localhost:8765/snapshots
curl -X POST -H "Authorization: Bearer $SNAPSHOT_BTRFS_SIDECAR_TOKEN" \
  -d '{"name": "20260101T000000Z-manual-abc123", "path": "/etc"}' \
  http://localhost:8765/snapshots
```

Expected: 204 for the delete, and 400 for both hostile bodies -- the traversal
name fails the name check and the extra `path` key is refused before the name is
looked at. Record the run in the deployment notes; it is operator evidence, not
CI evidence, and it is not a substitute for
`makervault/api/tests/test_snapshot_sidecar_guard.py`.
