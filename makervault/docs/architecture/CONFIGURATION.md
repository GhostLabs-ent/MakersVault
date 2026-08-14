# MakersVault Configuration Inventory

**Baseline:** Gate 1 slice 1D candidate, 2026-08-14

This inventory records configuration ownership. It does not replace the secure
deployment guidance required by Gate 1.

## Canonical deployment files

| Use | File |
|---|---|
| Local source build | `makervault/docker-compose.yml` |
| Production images | `makervault/docker-compose.deploy.yml` |
| Historical production alias | `makervault/docker-deploy.yml` |
| Canonical environment example | `makervault/.env.example` |

## API and container settings

| Variable | Current default | Owner and effect |
|---|---|---|
| `PUID`, `PGID` | `1000` | API entrypoint; runtime file ownership. |
| `CHOWN_MODE` | `minimal` | API entrypoint; `recursive` opts into a full data-tree ownership repair. |
| `FILE_STORAGE` | `./storage` in code; `/app/storage` in Compose | Managed primary, thumbnail, and bundle root. |
| `DB_URL` | `sqlite:///./app.db` in code | SQLAlchemy database URL; Compose uses `/app/data/app.db`. |
| `MAKERSVAULT_ENV` | `production` in code and production; explicit `development` in source Compose | Selects the fail-closed validation policy. |
| `AUTH_USERNAME` | `admin` | Current single-admin identity; it is not treated as a secret. |
| `AUTH_PASSWORD` | none in production | Required in production; at least 12 characters and not a published placeholder. |
| `AUTH_SECRET` | none in production | Required deployment-specific JWT secret; at least 32 bytes and distinct from the password. |
| `AUTH_TOKEN_TTL` | `43200` seconds | JWT lifetime. |
| `PUBLIC_URL` | empty | Public browser origin; also allows web runtime API derivation. |
| `CORS_ORIGINS` | derived or localhost | Comma-separated browser origins accepted by API CORS middleware. |
| `API_PORT` | `8000` | Published API port. |
| `WEB_PORT` | `5173` | Published web port. |

## Ingest and derived-preview budgets

These limits apply per file or per ZIP extraction request; they are not a
library-wide quota. Ordinary multi-file and mounted imports have no cumulative
file-count or batch-byte ceiling. A value that is not an integer, or is below
the documented minimum, stops the affected container at startup.

| Variable | Current default | Effect |
|---|---:|---|
| `FILE_MAX_MB` | `512` | Shared per-file limit for direct, supporting, remote, mounted, and extracted files. The web proxy derives a request-body ceiling with 1 MiB of multipart allowance. |
| `STORAGE_RESERVE_MB` | `512` | Minimum free space retained while writing managed or temporary files; `0` explicitly disables the reserve. |
| `ARCHIVE_MAX_ENTRIES` | `10000` | Maximum ZIP central-directory entries enumerated. |
| `ARCHIVE_MAX_SELECTED` | `1000` | Maximum entries selected in one ZIP extraction request. |
| `ARCHIVE_MAX_EXPANDED_MB` | `2048` | Maximum declared expanded bytes selected in one ZIP extraction request. |
| `ARCHIVE_MAX_RATIO` | `200` | Maximum uncompressed-to-compressed ratio for a ZIP member that MakersVault reads. |
| `ARCHIVE_METADATA_MAX_MB` | `16` | Aggregate 3MF thumbnail/metadata bytes considered during one inspection. |
| `IMAGE_MAX_PIXELS` | `64000000` | Maximum decoded pixels for a server-generated image preview. |
| `GENERATED_THUMBNAIL_MAX_MB` | `8` | Maximum browser-generated thumbnail upload. |

`IMPORT_MAX_MB` remains a v5.0 compatibility alias for `FILE_MAX_MB` when the
new variable is absent. Set `FILE_MAX_MB` for new installations. Raising it
also requires an equal or higher request-body limit at any external reverse
proxy.

## Remote import settings

| Variable | Current default | Effect |
|---|---|---|
| `IMPORT_TIMEOUT_SECONDS` | `30` | Remote request time budget. |
| `IMPORT_MAX_REDIRECTS` | `5` | Maximum transport redirects; every hop is revalidated and HTTPS downgrade is rejected. Set `0` to disable redirects. |
| `IMPORT_MAX_MB` | `512` | Compatibility alias for `FILE_MAX_MB`; retained for existing deployments. |
| `IMPORT_HTML_MAX_KB` | `4096` | Maximum resolver HTML size. |
| `MAKERWORLD_COOKIE` | empty | Optional server-side source credential. Browser-provided values are not persisted by the API. |
| `THINGIVERSE_COOKIE` | empty | Optional server-side source credential. Browser-provided values are not persisted by the API. |

## Mounted import settings

| Variable | Current default | Effect |
|---|---|---|
| `IMPORT_MOUNT_PATH` | empty in canonical production manifest | Container path eligible for scanning. Legacy alias `MOUNT_IMPORT_PATH` is also read by the API. |
| `IMPORT_MOUNT_PATH_HOST` | `./imports` | Read-only host path mounted at `/imports` by production Compose. |
| `IMPORT_MOUNT_EXTS` | built-in supported list | Comma-separated eligible extensions. |
| `IMPORT_MOUNT_INCLUDE_HIDDEN` | `false` | Whether hidden paths are scanned. |
| `IMPORT_MOUNT_ON_STARTUP` | `false` in canonical production manifest | Enables the current startup scan. The code default remains `true` when a path exists. |
| `IMPORT_MOUNT_COPY` | `true` | Copy into managed storage instead of indexing in place. |

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
