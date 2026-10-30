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
the matrix cannot keep an entry for a route that no longer exists. The caller
hands the checker the routes enumerated from the routers we own
(`permissions.router_routes(*main.API_ROUTERS)`), because `app.routes` is no
longer a complete view: fastapi 0.137+ wraps `include_router` in a lazy tree, so
the included routes never appear there.

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

from typing import Callable, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from sqlmodel import Session

import accounts
import mfa
import sessions
import settings_service
from auth import AuthContext, require_auth, require_auth_or_file_grant
from db import engine

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

# A distinct detail from `DENY_DETAIL[ADMIN]`: the caller is already an admin,
# the *session* just has not proved a second factor yet. One message covers
# both "step up" and "you have no factor at all"; the header distinguishes the
# latter so the client can offer the self-service enrolment routes.
MFA_REQUIRED_DETAIL = "Multi-factor authentication required"
MFA_ENROLMENT_HEADER = "X-MFA-Enrolment-Required"


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
    # After the rank check on purpose: a viewer still gets the plain 403, and
    # only a real admin is asked whether this session has a second factor.
    if level == ADMIN:
        enforce_admin_mfa(context)


def enforce_admin_mfa(context: AuthContext) -> None:
    """Require an MFA-ok session for an admin action while the policy is on.

    Break-glass is exempt: it has no user row, so there is nowhere to store a
    seed and gating the bootstrap path on one would be circular. The policy is
    an appconfig setting (an audited admin route toggles it), read once per
    admin request; when it is off this costs one primary-key SELECT.

    A session that never showed a factor is 403. The reason is the same single
    string in both cases, but a not-yet-enrolled account also gets
    `X-MFA-Enrolment-Required`, because there is nothing to step up to and the
    READ-level `/mfa*` routes stay reachable for exactly that path.
    """
    if context.kind == sessions.BREAK_GLASS_KIND:
        return
    if not settings_service.get_mfa_require_admin():
        return
    with Session(engine) as db:
        session_row = sessions.get(db, context.session_id)
        user = accounts.get_user(db, context.user_id)
    if mfa.mfa_ok(session_row):
        return
    headers = {} if mfa.user_is_enrolled(user) else {MFA_ENROLMENT_HEADER: "1"}
    raise HTTPException(status_code=403, detail=MFA_REQUIRED_DETAIL, headers=headers)


def require_permission(level: str, authenticate: Callable = require_auth) -> Callable:
    """Build the route dependency that enforces `level`, returning the context.

    `authenticate` is the authenticator the dependency runs; it defaults to the
    session-token verifier. The file routes pass `require_auth_or_file_grant` so
    a `?sig=` grant can authenticate there, and only there.

    The dependency is what actually guards the route, and `permission_level` on
    it is how `assert_routes_classified()` (and the tests) read the declaration
    back off the route. Public routes carry no dependency at all, so asking for
    one is a mistake rather than a no-op.
    """

    def dependency(
        request: Request,
        context: Optional[AuthContext] = Depends(authenticate),
    ) -> Optional[AuthContext]:
        authorize(request, context, level)
        return context

    dependency.permission_level = level
    return dependency


require_read = require_permission(READ)
require_write = require_permission(WRITE)
require_admin = require_permission(ADMIN)
# Same READ level, different authenticator: attached only to the four file
# routes, so a grant can never reach a list, write or admin route.
require_file_read = require_permission(READ, require_auth_or_file_grant)


