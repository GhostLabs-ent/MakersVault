"""BTRFS snapshots, through an opt-in privileged sidecar over HTTP.

BTRFS gives an unprivileged process no way to take a snapshot: ``btrfs
subvolume snapshot`` needs ``CAP_SYS_ADMIN``, and the API container deliberately
runs without it. So btrfs snapshotting is *opt-in*, not a default feature of
every btrfs volume: an operator who wants it runs a small sidecar next to the
API, grants that sidecar the capability and the library mount, and points the
API at it with ``SNAPSHOT_BTRFS_SIDECAR_URL``. An empty URL is the normal,
supported state -- the volume simply reports no usable snapshot method, exactly
like ``none``.

This module supplies only the two mechanics ``snapshots.SnapshotProvider`` asks
for -- materialise one snapshot, remove one snapshot -- plus a read-only probe
that says whether the sidecar will answer. Naming, retention, containment,
browsing and listing are *not* overridden here: they come from the template
provider, so a btrfs deployment behaves exactly like the CephFS one and a
snapshot name is always the template's ``<UTC stamp>-<reason>-<random suffix>``,
sent to the sidecar verbatim (never prefixed, never normalised).

``<root>/.snap`` is the store, the same directory the CephFS provider uses,
because the sidecar writes each snapshot as a read-only subvolume at
``<SNAPSHOT_BTRFS_SIDECAR_MOUNT>/.snap/<name>`` and the API sees that same mount
inside the library root. Because a snapshot is a real, read-only subvolume
directory inside the mounted library, the template's ``.snap/<name>`` view path
works unchanged, so the provider can browse and restore by copying out of it --
never by rolling the subvolume back, which would discard everything changed
since the snapshot for the whole filesystem.

The provider is constructed *probe-free*: no socket, no config read, no
subprocess at construction, because ``snapshots.provider_for`` builds a provider
on every volume it is asked about, including volumes that are not btrfs at all.
The sidecar is contacted lazily, on the first create or delete.

Real-btrfs verification -- that a real sidecar with ``CAP_SYS_ADMIN`` takes a
real subvolume snapshot, that the ``.snap/<name>`` view is browsable, and that a
real deployment accepts the token -- cannot be proven inside the API image. It
is a documented manual procedure, not CI evidence: see
``curiarium/docs/architecture/CONFIGURATION.md``, "Snapshots (BTRFS sidecar)".
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import config
import snapshots
import storage_capabilities

BTRFS_BIN = "btrfs"

# The operator docs quote this section name, and every reason below points at
# it, so an operator reading a capability report can find the fix in one hop.
CONFIGURATION_SECTION = "Snapshots (BTRFS sidecar)"

# The transport seam: (method, path, payload) -> (status, body text). Injected in
# tests so nothing here needs a live socket, and defaulted to ``http_call``.
Call = Callable[[str, str, Optional[dict[str, str]]], tuple[int, str]]


class BtrfsState(str, Enum):
    """What ``probe_sidecar`` found, in the vocabulary the docs and UI use."""

    READY = "ready"
    DISABLED = "disabled"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class BtrfsProbe:
    """One read-only answer about the configured sidecar."""

    state: BtrfsState
    url: str
    reason: str


def sidecar_settings() -> tuple[str, str]:
    """The configured (url, token), read at call time so tests can monkeypatch config."""
    url = (getattr(config, "SNAPSHOT_BTRFS_SIDECAR_URL", "") or "").strip()
    token = getattr(config, "SNAPSHOT_BTRFS_SIDECAR_TOKEN", "") or ""
    return url, token


def _disabled_reason() -> str:
    """The one disabled sentence: an empty URL is the opt-in default, not a fault."""
    return (
        "btrfs snapshots are disabled: SNAPSHOT_BTRFS_SIDECAR_URL is empty, so no snapshot sidecar is configured; "
        f"see CONFIGURATION.md ({CONFIGURATION_SECTION})"
    )


def _unreachable_reason(url: str, detail: str) -> str:
    """The one unreachable sentence shape, carrying whatever the probe actually saw."""
    return (
        f"btrfs snapshots are unreachable: the snapshot sidecar at {url} did not report ready ({detail}); "
        f"see CONFIGURATION.md ({CONFIGURATION_SECTION})"
    )


def _ready_reason(url: str) -> str:
    return f"the btrfs snapshot sidecar at {url} is ready to snapshot this volume"


def http_call(method: str, path: str, payload: Optional[dict[str, str]] = None) -> tuple[int, str]:
    """One request to the sidecar with stdlib ``urllib`` only; returns (status, body text).

    Called as ``urllib.request.urlopen(...)`` so a test can monkeypatch the
    module attribute. The bearer token is the only credential and is never
    logged. An ``HTTPError`` is the sidecar answering -- a 409 or 404 is
    meaningful -- so its status and body are returned rather than raised.
    """
    url, token = sidecar_settings()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{url.rstrip('/')}{path}", data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=config.SNAPSHOT_BTRFS_TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def probe_sidecar(root: Optional[Path] = None) -> BtrfsProbe:
    """Ask the configured sidecar ``GET /health``; read-only and never raises.

    ``root`` is the library root this API reads (``snapshot_zfs.probe_zfs`` takes
    the same argument); it is used to prove the sidecar writes the store this API
    lists. The sidecar snapshots whatever ``SNAPSHOT_BTRFS_SIDECAR_MOUNT`` names,
    so the two services must see one directory at two paths -- see
    CONFIGURATION.md. An empty URL answers DISABLED without opening a socket, so a
    deployment that never opted in pays nothing for capability detection.
    """
    url, _token = sidecar_settings()
    if not url:
        return BtrfsProbe(state=BtrfsState.DISABLED, url="", reason=_disabled_reason())
    try:
        status, body = http_call("GET", "/health", None)
    except Exception as error:
        return BtrfsProbe(state=BtrfsState.UNREACHABLE, url=url, reason=_unreachable_reason(url, str(error)))
    if not 200 <= status < 300:
        return BtrfsProbe(state=BtrfsState.UNREACHABLE, url=url, reason=_unreachable_reason(url, f"HTTP {status}"))
    try:
        report = json.loads(body)
        state = report.get("state")
    except (AttributeError, TypeError, ValueError):
        return BtrfsProbe(
            state=BtrfsState.UNREACHABLE, url=url, reason=_unreachable_reason(url, "the /health body is not a JSON object")
        )
    if state != BtrfsState.READY.value:
        return BtrfsProbe(
            state=BtrfsState.UNREACHABLE, url=url, reason=_unreachable_reason(url, f"the sidecar reported state {state!r}")
        )
    mismatch = _store_mismatch(root, report)
    if mismatch is not None:
        return BtrfsProbe(state=BtrfsState.UNREACHABLE, url=url, reason=_unreachable_reason(url, mismatch))
    return BtrfsProbe(state=BtrfsState.READY, url=url, reason=_ready_reason(url))


def _store_mismatch(root: Optional[Path], report: dict) -> Optional[str]:
    """Why the sidecar's store is not the store this API lists, or None when it is.

    One directory, two paths: a deployment that binds the same host directory
    into both services resolves this exactly when the paths agree and otherwise
    by the store the sidecar reports as existing being visible here, under
    ``<library>/.snap``. When neither holds, a create would succeed into a store
    ``list()`` never reads -- empty browse, dead retention -- so the volume is
    unreachable rather than usable.
    """
    library = Path(root) if root is not None else snapshots.library_root()
    expected = library / snapshots.SNAPSHOT_DIRNAME
    store = report.get("store")
    if not isinstance(store, str) or not store:
        return f"the /health body did not report the store it writes (this API reads {expected})"
    if Path(store) in (expected, expected.resolve()) or (report.get("store_exists") is True and expected.is_dir()):
        return None
    return (
        f"the sidecar writes {store} but this API reads {expected}: the two services are not sharing one "
        "directory, so a snapshot would land where the API can never list it"
    )


class BtrfsProvider(snapshots.SnapshotProvider):
    """The btrfs provider: two sidecar calls, and the template does the rest.

    Construction is probe-free -- no socket, no config read, no subprocess --
    because ``snapshots.provider_for`` builds a provider on every volume it is
    asked about. The URL is read lazily, on the first create or delete.

    Only ``_materialise`` and ``_delete`` are overridden: ``list``, ``create``,
    ``delete``, ``path_for``, naming and retention all come from
    ``snapshots.SnapshotProvider``. ``supports_browse`` and ``supports_restore``
    are true because a btrfs snapshot is a real read-only subvolume directory
    inside the mounted library, so the template's ``<root>/.snap/<name>`` view
    path works: browsing reads the subvolume and a restore copies out of it.
    """

    method = storage_capabilities.BTRFS_SUBVOL
    supports_browse = True
    supports_restore = True

    def __init__(
        self,
        root: Path,
        *,
        policy: Optional[snapshots.RetentionPolicy] = None,
        call: Optional[Call] = None,
    ) -> None:
        self.transport: Call = call or http_call
        super().__init__(root, policy=policy)

    def _call(self, method: str, path: str, payload: Optional[dict[str, str]] = None) -> str:
        """One sidecar call, with every wire failure mapped to a template exception.

        409 means the snapshot already exists, 404 means it does not, and a 5xx
        means the sidecar is up but cannot act -- the same "unavailable" a
        missing CephFS ``.snap`` produces -- so a caller sees one vocabulary on
        every provider. A malformed URL (no scheme) fails before any socket and
        is an unreachable sidecar too.
        """
        url, _token = sidecar_settings()
        if not url:
            raise snapshots.SnapshotUnavailable(_disabled_reason())
        try:
            status, body = self.transport(method, path, payload)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as error:
            raise snapshots.SnapshotUnavailable(_unreachable_reason(url, str(error))) from error
        if 200 <= status < 300:
            return body
        detail = body.strip()
        if status == 409:
            raise snapshots.SnapshotExists(f"the snapshot sidecar at {url} answered {method} {path} with 409: {detail}")
        if status == 404:
            raise snapshots.SnapshotNotFound(f"the snapshot sidecar at {url} has no {path}: {detail}")
        if 500 <= status < 600:
            raise snapshots.SnapshotUnavailable(_unreachable_reason(url, f"the sidecar answered {method} {path} with HTTP {status}"))
        raise snapshots.SnapshotError(
            f"the snapshot sidecar at {url} answered {method} {path} with HTTP {status}: {detail}"
        )

    def _materialise(self, target: Path) -> None:
        """Ask the sidecar for the snapshot the template named, using that name verbatim."""
        if snapshots.parse_name(target.name) is None:
            raise snapshots.SnapshotPathError(f"{target.name!r} is not a snapshot name")
        self._call("POST", "/snapshots", {"name": target.name})

    def _delete(self, target: Path) -> None:
        """Ask the sidecar to remove one snapshot; the name is the whole path."""
        if snapshots.parse_name(target.name) is None:
            raise snapshots.SnapshotPathError(f"{target.name!r} is not a snapshot name")
        self._call("DELETE", f"/snapshots/{target.name}")
