"""MakerVault API entrypoint: app wiring, startup guards and the test patch surface.

The routes live in `routers/` now (Mf-x9dx split them out of this module); what
stays here is the FastAPI app, the lifespan boot checks, the CORS/request-id
middleware and the compatibility re-exports described below.
"""

import os
import threading
from contextlib import asynccontextmanager
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

import asset_service
import audit
import import_runs
import login_throttle as login_throttle_module
import oidc
import permissions
from asset_file_service import backfill_prepared_print_metadata
from asset_service import backfill_embedded_thumbnails
from auth import validate_auth_configuration
from config import (
    ASSET_FILE_MAX_BYTES,
    ASSET_FILE_MAX_COUNT,
    ASSET_FILE_TOTAL_MAX_BYTES,
    IMPORT_MAX_BYTES,
    MAX_UPLOAD_BYTES,
)
from db import THUMBS, engine
from import_service import (
    download_import_to_temp,
    download_zip_attempt,
    import_asset_attempt,
    import_asset_from_url,
    open_import_response,
)
from library_scan import scan_status, start_scan
from migrations import run_migrations
from mount_import import mount_import_should_run, scan_mount_imports
from request_id import RequestIDMiddleware
from routers import (
    asset_files,
    assets,
    audit_log,
    auth_users,
    folders,
    imports,
    library,
    projects,
    settings,
    snapshots,
    system,
    trash,
    uploads,
)
from routers import (
    oidc as oidc_routes,
)
from routers.import_runs import router as import_runs_router
from routers.uploads import delete_asset_row_only
from url_utils import normalize_import_url
from version import __version__
from zip_service import arcname_for_asset

# The routers this app serves, in include order. One list drives both the
# startup guard and the `include_router` calls below, so a router cannot be
# served without being checked (or checked without being served).
API_ROUTERS = (
    system.router,
    settings.router,
    snapshots.router,
    library.router,
    auth_users.router,
    audit_log.router,
    uploads.router,
    imports.router,
    import_runs_router,
    asset_files.router,
    assets.router,
    folders.router,
    oidc_routes.router,
    projects.router,
    trash.router,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_configuration()
    # The same fail-closed contract one feature over: a half-configured or
    # fail-open SSO setup must stop the boot, not surface as a login that
    # breaks on its first request. Clears the in-process state and handoff
    # stores too, so a restarted process never inherits a spent state.
    oidc.validate_oidc_configuration()
    oidc.reset()
    # Fail at boot, not at the first request: a route that forgot its permission
    # level (or drifted from ROUTE_PERMISSIONS) is a security bug, so this check
    # refuses to start serving until it is fixed. The routes come from the
    # routers we own, not from `app.routes`: fastapi's lazy route tree hides the
    # included routes, and a guard that sees nothing checks nothing.
    permissions.assert_routes_classified(permissions.router_routes(*API_ROUTERS))
    # Same contract one level down: a mutating route that emits no audit event
    # (and is not exempt with a reason) is a bug that must not reach production.
    audit.assert_audit_coverage()
    login_throttle_module.limiter.reset()
    run_migrations(engine)
    # A row left `running` belongs to a previous process that died before it
    # could finish. This runs before the mount thread, so it cannot catch ours.
    import_runs.mark_interrupted()
    # Runs before the server accepts connections, so a single-process deployment
    # cannot have an in-flight upload for the sweep to race.
    asset_service.sweep_staging_dir()
    threading.Thread(target=backfill_embedded_thumbnails, daemon=True).start()
    threading.Thread(target=backfill_prepared_print_metadata, daemon=True).start()
    if mount_import_should_run():
        threading.Thread(target=scan_mount_imports, daemon=True).start()
    # Last in the boot sequence on purpose: the scheduled-snapshot thread is
    # provably started after migrations and after both boot guards, and the
    # function-local import keeps the snapshot stack out of every `import main`
    # (mirroring the function-local `import snapshot_zfs` idiom).
    import snapshot_schedule

    if snapshot_schedule.should_run():
        threading.Thread(target=snapshot_schedule.run_forever, args=(threading.Event(),), daemon=True).start()
    yield


app = FastAPI(title="MakerVault API", version=__version__, lifespan=lifespan)


def normalize_origin(raw: str) -> Optional[str]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def resolve_cors_origins() -> str:
    raw = os.getenv("CORS_ORIGINS")
    if raw:
        return raw
    candidates: List[str] = []
    for name in ("PUBLIC_URL", "VITE_API_URL"):
        origin = normalize_origin(os.getenv(name, ""))
        if origin:
            candidates.append(origin)
    if candidates:
        # Preserve order, remove duplicates.
        return ",".join(dict.fromkeys(candidates))
    return "http://localhost:5173"


origins_env = resolve_cors_origins()
origins = [o.strip() for o in origins_env.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Has-More", "X-Next-Offset", "X-Request-ID"],
)
app.add_middleware(RequestIDMiddleware)

for router in API_ROUTERS:
    app.include_router(router)


# Compatibility re-exports: the test patch surface ------------------------------
# The suite monkeypatches these names ON THIS MODULE (`monkeypatch.setattr(main,
# "THUMBS", ...)`, `setattr(main, "start_scan", ...)`, ...), and `setattr` runs
# with `raising=True`, so each name must exist here. The handlers resolve them at
# call time through `seams` (and `db.THUMBS` for the thumbnail root), which is
# why these bindings are inert on their own. They are the patch surface: do not
# "clean up" the imports, and keep `__all__` in step with the names the tests pin.
__all__ = (
    # the names the suite monkeypatches on this module
    "THUMBS",
    "MAX_UPLOAD_BYTES",
    "IMPORT_MAX_BYTES",
    "ASSET_FILE_MAX_BYTES",
    "ASSET_FILE_TOTAL_MAX_BYTES",
    "ASSET_FILE_MAX_COUNT",
    "start_scan",
    "scan_status",
    "normalize_import_url",
    "import_asset_from_url",
    "import_asset_attempt",
    "download_zip_attempt",
    "open_import_response",
    "download_import_to_temp",
    # the ones it calls directly, plus the app object it drives
    "delete_asset_row_only",
    "oidc",
    "arcname_for_asset",
    "lifespan",
    "app",
)
