"""Snapshot providers for the library volume, and the retention that bounds them.

This is the provider layer that S1's capability report only promised. A provider
turns "this volume reported method X" into three operations -- create, list,
delete -- plus a read-only view path, and it is the only place that knows how a
snapshot is actually made. Two real methods exist today: CephFS's ``.snap``
directory and a local copy, which is a test double and never a production
provider. Everything else resolves to the null provider, so the app boots on
every volume S1 can report instead of failing on the ones nobody has written a
provider for yet.

Semantics that callers must not lose sight of:

* ``.snap`` is never created implicitly. A provider materialises a snapshot with
  ``mkdir`` inside an existing snapshot directory; when that directory is
  missing the call fails with ``SnapshotUnavailable`` and nothing is created on
  disk. On CephFS the directory is the filesystem's own affordance and its
  absence means snapshotting is not available here, not that we should make it.
* A snapshot has no database row. Nothing can be rolled back with it, so its
  audit row is written after the filesystem action and its failure is
  fail-loud: ``audit.record`` raises, and the residual window between the action
  and the row is documented here rather than hidden. ``audit.stage`` is not used
  because there is no transaction to join.
* Retention runs on create and has no opt-out. A policy is read once, when the
  provider is constructed, and every ``create`` prunes to it before returning,
  so a caller cannot fill the volume by forgetting a maintenance job.
* Containment is enforced on both ends: the source (a library path must resolve
  strictly inside the library root) and the destination (the snapshot directory
  must resolve strictly inside the library root, checked at construction, and
  every snapshot directory is re-resolved before use, so a symlink planted
  inside the store cannot escape it, and a store entry that is itself a symlink
  is refused outright rather than followed, because this module only ever writes
  real directories). Resolution happens before the check, which
  is what closes ``..`` and symlink escapes.
* A ``.snap`` on a non-CephFS volume is an ordinary writable directory, not a
  copy-on-write view. Deleting a snapshot there is therefore ``rmdir``: it
  refuses a non-empty directory, so a delete can never remove a real tree even
  when the volume is not CephFS. The local-copy double is the explicit
  exception (it ``rmtree``s its own full copy, which it and only it created).

Errors map to HTTP in one place later: ``SnapshotPathError`` is a 400,
``SnapshotNotFound`` a 404, ``SnapshotUnavailable`` and ``SnapshotExists`` are
409s, and any other ``SnapshotError`` is a 500.

Snapshot names carry the creation time so the directory listing needs no
database: ``<UTC stamp>-<reason>-<random suffix>``. Lexicographic order equals
creation order across a date boundary because the stamp is fixed width; order
*within one second* is undefined because the suffix is random.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, NoReturn, Optional

from sqlmodel import Session

import audit
import settings_service
import storage_capabilities

SNAPSHOT_DIRNAME = ".snap"

# Belt-and-braces for case-insensitive mounts (the default on macOS and on some
# Windows shares): a path component is compared casefolded, so ``.Snap`` is
# refused just like ``.snap`` even though the real check is containment.
RESERVED_COMPONENTS = ("thumbs", "bundles", ".trash", ".incoming", ".snap")

LOCAL_COPY_METHOD = "local_copy"

NAME_RE = re.compile(r"^(?P<stamp>\d{8}T\d{6}Z)-(?P<reason>[a-z][a-z0-9_]*)-(?P<suffix>[0-9a-f]{6})$")

RULE_MAX_AGE = "max_age"
RULE_KEEP = "keep"
RULE_HARD_CAP = "hard_cap"

RETENTION_KEEP_LAST_N_KEY = "snapshot_keep_last_n"
RETENTION_KEEP_DAILY_KEY = "snapshot_keep_daily"
RETENTION_MAX_AGE_DAYS_KEY = "snapshot_max_age_days"
RETENTION_HARD_CAP_KEY = "snapshot_hard_cap"

DEFAULT_KEEP_LAST_N = 20
DEFAULT_KEEP_DAILY = 7
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_HARD_CAP = 100

_RESERVED_CASEFOLD = frozenset(component.casefold() for component in RESERVED_COMPONENTS)
_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"


class SnapshotError(Exception):
    """Base for every failure here; maps to HTTP 500."""


class SnapshotPathError(SnapshotError):
    """A path is outside the root it must stay inside, or names a reserved tree; 400."""


class SnapshotNotFound(SnapshotError):
    """The named snapshot does not exist; 404."""


class SnapshotUnavailable(SnapshotError):
    """This volume has no usable snapshot method, or its snapshot directory is gone; 409."""


class SnapshotExists(SnapshotError):
    """A snapshot with this name is already there; 409."""


class SnapshotReason(str, Enum):
    """Why a snapshot was taken; part of the name, so it survives a restart."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"
    PRE_DELETE = "pre_delete"
    PRE_RESTORE = "pre_restore"


