"""Every snapshot HTTP operation; ``routers/snapshots.py`` is a thin shell over this.

"Never write into the live tree" means two things here, and only two: a restore
never writes a file's original live path, and it never clobbers an existing path.
``STORAGE/recovered/...`` is inside the storage root *by design* -- that is where
a recovery lands so the library scan registers it. The two clauses are not
contradictory: the recovery tree is a new name, never a live asset's name.

The most dangerous line in this ticket is the publish step of a restore. The
snapshot bytes are copied into a hidden ``.part`` sibling **inside ``recovered/``**
and then published with ``asset_service._move_without_clobber``, which *moves*
(``os.link`` then ``unlink``). Copying ``snapshot -> recovered`` directly through
that arbiter would unlink the snapshot source and destroy the snapshot, so the
source is only ever read (``shutil.copy2``) and only the ``.part`` copy is moved.

Containment is S2's, not a second implementation: ``provider.path_for()`` (which
resolves through ``snapshots.resolve_view_path``) confines the source, and
``snapshots.assert_library_path()`` confines the destination. A second
implementation here could only drift from those two.

``recovered/`` must stay scan-visible, which is why it is NOT in
``library_scan.RESERVED_DIRS``: a recovery is only useful once the scan registers
it. The ``.part`` sibling is a dot *file*: ``_walk_storage`` prunes hidden
*directories*, and the dot-name filter that drops dot entries lives in the
registering loop (``library_scan.py``, the ``entry.name.startswith(".")`` guard),
so a run with ``include_hidden=True`` keeps it visible. It is removed in a
``finally`` either way.

A restore never 409s because a scan is running: the bytes are already copied by
then, so it reports ``scan_started: false`` rather than refusing work it has
already done.
"""

from __future__ import annotations

import os
import posixpath
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import audit
import seams
import snapshots
import storage_capabilities

# Deliberate private import: ``_move_without_clobber`` is the existing no-clobber
# arbiter for this storage tree, and the point of reusing it is that a restore
# inherits its guarantee instead of growing a second one that can disagree.
from asset_service import _move_without_clobber
from schemas import (
    SnapshotBrowseOut,
    SnapshotCreatedOut,
    SnapshotDeleteOut,
    SnapshotEntryOut,
    SnapshotListOut,
    SnapshotOut,
    SnapshotPruneOut,
    SnapshotRestoreOut,
    SnapshotRetentionIn,
    SnapshotRetentionOut,
)

RECOVERED_DIRNAME = "recovered"
PART_SUFFIX = ".part"


def library_method() -> str:
    """The snapshot method the library volume reports, or NO_METHOD when none does.

    Calls ``storage_capabilities.detect()`` with no arguments, through the module
    attribute, because the test fakes install a zero-argument lambda.
    """
    for volume in storage_capabilities.detect():
        if storage_capabilities.LIBRARY_ROLE not in volume.roles:
            continue
        return volume.snapshot_method if volume.usable else storage_capabilities.NO_METHOD
    return storage_capabilities.NO_METHOD


def provider() -> snapshots.SnapshotProvider:
    """Build the provider for the library volume, through ``snapshots.provider_for``.

    Called as a module attribute, never imported by name: the fakes monkeypatch
    ``snapshots.provider_for``.
    """
    return snapshots.provider_for(method=library_method())


def snapshot_out(snapshot: snapshots.Snapshot) -> SnapshotOut:
    """One snapshot as the API reports it: aware UTC, and an age floored at 0."""
    created_at = snapshot.created_at.astimezone(timezone.utc)
    age = int((datetime.now(timezone.utc) - created_at).total_seconds())
    return SnapshotOut(
        name=snapshot.name,
        created_at=created_at.isoformat(),
        age_seconds=max(0, age),
        reason=snapshot.reason.value,
    )


def list_out() -> SnapshotListOut:
    """This volume's snapshots, oldest first, with what the provider can do."""
    current = provider()
    return SnapshotListOut(
        snapshots=[snapshot_out(snapshot) for snapshot in current.list()],
        method=current.method,
        supports_browse=current.supports_browse,
        supports_restore=current.supports_restore,
    )


def create_out(ctx: Optional[audit.AuditContext]) -> SnapshotCreatedOut:
    """Take a manual snapshot, prune to the policy, and report both.

    Passing ``ctx`` is correct here and only here: ``POST /snapshots`` owns the
    provider's ``snapshot.create``/``snapshot.prune`` rows now that the action is
    a route action. ``snapshot_guard`` keeps passing ``ctx=None`` because it
    writes its own ``destructive.snapshot_*`` row instead.
    """
    created = provider().create(snapshots.SnapshotReason.MANUAL, ctx=ctx)
    return SnapshotCreatedOut(
        snapshot=snapshot_out(created.snapshot),
        prune=SnapshotPruneOut(
            pruned=created.prune.pruned,
            kept=created.prune.kept,
            names=[decision.name for decision in created.prune.prune],
        ),
    )


