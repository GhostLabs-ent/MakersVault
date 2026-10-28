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
| `IMPORT_HTML_MAX_KB` | `4096` | Maximum resolver HTML size. |
| `MAKERWORLD_COOKIE` | empty | Optional server-side source credential. Browser-provided values are not persisted by the API. |
| `THINGIVERSE_COOKIE` | empty | Optional server-side source credential. Browser-provided values are not persisted by the API. |

Upload bodies are streamed straight into storage: a body lands in
`<storage>/.incoming/<uuid>` and is renamed atomically into its rendered path
once the form fields that shape that path have arrived. Nothing is spooled into
container temp, so a 2 GB upload needs one 2 GB file rather than 2 GB of
scratch. `MAX_UPLOAD_MB` is enforced while the body streams, so an oversize
upload is cut off as soon as the cap is crossed.

## Mounted import settings

| Variable | Current default | Effect |
|---|---|---|
| `IMPORT_MOUNT_PATH` | empty in canonical production manifest | Container path eligible for scanning. Legacy alias `MOUNT_IMPORT_PATH` is also read by the API. A mount that contains or sits inside the storage root is refused (copy mode tolerates an identical root by registering in place), and the skip is logged at startup. |
| `IMPORT_MOUNT_PATH_HOST` | `./imports` | Read-only host path mounted at `/imports` by production Compose. |
| `IMPORT_MOUNT_EXTS` | built-in supported list | Comma-separated eligible extensions. |
| `IMPORT_MOUNT_INCLUDE_HIDDEN` | `false` | Whether hidden paths are scanned. |
| `IMPORT_MOUNT_ON_STARTUP` | `false` in canonical production manifest | Enables the startup scan. The code default remains `true` when a path is configured, so configuring a mount path is what opts a deployment in. |
| `IMPORT_MOUNT_COPY` | `true` | Copy into managed storage instead of indexing in place. Copy mode mirrors the mount's relative directory structure into the storage root (a mount holding `a/b/c.stl` registers `a/b/c.stl` and the folder chain `a` -> `a/b`); reference mode registers `is_reference` rows that point at the mount and copy nothing. |

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

The browser stores theme, preview mode, selected slicer/engraver, optional source-
site cookies, and a network override in local storage. These are per-browser and
are not server `AppConfig` values. Gate 1 re-evaluates authentication-token
storage separately.

## Server `AppConfig` settings

The current database-backed settings are mounted-import enable/copy behavior and
the managed-storage template. These settings are shared by the instance.