@dataclass(frozen=True)
class Snapshot:
    """One snapshot directory and what its name says about it."""

    name: str
    created_at: datetime
    reason: SnapshotReason


def _now() -> datetime:
    """The clock seam: aware UTC, monkeypatched by tests."""
    return datetime.now(timezone.utc)


def snapshot_name(reason: SnapshotReason, now: datetime, suffix: Optional[str] = None) -> str:
    """Build ``<UTC stamp>-<reason>-<suffix>`` for a snapshot taken at ``now``.

    The stamp is fixed width and UTC, so lexicographic order equals creation
    order across a date boundary. Order within one second is undefined: the
    suffix is random, not a counter.
    """
    return f"{now:{_STAMP_FORMAT}}-{reason.value}-{suffix or secrets.token_hex(3)}"


def parse_name(name: str) -> Optional[Snapshot]:
    """Read a snapshot name back; anything this module did not write is ``None``.

    Never raises: ``list`` and retention both run over whatever is in the
    directory, including directories another tool left behind.
    """
    match = NAME_RE.fullmatch(name)
    if match is None:
        return None
    try:
        reason = SnapshotReason(match.group("reason"))
    except ValueError:
        return None
    try:
        created_at = datetime.strptime(match.group("stamp"), _STAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return Snapshot(name=name, created_at=created_at, reason=reason)


@dataclass(frozen=True)
class RetentionPolicy:
    """How many snapshots to keep and for how long; validated once, at construction."""

    keep_last_n: int = DEFAULT_KEEP_LAST_N
    keep_daily: int = DEFAULT_KEEP_DAILY
    max_age_days: int = DEFAULT_MAX_AGE_DAYS
    hard_cap: int = DEFAULT_HARD_CAP

    def __post_init__(self) -> None:
        for field in ("keep_last_n", "keep_daily", "max_age_days", "hard_cap"):
            value = getattr(self, field)
            # ``bool`` is an ``int`` subclass; True is not a count.
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"the retention policy field {field} is not an integer: {value!r}")
        if self.keep_last_n < 1:
            raise ValueError(f"the retention policy field keep_last_n must be at least 1: {self.keep_last_n!r}")
        if self.keep_daily < 0:
            raise ValueError(f"the retention policy field keep_daily must be at least 0: {self.keep_daily!r}")
        if self.max_age_days < 1:
            raise ValueError(f"the retention policy field max_age_days must be at least 1: {self.max_age_days!r}")
        if self.hard_cap < 1:
            raise ValueError(f"the retention policy field hard_cap must be at least 1: {self.hard_cap!r}")


@dataclass(frozen=True)
class PruneDecision:
    """One snapshot to remove, and the rule that decided it."""

    name: str
    rule: str
    created_at: datetime


@dataclass(frozen=True)
class PrunePlan:
    """What retention would remove and what it would leave; pure data, no I/O."""

    prune: tuple[PruneDecision, ...]
    keep: tuple[str, ...]

    @property
    def pruned(self) -> int:
        return len(self.prune)

    @property
    def kept(self) -> int:
        return len(self.keep)


def _order_key(snapshot: Snapshot) -> tuple[datetime, str]:
    """Oldest first, with the name breaking ties inside one second."""
    return (snapshot.created_at, snapshot.name)