def delete_out(name: str, ctx: Optional[audit.AuditContext]) -> SnapshotDeleteOut:
    """Remove one snapshot; the provider writes the row and its failures propagate."""
    provider().delete(name, ctx=ctx)
    return SnapshotDeleteOut(ok=True, name=name)


def retention_out() -> SnapshotRetentionOut:
    """The policy in force; a stored row that does not parse raises ``ValueError``."""
    policy = snapshots.retention_policy()
    return SnapshotRetentionOut(
        keep_last_n=policy.keep_last_n,
        keep_daily=policy.keep_daily,
        max_age_days=policy.max_age_days,
        hard_cap=policy.hard_cap,
    )


def retention_from(body: SnapshotRetentionIn) -> snapshots.RetentionPolicy:
    """Build a validated policy from the request body; ValueError is the caller's 400."""
    return snapshots.RetentionPolicy(
        keep_last_n=body.keep_last_n,
        keep_daily=body.keep_daily,
        max_age_days=body.max_age_days,
        hard_cap=body.hard_cap,
    )


def browse_out(name: str, path: str) -> SnapshotBrowseOut:
    """One directory of one snapshot, directories first and then by name."""
    root = provider().path_for(name, path)
    if not root.is_dir():
        raise snapshots.SnapshotPathError(f"{path!r} in snapshot {name!r} is not a directory")
    normalised = _normalised(path)
    entries: List[SnapshotEntryOut] = []
    for entry in os.scandir(root):
        is_dir = entry.is_dir(follow_symlinks=False)
        try:
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            # A vanished or unreadable entry is still listed, with no metadata: a
            # browse that hid it would disagree with the next browse.
            stat = None
        entries.append(
            SnapshotEntryOut(
                name=entry.name,
                path=posixpath.join(normalised, entry.name),
                is_dir=is_dir,
                size=None if is_dir or stat is None else stat.st_size,
                modified_at=None if stat is None else datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            )
        )
    # Directories before files, then name within each group: the listing reads
    # like a file manager without the client having to sort.
    entries.sort(key=lambda entry: (0 if entry.is_dir else 1, entry.name))
    return SnapshotBrowseOut(snapshot=name, path=normalised, entries=entries)


def restore_out(name: str, path: str, ctx: Optional[audit.AuditContext]) -> SnapshotRestoreOut:
    """Copy ``path`` out of a snapshot into ``recovered/`` and start a scan.

    Nothing is written before every destination is known to be free, and no
    snapshot byte is ever moved: the publication step moves only the ``.part``
    copy inside ``recovered/``.
    """
    current = provider()
    source = current.path_for(name, path)
    # ``path_for`` proves containment but does not require the path to exist: a
    # caller-supplied path that is not in the snapshot is a 404 here, not a
    # FileNotFoundError from the copy loop.
    if not source.exists():
        raise snapshots.SnapshotNotFound(f"{path!r} is not in snapshot {name!r}")
    normalised = _normalised(path)
    if normalised == "":
        destination = f"{RECOVERED_DIRNAME}/{name}"
    else:
        destination = f"{RECOVERED_DIRNAME}/{name}/{normalised}"
    dest = snapshots.assert_library_path(destination)

    plan = _restore_plan(source, dest)

    # All-or-nothing preflight: the first occupied destination refuses the whole
    # restore before a byte is written. It is best-effort against a concurrent
    # writer -- a mid-flight collision can still leave a partial directory
    # restore behind, but never a clobber.
    for _, dest_file in plan:
        if dest_file.exists() or dest_file.is_symlink():
            raise _refuse_existing(destination, dest, dest_file)
        blocked = _blocked_ancestor(dest, dest_file)
        if blocked is not None:
            raise _refuse_existing(destination, dest, blocked)

    if not plan:
        # An empty directory is a legitimate recovery: materialise the
        # destination so the path the response names actually exists.
        if dest.exists() and not dest.is_dir():
            raise _refuse_existing(destination, dest, dest)
        _make_directories(dest, destination)

    files = 0
    size = 0
    for source_file, dest_file in plan:
        part = dest_file.with_name(f".{dest_file.name}{PART_SUFFIX}")
        # The directory this file publishes into, labelled library-relative. For a
        # single-file restore `dest` is the file itself, so the label is derived
        # from the file's own destination rather than from `dest`.
        directory_label = posixpath.dirname(_label_of(destination, dest, dest_file))
        try:
            _make_directories(part.parent, directory_label)
            # The snapshot is only ever READ: ``copy2`` reads the source and
            # writes the sibling, it never touches the source name.
            shutil.copy2(source_file, part)
            # Publishing through ``_move_without_clobber`` from ``part`` to
            # ``dest_file`` is safe because both names are inside ``recovered/``.
            # Doing it ``source -> dest_file`` would unlink the snapshot source
            # and destroy the snapshot.
            if not _move_without_clobber(part, dest_file):
                raise _refuse_existing(destination, dest, dest_file)
        finally:
            # No residue, even on failure: the copy is either published or gone.
            # A blocked parent path means there is no `.part` to remove, and the
            # refusal that caused it must not be masked by the cleanup.
            try:
                part.unlink(missing_ok=True)
            except NotADirectoryError:
                pass
        files += 1
        size += source_file.stat().st_size

    # Never raise when a scan is already running: the bytes are copied by now, so
    # ``False`` is the honest answer rather than a refusal to report success.
    scan_started = bool(seams.start_scan())

    # One row, fail-loud, and only when there is a request to hang it on:
    # ``audit.record`` requires a context, mirroring ``snapshots._emit``.
    if ctx is not None:
        audit.record(
            audit.Event(
                audit.SNAPSHOT_RESTORE,
                name,
                {
                    "path": normalised,
                    "destination": destination,
                    "files": files,
                    "bytes": size,
                    "scan_started": scan_started,
                },
            ),
            ctx=ctx,
        )

    return SnapshotRestoreOut(
        snapshot=name,
        path=normalised,
        destination=destination,
        files=files,
        bytes=size,
        scan_started=scan_started,
    )


