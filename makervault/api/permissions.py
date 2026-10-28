"""Server-side authorization: one permission level per route, declared at the route.

Authentication (`auth.require_auth`) answers "who is calling"; this module
answers "is that principal allowed to call this endpoint". There is exactly one
declarative mechanism, so a reviewer can read a route and see its level, and a
reviewer of the table below can see every level in one place:

* `PUBLIC`  - no authentication at all (`/health`, the token endpoints).
* `READ`    - any authenticated principal, whatever its role. Viewers live here.
* `WRITE`   - editors and administrators: every route that mutates the library.
* `ADMIN`   - administrators only: settings, user administration, purge.

Enforcement is the *route declaration*: each guarded route names
`Depends(require_read | require_write | require_admin)`, which is the only way to
express a level. `ROUTE_PERMISSIONS` is the audited matrix; it changes no
behaviour on its own, it is cross-checked against the real routes by
`assert_routes_classified()` at startup (see `main.lifespan`) and by the test
sweeps, so a route cannot ship with a level the matrix does not know about and
the matrix cannot keep an entry for a route that no longer exists.

Mf-s3z0 (the audit log) deliberately does NOT emit from `authorize()`. Those are
two different jobs: this module makes the *authorization* decision (who may call
what), while an audit *event* is what happened to which target - and
`authorize()` runs before the mutation, has no target, and cannot know whether
anything changed. Events are emitted at the action site instead, with
`audit.assert_audit_coverage()` as the drift guard. No other module may add an
ad-hoc permission check: a second way to say "admin" is a second way to get it
wrong (see `auth.require_admin`, deleted in this ticket).

Deliberate simplification: the level is per route, not per record. Mf-arm6 owns
per-asset ownership; until then an editor acts on every asset.
"""

from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.routing import APIRoute

import accounts
from auth import AuthContext, require_auth

PUBLIC = "public"
READ = "read"
WRITE = "write"
ADMIN = "admin"

# Ranked so the comparison is a single `<`; adding a level later means giving it
# a rank here and a role mapping below, nowhere else.
LEVEL_RANK = {PUBLIC: 0, READ: 1, WRITE: 2, ADMIN: 3}

# A role maps to the highest level it may use. Accounts are stored normalised
# (`accounts._clean_role`), so the keys are the canonical role strings.
ROLE_LEVELS = {
    accounts.ADMIN_ROLE: ADMIN,
    accounts.EDITOR_ROLE: WRITE,
    accounts.DEFAULT_ROLE: READ,
}

# One 403 detail per level, so a denial says what would have been needed without
# revealing anything about the resource. The admin string is the one
# `auth.require_admin` used to raise and is kept verbatim.
DENY_DETAIL = {
    READ: "Authentication required",
    WRITE: "Editor or administrator access required",
    ADMIN: "Administrator access required",
}


def level_for_role(role: Optional[str]) -> str:
    """The level a role may use; an unknown or blank role gets the least (PUBLIC).

    Failing closed matters here: a row with a hand-edited role, or a NULL that
    slipped through, must not be treated as "at least a viewer".
    """
    return ROLE_LEVELS.get((role or "").strip().lower(), PUBLIC)


def authorize(request: Request, context: Optional[AuthContext], level: str) -> None:
    """Raise 403 unless this principal may use `level`; the single choke point.

    `context is None` means authentication is disabled for this deployment
    (`auth.AUTH_ENABLED` is False), which keeps every route open exactly as it
    was before authorization existed. That is a deliberate deployment mode, not
    a bypass: the token endpoints answer 503 in it.

    This decides; it does not audit. Mf-s3z0 emits events at the action site
    because the decision has no target and runs before the mutation (see the
    module docstring).
    """
    if level == PUBLIC or context is None:
        return
    if LEVEL_RANK[level_for_role(context.role)] < LEVEL_RANK[level]:
        raise HTTPException(status_code=403, detail=DENY_DETAIL[level])


def require_permission(level: str) -> Callable:
    """Build the route dependency that enforces `level`, returning the context.

    The dependency is what actually guards the route, and `permission_level` on
    it is how `assert_routes_classified()` (and the tests) read the declaration
    back off the route. Public routes carry no dependency at all, so asking for
    one is a mistake rather than a no-op.
    """

    def dependency(
        request: Request,
        context: Optional[AuthContext] = Depends(require_auth),
    ) -> Optional[AuthContext]:
        authorize(request, context, level)
        return context

    dependency.permission_level = level
    return dependency


require_read = require_permission(READ)
require_write = require_permission(WRITE)
require_admin = require_permission(ADMIN)