def plan_prune(
    names: Iterable[str],
    policy: RetentionPolicy,
    *,
    now: Optional[datetime] = None,
    protect: Iterable[str] = (),
) -> PrunePlan:
    """Decide what retention removes, in one pass and with no I/O.

    The cascade is age, then the keep rules, then the hard cap:

    1. Names that do not parse are dropped entirely: never pruned, never kept.
    2. ``protect`` names are exempt from every rule, including the hard cap, so
       a protected set larger than the cap is an accepted overflow.
    3. ``max_age`` prunes anything older than ``max_age_days``; age beats the
       keep rules, because an old snapshot is gone whether or not it is recent.
    4. ``keep`` protects the union of the newest ``keep_last_n`` snapshots and,
       for the newest ``keep_daily`` distinct UTC dates that have a survivor,
       the newest survivor of that date. Everything outside that union is
       pruned with ``RULE_KEEP``. 50 snapshots taken today under the default
       policy leave 20: the newest 20 are the union, all 50 share one date so
       the daily rule adds nothing, and the other 30 go.
    5. ``hard_cap`` prunes the oldest survivors that no ``protect`` name covers
       until ``len(protect) + len(kept) <= hard_cap``, with ``RULE_HARD_CAP``.
       The cap therefore beats the keep rules.

    ``now`` is expected aware UTC; with ``now`` given the clock is not read, so
    a plan is reproducible. ``prune`` is oldest first and ``keep`` newest first.
    """
    protected = frozenset(protect)
    reference = now if now is not None else _now()

    parsed: dict[str, Snapshot] = {}
    for name in names:
        snapshot = parse_name(name)
        if snapshot is not None:
            parsed[snapshot.name] = snapshot
    oldest_first = sorted(parsed.values(), key=_order_key)

    cutoff = reference - timedelta(days=policy.max_age_days)
    decisions: list[PruneDecision] = []
    survivors: list[Snapshot] = []
    for snapshot in oldest_first:
        if snapshot.name in protected:
            survivors.append(snapshot)
            continue
        if snapshot.created_at < cutoff:
            decisions.append(PruneDecision(snapshot.name, RULE_MAX_AGE, snapshot.created_at))
            continue
        survivors.append(snapshot)

    newest_first = list(reversed(survivors))
    kept = {snapshot.name for snapshot in newest_first[: policy.keep_last_n]}
    seen_days: set[date] = set()
    for snapshot in newest_first:
        if len(seen_days) >= policy.keep_daily:
            break
        day = snapshot.created_at.date()
        if day in seen_days:
            continue
        seen_days.add(day)
        kept.add(snapshot.name)

    cappable: list[Snapshot] = []
    for snapshot in newest_first:
        if snapshot.name in protected:
            continue
        if snapshot.name not in kept:
            decisions.append(PruneDecision(snapshot.name, RULE_KEEP, snapshot.created_at))
            continue
        cappable.append(snapshot)

    overflow = sum(1 for snapshot in survivors if snapshot.name in protected) + len(cappable) - policy.hard_cap
    capped: set[str] = set()
    for snapshot in reversed(cappable):
        if overflow <= 0:
            break
        decisions.append(PruneDecision(snapshot.name, RULE_HARD_CAP, snapshot.created_at))
        capped.add(snapshot.name)
        overflow -= 1

    decisions.sort(key=lambda decision: (decision.created_at, decision.name))
    return PrunePlan(
        prune=tuple(decisions),
        keep=tuple(
            snapshot.name
            for snapshot in newest_first
            if (snapshot.name in kept or snapshot.name in protected) and snapshot.name not in capped
        ),
    )


def _setting_int(key: str) -> Optional[int]:
    """One stored retention setting, or None when the row is missing or blank."""
    raw = settings_service.get_setting(key)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"the setting {key} is not an integer") from error


def _with_default(value: Optional[int], default: int) -> int:
    """A missing or blank row falls back to the module default.

    ``keep_daily`` may legitimately be 0, so ``or`` cannot be used here: a stored
    zero must reach the validator and be honoured, not be replaced silently.
    """
    return default if value is None else value


