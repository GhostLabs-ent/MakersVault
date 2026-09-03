"""Gate 11C shared-vault roles and deny-by-default route authorization."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.routing import APIRoute


class Role(str, Enum):
    ADMINISTRATOR = "administrator"
    MEMBER = "member"
    VIEWER = "viewer"


class Permission(str, Enum):
    VAULT_READ = "vault.read"
    CONTENT_DOWNLOAD = "content.download"
    CONTENT_EXPORT = "content.export"
    HANDOFF_CREATE = "handoff.create"
    CONTENT_MANAGE = "content.manage"
    TRASH_READ = "trash.read"
    TRASH_RESTORE = "trash.restore"
    CONTENT_DELETE_PERMANENTLY = "content.delete_permanently"
    TRASH_EMPTY = "trash.empty"
    SETTINGS_MANAGE = "settings.manage"
    JOBS_MANAGE = "jobs.manage"
    SESSION_MANAGE_SELF = "session.manage_self"
    IDENTITY_MANAGE_SELF = "identity.manage_self"
    IDENTITY_MANAGE = "identity.manage"
    AUDIT_READ = "audit.read"


VIEWER_PERMISSIONS = frozenset(
    {
        Permission.VAULT_READ,
        Permission.CONTENT_DOWNLOAD,
        Permission.CONTENT_EXPORT,
        Permission.HANDOFF_CREATE,
        Permission.SESSION_MANAGE_SELF,
        Permission.IDENTITY_MANAGE_SELF,
    }
)
MEMBER_PERMISSIONS = VIEWER_PERMISSIONS | frozenset(
    {
        Permission.CONTENT_MANAGE,
        Permission.TRASH_READ,
        Permission.TRASH_RESTORE,
    }
)
ADMINISTRATOR_PERMISSIONS = MEMBER_PERMISSIONS | frozenset(
    {
        Permission.CONTENT_DELETE_PERMANENTLY,
        Permission.TRASH_EMPTY,
        Permission.SETTINGS_MANAGE,
        Permission.JOBS_MANAGE,
        Permission.IDENTITY_MANAGE,
        Permission.AUDIT_READ,
    }
)
ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = MappingProxyType(
    {
        Role.VIEWER: VIEWER_PERMISSIONS,
        Role.MEMBER: MEMBER_PERMISSIONS,
        Role.ADMINISTRATOR: ADMINISTRATOR_PERMISSIONS,
    }
)


def permissions_for_role(role: Role) -> frozenset[Permission]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc


def role_allows(role: Role, permission: Permission) -> bool:
    return permission in permissions_for_role(role)


class AccessKind(str, Enum):
    PUBLIC = "public"
    SESSION = "session"
    SCOPED_HANDOFF = "scoped_handoff"


@dataclass(frozen=True)
class RouteRule:
    kind: AccessKind
    permission: Permission | None = None
    recent_reauthentication: bool = False

    def __post_init__(self) -> None:
        if (self.kind is AccessKind.SESSION) != (self.permission is not None):
            raise ValueError("session route rules require exactly one permission")
        if self.recent_reauthentication and self.kind is not AccessKind.SESSION:
            raise ValueError("only session routes can require recent reauthentication")


def _session(permission: Permission) -> RouteRule:
    return RouteRule(AccessKind.SESSION, permission)


def _recent(permission: Permission) -> RouteRule:
    return RouteRule(AccessKind.SESSION, permission, recent_reauthentication=True)


PUBLIC = RouteRule(AccessKind.PUBLIC)
SCOPED_HANDOFF = RouteRule(AccessKind.SCOPED_HANDOFF)


# This inventory is deliberately exhaustive and separate from HTTP verbs inferred
# by convention. A route addition cannot become reachable until it is classified.
ROUTE_AUTHORIZATION: Mapping[tuple[str, str], RouteRule] = MappingProxyType(
    {
        ("GET", "/health"): PUBLIC,
        ("POST", "/login"): PUBLIC,
        ("GET", "/handoff/redeem"): SCOPED_HANDOFF,

        ("GET", "/session"): _session(Permission.SESSION_MANAGE_SELF),
        ("GET", "/sessions"): _session(Permission.SESSION_MANAGE_SELF),
        ("POST", "/logout"): _session(Permission.SESSION_MANAGE_SELF),
        ("DELETE", "/sessions/{session_id}"): _recent(Permission.SESSION_MANAGE_SELF),
        ("POST", "/sessions/revoke-all"): _recent(Permission.SESSION_MANAGE_SELF),
        ("POST", "/session/reauthenticate"): _session(Permission.IDENTITY_MANAGE_SELF),
        ("POST", "/account/password"): _recent(Permission.IDENTITY_MANAGE_SELF),

        ("GET", "/users"): _session(Permission.IDENTITY_MANAGE),
        ("POST", "/users"): _recent(Permission.IDENTITY_MANAGE),
        ("PATCH", "/users/{user_id}"): _recent(Permission.IDENTITY_MANAGE),
        ("POST", "/users/{user_id}/password-reset"): _recent(Permission.IDENTITY_MANAGE),
        ("GET", "/audit"): _session(Permission.AUDIT_READ),

        ("GET", "/assets"): _session(Permission.VAULT_READ),
        ("GET", "/tags"): _session(Permission.VAULT_READ),
        ("GET", "/folders"): _session(Permission.VAULT_READ),
        ("GET", "/projects"): _session(Permission.VAULT_READ),
        ("GET", "/project/{project_id}"): _session(Permission.VAULT_READ),
        ("GET", "/project/{project_id}/items"): _session(Permission.VAULT_READ),
        ("GET", "/project/{project_id}/tags"): _session(Permission.VAULT_READ),
        ("GET", "/project/{project_id}/candidates"): _session(Permission.VAULT_READ),
        ("GET", "/project/{project_id}/relationships"): _session(Permission.VAULT_READ),
        ("GET", "/machines"): _session(Permission.VAULT_READ),
        ("GET", "/machine/{machine_id}"): _session(Permission.VAULT_READ),
        ("GET", "/asset/{asset_id}/machines"): _session(Permission.VAULT_READ),
        ("GET", "/asset/{asset_id}/files"): _session(Permission.VAULT_READ),
        ("GET", "/asset/{asset_id}/revisions"): _session(Permission.VAULT_READ),
        ("GET", "/asset/{asset_id}/duplicates"): _session(Permission.VAULT_READ),
        ("GET", "/asset/{asset_id}/prepared-print"): _session(Permission.VAULT_READ),
        ("GET", "/settings/preview-policy"): _session(Permission.VAULT_READ),

        ("GET", "/file/{asset_id}/{name}"): _session(Permission.CONTENT_DOWNLOAD),
        ("GET", "/asset/{asset_id}/files/{file_id}"): _session(Permission.CONTENT_DOWNLOAD),
        ("GET", "/asset/{asset_id}/revisions/{revision_id}/file"): _session(Permission.CONTENT_DOWNLOAD),
        ("GET", "/asset/{asset_id}/revisions/{revision_id}/thumbnail"): _session(Permission.CONTENT_DOWNLOAD),
        ("GET", "/thumb/{asset_id}.jpg"): _session(Permission.CONTENT_DOWNLOAD),

        ("POST", "/download/zip"): _session(Permission.CONTENT_EXPORT),
        ("GET", "/folder/{folder_id}/download"): _session(Permission.CONTENT_EXPORT),
        ("GET", "/asset/{asset_id}/revisions/export"): _session(Permission.CONTENT_EXPORT),
        ("GET", "/project/{project_id}/export"): _session(Permission.CONTENT_EXPORT),
        ("POST", "/asset/{asset_id}/handoff"): _session(Permission.HANDOFF_CREATE),

        ("POST", "/upload"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/import"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/import/inspect"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/import/zip/entries"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/import/zip"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/revisions"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/revisions/{revision_id}/restore"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/files"): _session(Permission.CONTENT_MANAGE),
        ("DELETE", "/asset/{asset_id}/files/{file_id}"): _session(Permission.CONTENT_MANAGE),
        ("DELETE", "/asset/{asset_id}/prepared-print"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/thumbnail-generated"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/preview-state"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/preview-retry"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/tags"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/meta"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/rename"): _session(Permission.CONTENT_MANAGE),
        ("DELETE", "/asset/{asset_id}"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/folders"): _session(Permission.CONTENT_MANAGE),
        ("PATCH", "/folder/{folder_id}"): _session(Permission.CONTENT_MANAGE),
        ("DELETE", "/folder/{folder_id}"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/folder"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/projects"): _session(Permission.CONTENT_MANAGE),
        ("PATCH", "/project/{project_id}"): _session(Permission.CONTENT_MANAGE),
        ("DELETE", "/project/{project_id}"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/project/{project_id}/items/{asset_id}"): _session(Permission.CONTENT_MANAGE),
        ("DELETE", "/project/{project_id}/items/{asset_id}"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/project/{project_id}/relationships"): _session(Permission.CONTENT_MANAGE),
        ("DELETE", "/project/{project_id}/relationships/{relationship_id}"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/machines"): _session(Permission.CONTENT_MANAGE),
        ("PATCH", "/machine/{machine_id}"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/machine/{machine_id}/archive"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/machine/{machine_id}/restore"): _session(Permission.CONTENT_MANAGE),
        ("POST", "/asset/{asset_id}/machines/{machine_id}"): _session(Permission.CONTENT_MANAGE),
        ("DELETE", "/asset/{asset_id}/machines/{machine_id}"): _session(Permission.CONTENT_MANAGE),
        ("PUT", "/asset/{asset_id}/prepared-machine"): _session(Permission.CONTENT_MANAGE),

        ("GET", "/trash"): _session(Permission.TRASH_READ),
        ("GET", "/projects/trash"): _session(Permission.TRASH_READ),
        ("POST", "/trash/{asset_id}/restore"): _session(Permission.TRASH_RESTORE),
        ("POST", "/project/{project_id}/restore"): _session(Permission.TRASH_RESTORE),

        ("POST", "/trash/permanent"): _recent(Permission.CONTENT_DELETE_PERMANENTLY),
        ("POST", "/trash/empty"): _recent(Permission.TRASH_EMPTY),
        ("POST", "/project/{project_id}/permanent"): _recent(Permission.CONTENT_DELETE_PERMANENTLY),
        ("POST", "/machine/{machine_id}/permanent"): _recent(Permission.CONTENT_DELETE_PERMANENTLY),

        ("GET", "/settings/mount-import"): _session(Permission.SETTINGS_MANAGE),
        ("POST", "/settings/mount-import"): _session(Permission.SETTINGS_MANAGE),
        ("GET", "/settings/storage"): _session(Permission.SETTINGS_MANAGE),
        ("POST", "/settings/storage"): _session(Permission.SETTINGS_MANAGE),
        ("GET", "/settings/trash"): _session(Permission.TRASH_READ),
        ("POST", "/settings/trash"): _session(Permission.SETTINGS_MANAGE),
        ("GET", "/settings/mount-import/scan"): _session(Permission.JOBS_MANAGE),
        ("POST", "/settings/mount-import/rescan"): _session(Permission.JOBS_MANAGE),
        ("GET", "/settings/content-identity"): _session(Permission.JOBS_MANAGE),
        ("POST", "/settings/content-identity/backfill"): _session(Permission.JOBS_MANAGE),
    }
)


class SystemService(str, Enum):
    SESSION_CLEANUP = "session.cleanup"
    TRASH_MAINTENANCE = "trash.maintenance"
    MOUNT_SCAN_RECOVER = "mount_scan.recover"
    MOUNT_SCAN_STARTUP = "mount_scan.startup"
    CONTENT_IDENTITY_RECOVER = "content_identity.recover"
    CONTENT_IDENTITY_STARTUP = "content_identity.startup"
    THUMBNAIL_BACKFILL = "thumbnail.backfill"
    PREPARED_METADATA_BACKFILL = "prepared_metadata.backfill"


SYSTEM_SERVICE_ENTRY_POINTS: Mapping[SystemService, str] = MappingProxyType(
    {
        SystemService.SESSION_CLEANUP: "startup-and-bounded-request-maintenance",
        SystemService.TRASH_MAINTENANCE: "startup-owned-background-loop",
        SystemService.MOUNT_SCAN_RECOVER: "startup-recovery",
        SystemService.MOUNT_SCAN_STARTUP: "startup-configuration",
        SystemService.CONTENT_IDENTITY_RECOVER: "startup-recovery",
        SystemService.CONTENT_IDENTITY_STARTUP: "startup-owned-background-job",
        SystemService.THUMBNAIL_BACKFILL: "startup-owned-background-job",
        SystemService.PREPARED_METADATA_BACKFILL: "startup-owned-background-job",
    }
)

_Result = TypeVar("_Result")


def run_system_service(
    service: SystemService,
    operation: Callable[[], _Result],
) -> _Result:
    if service not in SYSTEM_SERVICE_ENTRY_POINTS:
        raise RuntimeError(f"unclassified system service: {service}")
    return operation()


def route_rule(request: Request) -> RouteRule:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    rule = ROUTE_AUTHORIZATION.get((request.method.upper(), path))
    if rule is None:
        raise HTTPException(status_code=403, detail="Unclassified route")
    return rule


def validate_route_inventory(app: FastAPI) -> None:
    actual: dict[tuple[str, str], APIRoute] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            raise RuntimeError(
                f"unclassified framework route {getattr(route, 'path', '<unknown>')}"
            )
        for method in route.methods or ():
            if method in {"HEAD", "OPTIONS"}:
                continue
            key = (method, route.path)
            if key in actual:
                raise RuntimeError(f"duplicate application route {key}")
            actual[key] = route

    expected = set(ROUTE_AUTHORIZATION)
    missing = sorted(set(actual) - expected)
    extra = sorted(expected - set(actual))
    if missing or extra:
        details = []
        if missing:
            details.append(f"unclassified routes: {missing}")
        if extra:
            details.append(f"stale route rules: {extra}")
        raise RuntimeError("; ".join(details))

    for key, route in actual.items():
        rule = ROUTE_AUTHORIZATION[key]
        authorizers = [
            dependency.call
            for dependency in route.dependant.dependencies
            if getattr(dependency.call, "__makersvault_session_authorizer__", False)
        ]
        if rule.kind is AccessKind.SESSION and len(authorizers) != 1:
            raise RuntimeError(f"protected route {key} requires exactly one session authorizer")
        if rule.kind is not AccessKind.SESSION and authorizers:
            raise RuntimeError(f"non-session route {key} cannot use session authorization")
