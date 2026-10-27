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
| `AUTH_USERNAME` | `admin` | Current single-admin identity. Gate 1 must remove unsafe production fallback behavior. |
| `AUTH_PASSWORD` | `super-secret` | Current single-admin secret. Confirmed Gate 1 blocker. |
| `AUTH_SECRET` | `changeme-secret` | JWT signing secret. Confirmed Gate 1 blocker. |
| `AUTH_ALLOW_INSECURE_DEFAULTS` | unset (false) | Opts out of the startup guard that refuses the published sample credentials while auth is enabled. |
| `AUTH_TOKEN_TTL` | `43200` seconds | JWT lifetime. |
| `PUBLIC_URL` | empty | Public browser origin; also allows web runtime API derivation. |
| `CORS_ORIGINS` | derived or localhost | Comma-separated browser origins accepted by API CORS middleware. |
| `API_PORT` | `8000` | Published API port. |
| `WEB_PORT` | `5173` | Published web port. |

## Remote import settings

| Variable | Current default | Effect |
|---|---|---|
| `IMPORT_TIMEOUT_SECONDS` | `30` | Remote request time budget. |
| `IMPORT_MAX_MB` | `512` | Maximum remote response size for link imports and zip entries. |
| `MAX_UPLOAD_MB` | `4096` | Direct upload cap enforced by the API; the reverse proxy needs a matching `client_max_body_size`. |
| `IMPORT_HTML_MAX_KB` | `4096` | Maximum resolver HTML size. |
| `MAKERWORLD_COOKIE` | empty | Optional server-side source credential. Browser-provided values are not persisted by the API. |
| `THINGIVERSE_COOKIE` | empty | Optional server-side source credential. Browser-provided values are not persisted by the API. |

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

The production web image is a static Vite build served by unprivileged Nginx.
Only `web/40-runtime-config.sh` participates in its runtime configuration. The old
Node development entrypoint is not part of the production image.

## Browser-local settings

The browser stores theme, preview mode, selected slicer/engraver, optional source-
site cookies, and a network override in local storage. These are per-browser and
are not server `AppConfig` values. Gate 1 re-evaluates authentication-token
storage separately.

## Server `AppConfig` settings

The current database-backed settings are mounted-import enable/copy behavior and
the managed-storage template. These settings are shared by the instance.