def retention_policy() -> RetentionPolicy:
    """The configured policy; a missing row falls back, a broken row raises.

    A stored value that is not an integer, or one the policy refuses, is a
    ``ValueError`` rather than a silent default: guessing here would quietly
    change how much of the volume is kept.
    """
    return RetentionPolicy(
        keep_last_n=_with_default(_setting_int(RETENTION_KEEP_LAST_N_KEY), DEFAULT_KEEP_LAST_N),
        keep_daily=_with_default(_setting_int(RETENTION_KEEP_DAILY_KEY), DEFAULT_KEEP_DAILY),
        max_age_days=_with_default(_setting_int(RETENTION_MAX_AGE_DAYS_KEY), DEFAULT_MAX_AGE_DAYS),
        hard_cap=_with_default(_setting_int(RETENTION_HARD_CAP_KEY), DEFAULT_HARD_CAP),
    )


def set_retention_policy(policy: RetentionPolicy, *, session: Optional[Session] = None) -> None:
    """Validate and persist all four keys; nothing is written when validation fails.

    The policy is rebuilt from its four fields first, so even an object that
    bypassed ``__post_init__`` cannot reach the settings table. With ``session``
    given the four writes join the caller's transaction, which is what lets a
    settings change and its audit row commit together.
    """
    validated = RetentionPolicy(
        keep_last_n=policy.keep_last_n,
        keep_daily=policy.keep_daily,
        max_age_days=policy.max_age_days,
        hard_cap=policy.hard_cap,
    )
    values = (
        (RETENTION_KEEP_LAST_N_KEY, validated.keep_last_n),
        (RETENTION_KEEP_DAILY_KEY, validated.keep_daily),
        (RETENTION_MAX_AGE_DAYS_KEY, validated.max_age_days),
        (RETENTION_HARD_CAP_KEY, validated.hard_cap),
    )
    if session is not None:
        for key, value in values:
            settings_service.set_setting(key, str(value), session=session)
        return
    import db

    with Session(db.engine) as own:
        for key, value in values:
            settings_service.set_setting(key, str(value), session=own)
        own.commit()


def library_root() -> Path:
    """Resolve the library root at call time so tests can monkeypatch ``db.STORAGE``."""
    import db

    return Path(db.STORAGE)


def _refuse_reserved(path: str | Path, parts: tuple[str, ...]) -> None:
    for part in parts:
        if part.casefold() in _RESERVED_CASEFOLD:
            raise SnapshotPathError(f"{str(path)!r} contains the reserved component {part!r}")


def assert_library_path(path: str | Path, root: Optional[Path] = None) -> Path:
    """Resolve a library-relative path and prove it is strictly inside the root.

    Absolute inputs and reserved components are refused before resolution, then
    the resolved candidate must have the root among its parents: resolution
    happens first, so ``..`` sequences and symlinks that point outside have
    nothing left to slip through. Equal to the root is refused as well.
    """
    base = (Path(root) if root is not None else library_root()).resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        raise SnapshotPathError(f"{str(path)!r} is an absolute path; a library path is relative")
    _refuse_reserved(path, candidate.parts)
    resolved = (base / candidate).resolve()
    if base not in resolved.parents:
        raise SnapshotPathError(f"{str(path)!r} resolved to {resolved}, which is not inside the library root {base}")
    return resolved


def resolve_view_path(view_root: Path, relpath: str | Path = "") -> Path:
    """Resolve a read-only path inside one snapshot view; the root itself is allowed."""
    base = Path(view_root).resolve()
    candidate = Path(relpath)
    if candidate.is_absolute():
        raise SnapshotPathError(f"{str(relpath)!r} is an absolute path; a snapshot path is relative")
    _refuse_reserved(relpath, candidate.parts)
    resolved = (base / candidate).resolve()
    if resolved != base and base not in resolved.parents:
        raise SnapshotPathError(f"{str(relpath)!r} resolved to {resolved}, which is not inside the snapshot {base}")
    return resolved


