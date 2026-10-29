"""The one seam between a destructive route and the snapshot provider layer.

Three route actions destroy library content: a folder delete, a trash purge and
a bulk asset delete. All three go through this module, so the decision "take a
snapshot first, proceed without one, or refuse" is made once, in one place, and
a route can only inherit it. A single-asset delete takes no snapshot: the trash
keeps it restorable, and a snapshot there would be per click rather than per
gesture.

Two entry points, deliberately different in kind:

* ``describe(reason)`` is PURE. It answers "what would happen" for a dialog
  without taking anything, writing anything or raising: it reads the policy from
  ``config`` at call time, asks ``storage_capabilities.detect()`` once, and
  builds the notice. It never constructs a provider, because a provider reads
  the four retention settings when it is constructed and a preview must not pay
  for that.
* ``guard(reason, target, ctx=...)`` ACTS. It is called by the route after every
  gate the handler owns (404, confirmation, a running scan) and before the
  mutation, so a refused operation has changed nothing.

The ``ctx`` handed to ``provider.create()`` on the three destructive routes is
always ``None``, and that is load-bearing. A provider writes
``snapshot.create``/``snapshot.prune`` rows when it is given a context, and
``POST /snapshots`` does give it one, so ``snapshot.create``,
``snapshot.prune`` and ``snapshot.delete`` are route actions today. Here on a
destructive route the guard hands the provider ``None`` and writes exactly one
row itself (``destructive.snapshot_taken`` or ``destructive.snapshot_missed``),
and the snapshot's exact name travels in that row's ``detail``. So each
destructive request owns one honest audit fact, and no provider row is written
on those three routes -- which is why ``audit.ROUTE_ACTIONS`` can name the
destructive action and the snapshot action in the same tuple without a provider
ever writing a row there.

The policy table (``SNAPSHOT_POLICY_PREDELETE``, ``SNAPSHOT_POLICY_PREPURGE``,
``SNAPSHOT_POLICY_PREBULK``; ``warn`` for a folder delete, ``strict`` for the
other two):

* capability available -> take the snapshot, whatever the policy says.
* capability unavailable -> ``warn`` proceeds and says so; ``strict`` refuses
  **only** when ``SNAPSHOT_REQUIRE_CAPABILITY`` is set. Without that switch a
  strict policy still proceeds, because an advertised, audited absence is not a
  failure: on ext4 or tmpfs there is no snapshot method at all, and Empty trash
  must stay possible. The refusal is the operator's explicit choice, not the
  default.
* a real failure while taking one (a path defect, a name collision, the
  ``.snap`` directory vanishing between detection and create) is never a
  capability miss. A collision or a path escape raises whatever the policy says;
  ``SnapshotUnavailable`` and any other ``SnapshotError`` refuse under
  ``strict`` and proceed under ``warn``, after the missed row is written.

The exception mapping lives here, in one ordered tuple, because the app has no
global handler for this hierarchy: ``SnapshotPathError`` is a 400,
``SnapshotNotFound`` a 404, ``SnapshotUnavailable`` and ``SnapshotExists`` 409s,
and any other ``SnapshotError`` a 500.

Audit rows are fail-loud: ``audit.record`` raises and nothing catches it, so an
audit failure propagates unchanged (a 500) with nothing mutated. A ``None``
context writes no row at all, mirroring ``snapshots._emit``, so a caller that is
not on a request path keeps working.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

import audit
import config
import snapshots
import storage_capabilities
from schemas import SnapshotNoticeOut

NAME_PATTERN = "<YYYYmmddTHHMMSSZ>-{reason}-<6 hex>"

# The destructive operations, in the order the taxonomy lists them.
OPERATIONS: tuple[snapshots.SnapshotReason, ...] = (
    snapshots.SnapshotReason.PRE_DELETE,
    snapshots.SnapshotReason.PRE_PURGE,
    snapshots.SnapshotReason.PRE_BULK,
)

_POLICY_ATTRIBUTES = {
    snapshots.SnapshotReason.PRE_DELETE: "SNAPSHOT_POLICY_PREDELETE",
    snapshots.SnapshotReason.PRE_PURGE: "SNAPSHOT_POLICY_PREPURGE",
    snapshots.SnapshotReason.PRE_BULK: "SNAPSHOT_POLICY_PREBULK",
}

_STATUS = (
    (snapshots.SnapshotPathError, 400),
    (snapshots.SnapshotNotFound, 404),
    (snapshots.SnapshotUnavailable, 409),
    (snapshots.SnapshotExists, 409),
)


def policy_for(reason: snapshots.SnapshotReason) -> str:
    """The policy in force for ``reason``, read from ``config`` at call time.

    Read through the module attribute on every call, so a test (or a future
    runtime override) can patch ``config.SNAPSHOT_POLICY_*`` without reloading
    this module. A reason that names no destructive operation fails closed to
    ``strict``.
    """
    attribute = _POLICY_ATTRIBUTES.get(reason)
    if attribute is None:
        return config.SNAPSHOT_POLICY_STRICT
    return getattr(config, attribute)


def name_pattern(reason: snapshots.SnapshotReason) -> str:
    """The exact shape of the name a snapshot of ``reason`` will get.

    The name itself is minted at create time (it carries the clock), so this
    descriptive pattern is the only promise a preview can keep.
    """
    return NAME_PATTERN.format(reason=reason.value)


def status_for(error: snapshots.SnapshotError) -> int:
    """Map one ``SnapshotError`` to its HTTP status; anything unlisted is a 500.

    The one mapping: ``guard()`` and ``routers/snapshots.py`` both read it, so a
    snapshot failure cannot mean 400 on one route and 500 on another.
    """
    for error_type, status in _STATUS:
        if isinstance(error, error_type):
            return status
    return 500


def _capability() -> tuple[str, Optional[str]]:
    """(method, unavailable detail) for the library volume, one ``detect()`` per call.

    A volume that does not list the library role, or one that reports itself
    unusable, resolves to ``NO_METHOD``: the detail is the volume's own reason
    when there is one, so a preview can say why no snapshot will be taken.
    """
    for volume in storage_capabilities.detect():
        if storage_capabilities.LIBRARY_ROLE not in volume.roles:
            continue
        if volume.usable:
            return volume.snapshot_method, None
        return storage_capabilities.NO_METHOD, volume.reason
    return storage_capabilities.NO_METHOD, "no storage volume reported the library role"


def _policy_refuses(policy: str) -> bool:
    """Whether a missing capability is a refusal: strict plus the operator switch."""
    return policy == config.SNAPSHOT_POLICY_STRICT and config.SNAPSHOT_REQUIRE_CAPABILITY


def _notice(
    reason: snapshots.SnapshotReason,
    policy: str,
    capability: str,
    action: str,
    detail: Optional[str] = None,
    name: Optional[str] = None,
) -> SnapshotNoticeOut:
    """One notice, built the same way by ``describe`` and ``guard``."""
    return SnapshotNoticeOut(
        reason=reason.value,
        policy=policy,
        capability=capability,
        action=action,
        pattern=name_pattern(reason),
        name=name,
        detail=detail,
    )


def describe(reason: snapshots.SnapshotReason) -> SnapshotNoticeOut:
    """What a destructive operation would do about a snapshot; takes nothing.

    Pure and cheap: no provider is constructed, one ``detect()`` runs and
    nothing is written. It never raises, so a dialog can always render it.
    """
    policy = policy_for(reason)
    _, unavailable = _capability()
    if unavailable is None:
        return _notice(reason, policy, "available", "snapshot")
    action = "refuse" if _policy_refuses(policy) else "proceed_without"
    return _notice(reason, policy, "unavailable", action, detail=unavailable)


def _write_taken(
    reason: snapshots.SnapshotReason,
    policy: str,
    target: str,
    name: str,
    method: str,
    pruned: int,
    ctx: Optional[audit.AuditContext],
) -> None:
    """One row for a snapshot that exists; the exact name is the detail.

    ``pruned`` counts what this create's retention removed. A destructive route
    hands the provider no audit context, so no ``snapshot.prune`` row is written
    on that path: the count here is what records that a prune happened.
    """
    if ctx is None:
        return
    audit.record(
        audit.Event(
            audit.DESTRUCTIVE_SNAPSHOT_TAKEN,
            target,
            {"reason": reason.value, "policy": policy, "name": name, "method": method, "pruned": pruned},
        ),
        ctx=ctx,
    )


def _write_missed(
    reason: snapshots.SnapshotReason,
    policy: str,
    target: str,
    cause: str,
    error: Optional[str],
    ctx: Optional[audit.AuditContext],
) -> None:
    """One row for a destruction that has no snapshot, and why."""
    if ctx is None:
        return
    audit.record(
        audit.Event(
            audit.DESTRUCTIVE_SNAPSHOT_MISSED,
            target,
            {"reason": reason.value, "policy": policy, "cause": cause, "error": error},
        ),
        ctx=ctx,
    )


def _refusal(reason: snapshots.SnapshotReason, policy: str, unavailable: str) -> HTTPException:
    """The 409 for a policy that refuses to destroy without a snapshot."""
    return HTTPException(
        status_code=409,
        detail=(
            f"refusing {reason.value}: the snapshot policy is {policy} and SNAPSHOT_REQUIRE_CAPABILITY is set, "
            f"but no snapshot can be taken ({unavailable})"
        ),
    )


def guard(
    reason: snapshots.SnapshotReason,
    target: str,
    *,
    ctx: Optional[audit.AuditContext],
) -> SnapshotNoticeOut:
    """Take the pre-operation snapshot, or decide (and record) not to.

    Called after the handler's own gates and before the mutation, so every path
    out of here leaves the library untouched. ``target`` is the operation's
    subject (a folder id, ``"trash"``, ``"assets"``) and is what the audit row
    names.
    """
    policy = policy_for(reason)
    method, unavailable = _capability()

    if unavailable is not None:
        _write_missed(reason, policy, target, "unavailable", None, ctx)
        if _policy_refuses(policy):
            raise _refusal(reason, policy, unavailable)
        return _notice(reason, policy, "unavailable", "proceed_without", detail=unavailable)

    try:
        provider = snapshots.provider_for(method=method)
        # No context on purpose: the guard owns this operation's single row.
        created = provider.create(reason, ctx=None)
    except (
        snapshots.SnapshotPathError,
        snapshots.SnapshotNotFound,
        snapshots.SnapshotExists,
    ) as error:
        # A defect or a name collision, never a capability miss: refuse whatever
        # the policy says, because proceeding would hide a real bug.
        _write_missed(reason, policy, target, "failed", str(error), ctx)
        raise HTTPException(status_code=status_for(error), detail=str(error)) from error
    except snapshots.SnapshotError as error:
        # The snapshot could not be taken although the volume advertised one.
        # The row comes first: it is the only record of an attempt that failed.
        # `unavailable` means the volume has no usable method after all; anything
        # else is a failure of a method that exists, which is a different fact.
        unavailable_now = isinstance(error, snapshots.SnapshotUnavailable)
        _write_missed(reason, policy, target, "unavailable" if unavailable_now else "failed", str(error), ctx)
        if policy == config.SNAPSHOT_POLICY_STRICT:
            raise HTTPException(status_code=status_for(error), detail=str(error)) from error
        capability = "unavailable" if unavailable_now else "available"
        return _notice(reason, policy, capability, "proceed_without", detail=str(error))

    name = created.snapshot.name
    _write_taken(reason, policy, target, name, provider.method, created.prune.pruned, ctx)
    return _notice(reason, policy, "available", "snapshot", name=name)