# The audited matrix. Path strings are the FastAPI templates exactly as declared
# on the routes; `(method, path)` is the key so one path can carry two levels
# (`GET /library/scan` is a read, `POST /library/scan` is write).
ROUTE_PERMISSIONS: dict[tuple[str, str], str] = {
    # public: no authentication; the token endpoints 503 when auth is disabled.
    ("GET", "/health"): PUBLIC,
    ("POST", "/login"): PUBLIC,
    ("POST", "/refresh"): PUBLIC,
    ("POST", "/logout"): PUBLIC,
    # read: any authenticated principal, including viewers.
    ("GET", "/me"): READ,
    ("GET", "/library/scan"): READ,
    ("GET", "/file/{asset_id}/{name}"): READ,
    ("GET", "/asset/{asset_id}/files"): READ,
    ("GET", "/asset/{asset_id}/files/{file_id}"): READ,
    ("GET", "/asset/{asset_id}/prepared-print"): READ,
    ("GET", "/thumb/{asset_id}.jpg"): READ,
    ("GET", "/assets"): READ,
    ("GET", "/tags"): READ,
    # POST for a download: it builds a temp zip and streams it, nothing mutates.
    ("POST", "/download/zip"): READ,
    ("GET", "/folders"): READ,
    ("GET", "/projects"): READ,
    ("GET", "/project/{project_id}/assets"): READ,
    # A pure SELECT that counts what a delete would remove.
    ("GET", "/folder/{folder_id}/delete-preview"): READ,
    ("GET", "/folder/{folder_id}/download"): READ,
    ("GET", "/trash"): READ,
    # write: create, mutate or delete library content.
    ("POST", "/upload"): WRITE,
    ("POST", "/import"): WRITE,
    # Also an outbound-fetch oracle, like /import/inspect, and it mutates a project.
    ("POST", "/import/project"): WRITE,
    # No mutation, but both are outbound-fetch oracles (arbitrary URL in, remote
    # response out), so a viewer must not have them.
    ("POST", "/import/inspect"): WRITE,
    ("POST", "/import/zip/entries"): WRITE,
    ("POST", "/import/zip"): WRITE,
    ("POST", "/asset/{asset_id}/files"): WRITE,
    ("DELETE", "/asset/{asset_id}/files/{file_id}"): WRITE,
    ("DELETE", "/asset/{asset_id}/prepared-print"): WRITE,
    ("POST", "/asset/{asset_id}/thumbnail-generated"): WRITE,
    ("POST", "/assets/batch/tags"): WRITE,
    ("POST", "/assets/batch/folder"): WRITE,
    ("POST", "/assets/batch/delete"): WRITE,
    ("POST", "/asset/{asset_id}/tags"): WRITE,
    ("POST", "/asset/{asset_id}/meta"): WRITE,
    ("POST", "/asset/{asset_id}/rename"): WRITE,
    ("DELETE", "/asset/{asset_id}"): WRITE,
    ("POST", "/folders"): WRITE,
    ("PATCH", "/folder/{folder_id}"): WRITE,
    ("DELETE", "/folder/{folder_id}"): WRITE,
    ("POST", "/projects"): WRITE,
    ("PATCH", "/project/{project_id}"): WRITE,
    ("DELETE", "/project/{project_id}"): WRITE,
    ("POST", "/project/{project_id}/assets"): WRITE,
    ("DELETE", "/project/{project_id}/assets"): WRITE,
    ("POST", "/asset/{asset_id}/folder"): WRITE,
    # Registering files found on disk is library work, not administration, and
    # the missing-file banner offers Re-scan to editors; the audit event stays.
    ("POST", "/library/scan"): WRITE,
    # admin: settings, user administration, destruction, and the audit trail
    # itself.
    ("GET", "/audit"): ADMIN,
    ("GET", "/settings/mount-import"): ADMIN,
    ("POST", "/settings/mount-import"): ADMIN,
    ("GET", "/settings/storage"): ADMIN,
    ("POST", "/settings/storage"): ADMIN,
    ("POST", "/users"): ADMIN,
    ("GET", "/users"): ADMIN,
    ("PATCH", "/users/{user_id}"): ADMIN,
    # Purging deleted data is irreversible, so it is not an editor action.
    ("POST", "/trash/purge"): ADMIN,
}


def declared_levels(route: APIRoute) -> list[str]:
    """Every permission level this route declares, in dependency order.

    Walks the whole dependency tree (sub-dependencies included), because a route
    could otherwise smuggle a level in through a nested dependency.
    """
    levels: list[str] = []

    def walk(dependant) -> None:
        for dependency in dependant.dependencies:
            level = getattr(dependency.call, "permission_level", None)
            if level is not None:
                levels.append(level)
            walk(dependency)

    walk(route.dependant)
    return levels


def assert_routes_classified(app) -> dict[tuple[str, str], str]:
    """Prove the routes and ROUTE_PERMISSIONS agree; returns the matrix.

    Runs at startup (`main.lifespan`) so a route that forgets its level fails to
    boot instead of failing open, and in the tests so the sweeps and the
    enforcement read the same table. Every problem is collected before raising,
    so a single startup log line shows the whole drift.

    The three-way rule, per (method, path):

    * a route that declares a level must declare the one the matrix has;
    * a route that declares no level must be PUBLIC in the matrix;
    * a route must not declare two levels.

    Plus: every route must be in the matrix, and every matrix key must be a real
    route (no stale entries left behind by a deleted endpoint).
    """
    declared_keys: set[tuple[str, str]] = set()
    problems: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            # Starlette's docs/openapi routes are not part of the API contract.
            continue
        levels = declared_levels(route)
        if len(levels) > 1:
            problems.append(f"{route.path} declares {len(levels)} permission levels ({', '.join(levels)}); declare exactly one")
        level = levels[0] if levels else None
        for method in route.methods:
            key = (method, route.path)
            if method in {"HEAD", "OPTIONS"} and key not in ROUTE_PERMISSIONS:
                continue
            declared_keys.add(key)
            expected = ROUTE_PERMISSIONS.get(key)
            if expected is None:
                problems.append(
                    f"{method} {route.path} is missing from ROUTE_PERMISSIONS; "
                    "declare a level on the route and add it to the matrix"
                )
            elif level is None:
                if expected != PUBLIC:
                    problems.append(
                        f"{method} {route.path} declares no permission but the matrix says {expected!r}; "
                        f"add Depends(require_{expected}) to the route (or make it public)"
                    )
            elif level != expected:
                problems.append(f"{method} {route.path} declares {level!r} but the matrix says {expected!r}")

    for method, path in ROUTE_PERMISSIONS:
        if (method, path) not in declared_keys:
            problems.append(f"{method} {path} is in ROUTE_PERMISSIONS but no such route exists")
    if problems:
        raise RuntimeError("permission matrix does not match the routes:\n  - " + "\n  - ".join(problems))
    return ROUTE_PERMISSIONS