@dataclass(frozen=True)
class SnapshotCreated:
    """What one ``create`` did: the snapshot, and the retention it triggered."""

    snapshot: Snapshot
    prune: PrunePlan


def _emit(ctx: Optional[audit.AuditContext], *events: audit.Event) -> None:
    """Write fail-loud events; a ``None`` context is the one no-op.

    ``audit.stage`` no-ops on ``None``, but ``audit.record`` requires a context,
    so the guard has to live here.
    """
    if ctx is None or not events:
        return
    audit.record(*events, ctx=ctx)


class SnapshotProvider:
    """One snapshot method on one root; the shared sequence, not the mechanics.

    The base class owns naming, containment, retention and audit, and leaves two
    steps to the provider: materialising one directory and removing one
    directory. ``snapshot_root`` exists so a caller can point the store
    elsewhere inside the root, but it must stay inside the root and is never
    created here.
    """

    method: str = storage_capabilities.NO_METHOD
    supports_browse: bool = False
    supports_restore: bool = False

    def __init__(
        self,
        root: Path,
        *,
        policy: Optional[RetentionPolicy] = None,
        snapshot_root: Optional[Path] = None,
    ) -> None:
        self.root = Path(root).resolve()
        # Resolved once, at construction: a create never re-reads the settings
        # table behind the caller's back.
        self.policy = policy or retention_policy()
        store = snapshot_root if snapshot_root is not None else self.root / SNAPSHOT_DIRNAME
        self.snapshot_dir = Path(store).resolve()
        if self.root not in self.snapshot_dir.parents:
            raise SnapshotPathError(
                f"the snapshot directory {self.snapshot_dir} is not strictly inside the library root {self.root}"
            )

    def create(
        self,
        reason: SnapshotReason = SnapshotReason.MANUAL,
        *,
        ctx: Optional[audit.AuditContext] = None,
    ) -> SnapshotCreated:
        """Take one snapshot, prune to the policy, then write the audit rows.

        Retention is unconditional: there is no argument that turns it off. The
        audit rows are written last and fail loud, because the snapshot already
        exists on disk by then.
        """
        # The name carries one-second precision, so the time reported back is
        # truncated to match it: the returned snapshot is the one ``list`` sees.
        # The same instant is the retention reference, so one create reads the
        # clock once and its name and cutoff cannot disagree.
        created_at = _now().replace(microsecond=0)
        name = snapshot_name(reason, created_at)
        target = self._new_path(name)
        try:
            self._materialise(target)
        except FileExistsError as error:
            raise SnapshotExists(f"a snapshot named {name} already exists in {self.snapshot_dir}") from error
        plan = plan_prune(self._names(), self.policy, now=created_at, protect=[name])
        for decision in plan.prune:
            self._remove(decision.name)
        _emit(
            ctx,
            audit.Event(
                audit.SNAPSHOT_CREATE,
                name,
                {"reason": reason.value, "method": self.method, "pruned": plan.pruned},
            ),
            *(
                audit.Event(audit.SNAPSHOT_PRUNE, decision.name, {"rule": decision.rule, "trigger": name})
                for decision in plan.prune
            ),
        )
        return SnapshotCreated(snapshot=Snapshot(name=name, created_at=created_at, reason=reason), prune=plan)

    def list(self) -> list[Snapshot]:
        """This provider's snapshots, oldest first.

        Only names this module wrote are listed, so a directory left here by
        another tool is invisible and immune to retention. Only directories
        count: this module writes nothing but directories, so a regular file or
        a symlink with a parseable name is invisible and immune to retention
        too. A missing snapshot directory is an empty list: the volume has no
        snapshots, not an error.
        """
        try:
            entries = list(os.scandir(self.snapshot_dir))
        except FileNotFoundError:
            return []
        parsed = (parse_name(entry.name) for entry in entries if entry.is_dir(follow_symlinks=False))
        return sorted((snapshot for snapshot in parsed if snapshot is not None), key=_order_key)

    def delete(self, name: str, *, ctx: Optional[audit.AuditContext] = None) -> None:
        """Remove one snapshot, then write its audit row (fail-loud)."""
        self._remove(name)
        _emit(ctx, audit.Event(audit.SNAPSHOT_DELETE, name, {"method": self.method}))

    def path_for(self, name: str, relpath: str | Path = "") -> Path:
        """The read-only path of ``relpath`` inside the named snapshot.

        An empty ``relpath`` is the snapshot directory itself. A name this module
        did not write, or a snapshot directory that resolves outside the store (a
        planted symlink), is ``SnapshotPathError``. A snapshot that is not there
        is ``SnapshotNotFound`` -- including on a volume with no snapshot
        directory at all, because browsing asks for a snapshot that does not
        exist rather than for a method that cannot browse.
        """
        return resolve_view_path(self._view_root(name), relpath)

    def _names(self) -> list[str]:
        return [snapshot.name for snapshot in self.list()]

    def _entry(self, name: str) -> Path:
        """The store entry for ``name``: parse-checked, and never a symlink.

        A symlinked entry is refused outright, before any resolution, because
        this module only ever writes real directories: a ``.snap/<name>`` link
        was planted, and following it would either escape the store or alias a
        sibling snapshot, so ``delete(nameA)`` would remove nameB's real tree.
        """
        if parse_name(name) is None:
            raise SnapshotPathError(f"{name!r} is not a snapshot name")
        entry = self.snapshot_dir / name
        if entry.is_symlink():
            raise SnapshotPathError(
                f"the snapshot entry {entry} is a symlink; this provider only ever writes real directories"
            )
        return entry

    def _view_root(self, name: str) -> Path:
        """Validate a name and return its snapshot directory, proven inside the store.

        The entry itself must be a real directory (``_entry`` refuses a symlink),
        and the resolved path must still have the store among its parents, so a
        symlinked parent cannot escape either.
        """
        resolved = self._entry(name).resolve()
        if self.snapshot_dir not in resolved.parents:
            raise SnapshotPathError(f"{name!r} resolved to {resolved}, outside the snapshot directory {self.snapshot_dir}")
        if not resolved.is_dir():
            raise SnapshotNotFound(f"the snapshot {name!r} is not in {self.snapshot_dir}")
        return resolved

    def _new_path(self, name: str) -> Path:
        """Validate a name and return its not-yet-existing directory.

        ``_entry`` refuses a symlinked entry, so a planted link can never be
        materialised over or removed through this path.
        """
        target = self._entry(name).resolve()
        if self.snapshot_dir not in target.parents:
            raise SnapshotPathError(f"{name!r} resolved to {target}, outside the snapshot directory {self.snapshot_dir}")
        if not self.snapshot_dir.is_dir():
            raise SnapshotUnavailable(
                f"the snapshot directory {self.snapshot_dir} does not exist; this provider never creates it"
            )
        return target

    def _remove(self, name: str) -> None:
        """Remove one snapshot directory, without an audit row."""
        self._delete(self._new_path(name))

    def _materialise(self, target: Path) -> None:
        raise NotImplementedError

    def _delete(self, target: Path) -> None:
        raise NotImplementedError