def _normalised(path: str) -> str:
    """The echoed snapshot-relative path: "" is the snapshot root, else POSIX."""
    candidate = posixpath.normpath(path) if path else ""
    return "" if candidate == "." else candidate


def _restore_plan(source: Path, dest: Path) -> List[Tuple[Path, Path]]:
    """Every ``(source file, destination file)`` the restore will copy.

    A file source is one pair. A directory source is walked without following
    symlinks (``followlinks=False``), and each symlink is skipped: a restore
    copies bytes, it never plants a link and never follows one out of the
    snapshot.
    """
    if not source.is_dir():
        return [(source, dest)]
    plan: List[Tuple[Path, Path]] = []
    for root, _dirs, names in os.walk(source, followlinks=False):
        for entry_name in names:
            source_file = Path(root) / entry_name
            if source_file.is_symlink():
                continue
            plan.append((source_file, dest / source_file.relative_to(source)))
    return plan


def _refuse_existing(destination: str, dest: Path, dest_file: Path) -> snapshots.SnapshotExists:
    """The 409 for an occupied destination; a restore never overwrites anything."""
    return snapshots.SnapshotExists(
        f"{_label_of(destination, dest, dest_file)} already exists; "
        "a restore never overwrites - move or delete it first"
    )


def _make_directories(path: Path, label: str) -> None:
    """Create one directory and its parents, refusing rather than failing on a blockage.

    A regular file anywhere on the way (``<storage>/recovered`` itself, say) makes
    ``mkdir`` raise, and the honest answer is a 409 the caller can act on, not a
    500: nothing has been written either way.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError as error:
        raise snapshots.SnapshotExists(
            f"{label} already exists and is not a directory; a restore never overwrites - move or delete it first"
        ) from error
    except NotADirectoryError as error:
        raise snapshots.SnapshotExists(f"{label} cannot be created; a file is in the way") from error


def _blocked_ancestor(dest: Path, dest_file: Path) -> Optional[Path]:
    """The first existing non-directory on the way to ``dest_file``, if any.

    The preflight covers each file's final name; this covers the directories the
    copy has to create. A file sitting where a directory must go is a 409 naming
    that file, not a failed ``mkdir`` (a 500).
    """
    if dest_file == dest:
        return None
    for parent in dest_file.parents:
        if parent.exists() and not parent.is_dir():
            return parent
        if parent == dest:
            return None
    return None


def _label_of(destination: str, dest: Path, path: Path) -> str:
    """One path under the destination as the library-relative label a 409 names."""
    relative = path.relative_to(dest).as_posix()
    return destination if relative == "." else posixpath.join(destination, relative)