# The audited matrix. Path strings are the FastAPI templates exactly as declared
# on the routes; `(method, path)` is the key so one path can carry two levels
# (`GET /library/scan` is a read, `POST /library/scan` is write).
ROUTE_PERMISSIONS: dict[tuple[str, str], str] = {
    # public: no authentication; the token endpoints 503 when auth is disabled.
    ("GET", "/health"): PUBLIC,
    ("POST", "/login"): PUBLIC,
    ("POST", "/refresh"): PUBLIC,
    ("POST", "/logout"): PUBLIC,
    # OIDC / SSO (Mf-4c24). All four are public because they run before a
    # session exists, and all four 503 when auth is disabled, exactly like
    # /login. `status` only reports whether SSO is on; `start` and `callback`
    # mint and spend a single-use state; `exchange` is the one mutation and it
    # is audited (`login.oidc.succeeded`).
    ("GET", "/auth/oidc/status"): PUBLIC,
    ("GET", "/auth/oidc/start"): PUBLIC,
    ("GET", "/auth/oidc/callback"): PUBLIC,
    ("POST", "/auth/oidc/exchange"): PUBLIC,
    # MFA verification runs before a session exists: it trades the short-lived
    # challenge minted by `/login` for the real token pair, so it is public in
    # the same sense `/login` is. It is throttled on the challenge's subject.
    ("POST", "/mfa/verify"): PUBLIC,
    # read: any authenticated principal, including viewers.
    ("GET", "/me"): READ,
    # A viewer must be able to list and sign out their own devices, so both
    # `/me/sessions` routes are READ. Ownership scoping is a data constraint in
    # the handler, not a second permission mechanism: a foreign session id
    # answers 404 rather than 403, so the route never reveals that somebody
    # else's session exists.
    ("GET", "/me/sessions"): READ,
    ("DELETE", "/me/sessions/{session_id}"): READ,
    # The MFA self-service routes act on the caller's own account, exactly like
    # `/me/sessions`, so they are READ: a viewer must be able to enrol, step up
    # and read their own status. The admin policy is what gates *other* admin
    # routes, not this surface; every one of these 503s when auth is off.
    ("GET", "/mfa"): READ,
    ("POST", "/mfa/enrol"): READ,
    ("POST", "/mfa/confirm"): READ,
    ("POST", "/mfa/step-up"): READ,
    ("DELETE", "/mfa"): READ,
    ("POST", "/mfa/recovery-codes"): READ,
    ("GET", "/library/scan"): READ,
    ("GET", "/imports/runs"): READ,
    ("GET", "/imports/runs/{run_id}"): READ,
    ("GET", "/file/{asset_id}/{name}"): READ,
    ("GET", "/asset/{asset_id}/files"): READ,
    ("GET", "/asset/{asset_id}/files/{file_id}"): READ,
    ("GET", "/asset/{asset_id}/files/limits"): READ,
    ("GET", "/asset/{asset_id}/prepared-print"): READ,
    ("GET", "/thumb/{asset_id}.jpg"): READ,
    # mints a short-lived read-only grant; nothing mutates.
    ("POST", "/file-grants"): READ,
    ("GET", "/assets"): READ,
    # A pure SELECT that counts what a bulk delete would remove.
    ("GET", "/assets/delete-preview"): READ,
    ("GET", "/tags"): READ,
    ("GET", "/creators"): READ,
    # POST for a download: it builds a temp zip and streams it, nothing mutates.
    ("POST", "/download/zip"): READ,
    ("GET", "/folders"): READ,
    ("GET", "/projects"): READ,
    ("GET", "/project/{project_id}/assets"): READ,
    # A pure SELECT that counts what a delete would remove.
    ("GET", "/folder/{folder_id}/delete-preview"): READ,
    ("GET", "/folder/{folder_id}/download"): READ,
    ("GET", "/trash"): READ,
    # A read-only report of filesystem snapshot capability; creates nothing.
    ("GET", "/storage/capabilities"): READ,
    # A snapshot list is a read of the provider's view; it creates nothing.
    ("GET", "/snapshots"): READ,
    # A browse is a read of one snapshot view, and creates nothing either.
    ("GET", "/snapshots/{name}/browse"): READ,
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
    ("PATCH", "/asset/{asset_id}/files/{file_id}"): WRITE,
    ("PUT", "/asset/{asset_id}/files/order"): WRITE,
    ("DELETE", "/asset/{asset_id}/prepared-print"): WRITE,
    ("POST", "/asset/{asset_id}/thumbnail-generated"): WRITE,
    ("POST", "/assets/batch/tags"): WRITE,
    ("POST", "/assets/batch/folder"): WRITE,
    ("POST", "/assets/batch/delete"): WRITE,
    ("POST", "/assets/batch/meta"): WRITE,
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
    # Taking a snapshot and restoring one are library mutations, not administration.
    ("POST", "/snapshots"): WRITE,
    # A restore copies snapshot bytes back into the library: an editor's move.
    ("POST", "/snapshots/{name}/restore"): WRITE,
    # admin: settings, user administration, destruction, and the audit trail
    # itself.
    ("GET", "/audit"): ADMIN,
    ("GET", "/settings/mount-import"): ADMIN,
    ("POST", "/settings/mount-import"): ADMIN,
    # The MFA policy decides what every admin route demands, so changing it is
    # administration itself.
    ("POST", "/settings/mfa"): ADMIN,
    ("GET", "/settings/storage"): ADMIN,
    ("POST", "/settings/storage"): ADMIN,
    # Reading the retention policy that bounds every snapshot is administration.
    ("GET", "/snapshots/retention"): ADMIN,
    # The scheduler's status surface reports what a background thread did; it
    # operates nothing, so it is administration, not a library mutation.
    ("GET", "/snapshots/schedule"): ADMIN,
    # Changing it decides what history survives, so it is not an editor action.
    ("POST", "/snapshots/retention"): ADMIN,
    # Deleting a snapshot decides what history survives too.
    ("DELETE", "/snapshots/{name}"): ADMIN,
    ("POST", "/users"): ADMIN,
    ("GET", "/users"): ADMIN,
    ("PATCH", "/users/{user_id}"): ADMIN,
    # Session administration over another principal: listing somebody else's
    # devices and revoking one are admin, like every other user-administration
    # route, and unlike the `/me/sessions` pair above.
    ("GET", "/users/{user_id}/sessions"): ADMIN,
    ("DELETE", "/sessions/{session_id}"): ADMIN,
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


def router_routes(*routers: APIRouter) -> list[APIRoute]:
    """Every route the given routers declare, in declaration order.

    Enumerate from the routers we own rather than from `app.routes`: fastapi
    wraps `include_router` in a lazy tree (0.137+), so `app.routes` no longer
    yields the included `APIRoute`s and the boot guard would see nothing. Each
    `APIRouter.routes` is public API and already carries the final path and the
    route's dependency tree, which is what `assert_routes_classified` reads.

    A router that includes another router would put a non-`APIRoute` in
    `.routes`, so this refuses instead of silently skipping it: a route the
    guard cannot see is a route that fails open.
    """
    routes: list[APIRoute] = []
    for router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                raise RuntimeError(
                    f"{type(route).__name__} in a router's .routes; permission enumeration only "
                    "handles routes declared on the router itself - list a nested router "
                    "separately in main.API_ROUTERS"
                )
            routes.append(route)
    return routes


def assert_routes_classified(routes: Sequence[APIRoute]) -> dict[tuple[str, str], str]:
    """Prove the routes and ROUTE_PERMISSIONS agree; returns the matrix.

    `routes` is the enumeration from the routers we own
    (`permissions.router_routes(*main.API_ROUTERS)`), not `app.routes`: the
    app-level list is a lazy tree in current fastapi, so it would miss every
    included route and pass vacuously.

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
    if not routes:
        # Fail closed: with no routes both loops below pass vacuously, which is
        # exactly how a lazy route tree slipped past the guard before.
        problems.append("no routes enumerated: nothing was checked against ROUTE_PERMISSIONS")
    for route in routes:
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