class CephFsSnapdirProvider(SnapshotProvider):
    """CephFS ``.snap``: ``mkdir`` under the snap directory makes a CoW view.

    The filesystem does the copying, so create is one syscall and the copy is
    free. Delete is ``rmdir``, which the kernel refuses on a non-empty directory:
    on a non-CephFS volume (where ``.snap`` is an ordinary directory) a delete
    can therefore never remove a real tree. An ``OSError`` is wrapped, not
    swallowed, because ENOTEMPTY here means "this is not the filesystem you
    think it is", not "try again".
    """

    method = storage_capabilities.CEPHFS_SNAPDIR
    supports_browse = True
    supports_restore = True

    def _materialise(self, target: Path) -> None:
        os.mkdir(target)

    def _delete(self, target: Path) -> None:
        try:
            os.rmdir(target)
        except FileNotFoundError as error:
            raise SnapshotNotFound(f"the snapshot {target.name!r} is not in {self.snapshot_dir}") from error
        except OSError as error:
            raise SnapshotError(f"could not remove the snapshot {target}: {error}") from error


class LocalCopyProvider(SnapshotProvider):
    """A full ``copytree`` of the root: a test double, never a production provider.

    There is no CoW here. Every snapshot is a complete second copy of the
    library, which is wasteful and has none of the guarantees a real snapshot
    has: it does not preserve ownership, ACLs or xattrs. ``copytree`` copies
    with ``copy2``, so modes and mtimes are preserved, symlinks are copied as
    symlinks (never followed out of the root), and the snapshot store itself is
    excluded from the walk so a copy cannot recurse into the snapshots it is
    creating.
    """

    method = LOCAL_COPY_METHOD
    supports_browse = True
    supports_restore = True

    def _materialise(self, target: Path) -> None:
        shutil.copytree(self.root, target, symlinks=True, ignore=self._ignore_snapshot_store)

    def _delete(self, target: Path) -> None:
        if not target.is_dir():
            raise SnapshotNotFound(f"the snapshot {target.name!r} is not in {self.snapshot_dir}")
        shutil.rmtree(target)

    def _ignore_snapshot_store(self, directory, names) -> list[str]:
        """Skip the snapshot store itself, at whatever depth it sits.

        ``copytree`` calls this for every directory it walks, so the store is
        matched by its resolved path rather than by name at the root: a nested
        ``snapshot_root`` (or one reached through a symlinked parent) must not be
        copied into the copy it is creating. A root-level ``.snap`` is always
        skipped too, even when the store lives elsewhere, because it is this
        module's own tree by convention.
        """
        current = Path(directory).resolve()
        return [
            name
            for name in names
            if (current / name).resolve() == self.snapshot_dir or (current == self.root and name == SNAPSHOT_DIRNAME)
        ]


class NullProvider(SnapshotProvider):
    """The provider for every volume without a snapshot method: it refuses, calmly.

    It exists so ``provider_for`` never raises for an unknown method: the app
    boots on ext4, zfs and btrfs today, and asks this provider what it can do
    (nothing) instead of crashing. ``list`` is empty rather than an error
    because "this volume has no snapshots" is a true answer.
    """

    method = storage_capabilities.NO_METHOD
    supports_browse = False
    supports_restore = False

    def create(
        self,
        reason: SnapshotReason = SnapshotReason.MANUAL,
        *,
        ctx: Optional[audit.AuditContext] = None,
    ) -> SnapshotCreated:
        self._unavailable("take")

    def delete(self, name: str, *, ctx: Optional[audit.AuditContext] = None) -> None:
        self._unavailable("delete")

    def path_for(self, name: str, relpath: str | Path = "") -> Path:
        self._unavailable("browse")

    def list(self) -> list[Snapshot]:
        return []

    def _unavailable(self, operation: str) -> NoReturn:
        raise SnapshotUnavailable(
            f"this volume has no snapshot method ({self.method}); cannot {operation} snapshots under {self.root}"
        )


def provider_for(
    root: Optional[Path] = None,
    method: str = storage_capabilities.NO_METHOD,
    *,
    policy: Optional[RetentionPolicy] = None,
    snapshot_root: Optional[Path] = None,
) -> SnapshotProvider:
    """Build the provider for a capability method; unknown methods get the null one.

    ``NO_METHOD``, ``zfs_dataset``, ``btrfs_subvol`` and any string nobody has
    implemented all resolve to ``NullProvider`` without raising, so the app boots
    on every volume S1 can report and a later slice adds a method by adding a
    branch here, not by making boot conditional.
    """
    library = Path(root) if root is not None else library_root()
    if method == storage_capabilities.CEPHFS_SNAPDIR:
        return CephFsSnapdirProvider(library, policy=policy, snapshot_root=snapshot_root)
    if method == LOCAL_COPY_METHOD:
        return LocalCopyProvider(library, policy=policy, snapshot_root=snapshot_root)
    return NullProvider(library, policy=policy, snapshot_root=snapshot_root)
