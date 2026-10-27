"""Trash-backed destructive folder delete, and the explicit purge that follows it.

Deleting a folder must never unlink bytes. The whole directory subtree is moved
with ``os.rename`` into ``<STORAGE>/.trash/<UTC timestamp>-<sanitised name>/``
and only then are the database rows removed; an irreversible ``rm -r`` happens
only when somebody asks for a purge. Until then the bytes are recoverable with a
plain ``mv``, which is also why delete cannot depend on a wrapping transaction:
the filesystem is always changed first and the rows second, with the moves
undone if the commit fails.

Semantics that callers must not loose sight of:

* The delete is whole-subtree (``rm -r``): child folders and every asset in them
  go with the parent. Nothing outside the subtree may relocate: the storage
  template is never rendered and no metadata-relocation helper runs here.
* ``is_reference`` assets point at files outside the storage root. They lose
  their rows only; the external file is never touched, and neither is anything
  referenced by ``source_path``.
* Files that live inside the directory but have no DB row are untracked: they
  move with the directory because the directory moves. They are never
  enumerated, targeted individually, or counted.
* There are exactly two deliberate carve-outs from "nothing outside the subtree
  moves". App-owned sidecars at ``bundles/<asset_id>/`` and a tracked asset's
  managed file whose path sits outside the folder directory are moved *into* the
  trash entry (under ``.bundles/`` and ``.assets/``) so a purge can reclaim them
  and a delete cannot leave orphaned bytes behind.
* Restore is file-level only. Rows were deleted because they describe assets
  that no longer existed at delete time. Hand-moving an entry back and running a
  library rescan re-registers the files as new assets. There is no row-level
  undo and no soft-delete column: filtering every listing query through a
  ``trashed_at`` flag is a whole-library outage waiting to happen.

Every path is resolved per call from ``db.STORAGE`` / ``db.THUMBS`` rather than
bound at import, so tests can point both at temporary directories. ``THUMBS`` is
read separately from ``STORAGE``: after a monkeypatch it is not necessarily
``<STORAGE>/thumbs``.
"""

import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

import db
import file_utils
import folder_paths
from models import Asset, AssetFile, Folder

log = logging.getLogger(__name__)

TRASH_DIRNAME = ".trash"
BUNDLES_DIRNAME = "bundles"
ASSET_CARVEOUT_DIRNAME = ".assets"
BUNDLE_CARVEOUT_DIRNAME = ".bundles"

SECONDS_PER_DAY = 86400


# Paths ----------------------------------------------------------


def storage_root() -> Path:
    """Resolve the storage root at call time so tests can monkeypatch it."""
    return Path(db.STORAGE).resolve()


def thumbs_root() -> Path:
    """Resolve the thumbnail root on its own; it is not always under storage."""
    return Path(db.THUMBS).resolve()


def bundles_root() -> Path:
    """App-owned sidecar root; always a direct child of the storage root."""
    return storage_root() / BUNDLES_DIRNAME


def trash_root() -> Path:
    """Root of every trash entry; always a direct child of the storage root."""
    return storage_root() / TRASH_DIRNAME


def _strictly_inside(path: Path, root: Path) -> bool:
    return root in path.parents


def _inside_or_equal(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def resolve_inside_storage(relative: str) -> Path:
    """Resolve a folder's relative storage path and prove it is safe to move.

    A resolved path equal to the storage root itself or outside it is refused,
    which also covers absolute inputs and ``..`` sequences: resolution happens
    before the check, so there is no lexical gap to slip through. The app-owned
    ``thumbs/`` and ``bundles/`` trees are not library folders and are refused
    as well.
    """
    root = storage_root()
    candidate = (root / relative).resolve()
    if not _strictly_inside(candidate, root):
        raise HTTPException(status_code=400, detail="Folder path resolved outside the storage directory")
    for reserved in (thumbs_root(), bundles_root()):
        if _inside_or_equal(candidate, reserved):
            raise HTTPException(status_code=400, detail="Refusing to delete an app-owned storage directory")
    return candidate


def entry_name(folder_name: str, now: datetime) -> str:
    """Build a unique, filesystem-safe entry name for a delete at ``now``.

    The timestamp is UTC (``now`` is expected to be aware) and the folder name is
    sanitised and truncated so an absurd name cannot push the path over the
    filesystem limit. Two deletes of same-named folders within one second get
    ``-2``, ``-3``, ... rather than colliding.
    """
    segment = file_utils.sanitize_path_segment(folder_name, fallback="folder")[:80]
    base = f"{now:%Y%m%dT%H%M%SZ}-{segment}"
    root = trash_root()
    name = base
    suffix = 2
    while (root / name).exists():
        name = f"{base}-{suffix}"
        suffix += 1
    return name


def _relative_to_storage(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        return path.relative_to(storage_root()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_in_trash(folder: Folder) -> bool:
    """True when the folder's directory already lives under ``.trash``."""
    relative = folder.storage_path or ""
    if not relative:
        return False
    if relative.split("/", 1)[0] == TRASH_DIRNAME:
        return True
    try:
        candidate = (storage_root() / relative).resolve()
    except OSError:
        return False
    return _inside_or_equal(candidate, trash_root())


# Selection ------------------------------------------------------


def _selected_assets(session: Session, subtree_ids: set[str], relative: Optional[str]) -> List[Asset]:
    """Load every asset once and filter in Python, never with SQL ``LIKE``.

    Sanitised folder segments may legally contain ``%`` or ``_``, which a LIKE
    prefix would treat as wildcards. An asset can match both clauses (it is in a
    child folder whose path is under the parent), so each row is appended at
    most once, in id order for deterministic reporting.
    """
    prefix = f"{relative}/" if relative else None
    selected: List[Asset] = []
    for asset in session.exec(select(Asset).order_by(Asset.id)):
        if asset.folder_id in subtree_ids:
            selected.append(asset)
        elif prefix and asset.storage_path and asset.storage_path.startswith(prefix):
            selected.append(asset)
    return selected


def folder_delete_preview(session: Session, folder: Folder) -> dict:
    """Describe what a delete would remove, without touching anything.

    Read-only on purpose: the UI needs this for its confirmation modal, and a
    preview must never converge ancestors, create `.trash`, or write a row.
    """
    subtree = folder_paths.folder_subtree(session, folder.id)
    subtree_ids = {node.id for node in subtree}
    assets = _selected_assets(session, subtree_ids, folder.storage_path)
    supporting_count = sum(int(asset.supporting_file_count or 0) for asset in assets)
    return {
        "folders": len(subtree),
        "assets": len(assets),
        "files": len(assets) + supporting_count,
        "bytes": sum(int(asset.size or 0) for asset in assets),
        "in_trash": _is_in_trash(folder),
    }


# Moves ----------------------------------------------------------


def _managed_file(asset: Asset) -> Optional[Path]:
    """Resolve an asset's primary file, refusing anything outside the root.

    A symlink is skipped rather than followed: moving its target would be a
    second, unexpected relocation outside the deleted subtree.
    """
    relative = asset.storage_path or f"{asset.id}/{asset.filename}"
    root = storage_root()
    raw = root / relative
    if raw.is_symlink():
        return None
    candidate = raw.resolve()
    if candidate == root or root not in candidate.parents:
        return None
    return candidate


def _ensure_entry(entry: Optional[Path], folder_name: str, now: datetime) -> Path:
    """Return the trash entry, creating it on first actual move."""
    if entry is not None:
        return entry
    entry = trash_root() / entry_name(folder_name, now)
    entry.mkdir(parents=True, exist_ok=True)
    return entry


def _move_to_trash(
    folder: Folder,
    source: Optional[Path],
    assets: List[Asset],
    now: datetime,
    moves: list[tuple[Path, Path]],
    empty_after_move: list[Path],
) -> Optional[Path]:
    """Move the subtree and the two documented carve-outs; record every move.

    ``moves`` is an undo list of ``(moved_to, original)`` pairs, the entry move
    first so reversing it puts the directory back before the carve-outs are
    restored. ``empty_after_move`` collects directories that a carve-out leaves
    behind empty; they are removed only after the rows commit, because the
    library scan turns every leftover directory into a folder row. Returns the
    entry path, or ``None`` when nothing existed on disk (a scan-created folder
    whose directory never materialised) - the rows are still deleted then.
    """
    entry: Optional[Path] = None

    if source is not None and source.is_dir():
        entry = trash_root() / entry_name(folder.name, now)
        entry.parent.mkdir(parents=True, exist_ok=True)
        if entry.is_symlink():
            # TOCTOU: someone replaced the freshly named entry with a link.
            raise HTTPException(status_code=409, detail="Trash entry path is a symlink")
        os.rename(source, entry)
        os.utime(entry)
        moves.append((entry, source))

    for asset in assets:
        if asset.is_reference:
            # Reference assets point outside storage; only their rows go.
            continue

        bundle = bundles_root() / asset.id
        if bundle.is_dir() and not bundle.is_symlink():
            entry = _ensure_entry(entry, folder.name, now)
            target = entry / BUNDLE_CARVEOUT_DIRNAME / asset.id
            target.parent.mkdir(parents=True, exist_ok=True)
            os.rename(bundle, target)
            moves.append((target, bundle))

        managed = _managed_file(asset)
        if managed is not None and managed.is_file() and not _strictly_inside(managed, source):
            entry = _ensure_entry(entry, folder.name, now)
            target = entry / ASSET_CARVEOUT_DIRNAME / asset.id / asset.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            os.rename(managed, target)
            moves.append((target, managed))
            # A flat template or a NULL storage_path leaves the file's parent
            # directory empty; it must not survive as a future scan folder.
            if _strictly_inside(managed.parent, storage_root()):
                empty_after_move.append(managed.parent)

    return entry


def _undo_moves(moves: list[tuple[Path, Path]]) -> None:
    """Best-effort reverse of every move, newest first.

    The delete is filesystem-first, so a failed commit leaves bytes displaced.
    A crash between ``rmtree``-free rename and its undo can still desync disk and
    rows; that is why this is best effort and logged rather than raised.
    """
    for moved_to, original in reversed(moves):
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            os.rename(moved_to, original)
        except OSError:
            log.exception("Failed to undo trash move %s -> %s", moved_to, original)


def _delete_rows(session: Session, assets: List[Asset], subtree: List[Folder]) -> None:
    """Stage the row deletes: asset files, assets, then folders children-first.

    ``AssetFile`` rows go first so no dangling reference survives the asset
    delete. Folders are removed in reverse breadth-first order, which is
    children before their parents.
    """
    if assets:
        asset_ids = [asset.id for asset in assets]
        for row in session.exec(select(AssetFile).where(AssetFile.asset_id.in_(asset_ids))):
            session.delete(row)
        for asset in assets:
            session.delete(asset)
    for node in reversed(subtree):
        session.delete(node)


# Delete ---------------------------------------------------------


def trash_folder(session: Session, folder: Folder) -> dict:
    """Move a folder's subtree into the trash, then delete its rows.

    Order is fixed: move bytes, commit rows, only then unlink thumbnails. A
    failure while moving or committing reverses every move and reports a 500,
    so the caller never sees a partial delete. Emptied ancestor directories are
    deliberately left alone: an emptied parent still owns a Folder row, so
    pruning it would desynchronise database and disk.
    """
    subtree = folder_paths.folder_subtree(session, folder.id)
    subtree_ids = {node.id for node in subtree}
    # Same deliberate convergence as folder_service.move_folder: a scan-created
    # folder has no storage_path yet, and every descendant needs the parent's
    # path to decide what belongs to this subtree. Persist only, no filesystem.
    relative = folder.storage_path or folder_paths.converge_ancestor_paths(session, folder.id)

    source: Optional[Path] = None
    if relative:
        raw_source = storage_root() / relative
        if raw_source.is_symlink():
            raise HTTPException(status_code=400, detail="Refusing to delete a symlinked folder")
        source = resolve_inside_storage(relative)
        if _inside_or_equal(source, trash_root()):
            raise HTTPException(status_code=409, detail="Folder is already inside the trash")

    assets = _selected_assets(session, subtree_ids, relative)
    asset_ids = [asset.id for asset in assets]
    asset_bytes = sum(int(asset.size or 0) for asset in assets)
    now = datetime.now(timezone.utc)

    entry: Optional[Path] = None
    moves: list[tuple[Path, Path]] = []
    empty_after_move: list[Path] = []
    try:
        entry = _move_to_trash(folder, source, assets, now, moves, empty_after_move)
        _delete_rows(session, assets, subtree)
        session.commit()
    except BaseException as error:
        session.rollback()
        _undo_moves(moves)
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Folder delete failed; no rows were changed") from error

    # Only after the rows are gone: a thumbnail for a row that still exists is
    # merely stale, while a missing one is a broken UI. Best effort, like
    # delete_asset in main.py.
    thumb_root = thumbs_root()
    for asset_id in asset_ids:
        try:
            (thumb_root / f"{asset_id}.jpg").unlink(missing_ok=True)
        except OSError:
            pass
    for directory in empty_after_move:
        try:
            directory.rmdir()
        except OSError:
            # Still holds other files: not ours to remove.
            pass

    return {
        "trash_path": _relative_to_storage(entry),
        "folders": len(subtree),
        "assets": len(assets),
        "bytes": asset_bytes,
    }


# Trash listing and purge ----------------------------------------


def _entry_size(path: Path) -> int:
    """Best-effort recursive byte count that never follows a symlink."""
    total = 0
    for current, _dirnames, filenames in os.walk(path, followlinks=False):
        for filename in filenames:
            item = Path(current) / filename
            try:
                if item.is_symlink():
                    continue
                total += item.stat().st_size
            except OSError:
                continue
    return total


def list_entries() -> list[dict]:
    """List direct children of ``.trash`` with their size and UTC mtime."""
    root = trash_root()
    if not root.is_dir():
        return []
    entries: list[dict] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        try:
            if child.is_symlink():
                # Never follow: a link could point at live library content.
                continue
            stat_result = child.stat()
        except OSError:
            continue
        entries.append({
            "path": f"{TRASH_DIRNAME}/{child.name}",
            "name": child.name,
            "size": _entry_size(child),
            "mtime": datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat(),
        })
    return entries


def purge(older_than_days: Optional[int] = None) -> dict:
    """Irreversibly remove trash entries, all of them or only the old ones.

    Only direct children of ``.trash`` are considered, symlinks are skipped so a
    planted link can never make the purge reach into the live library, and the
    age test is strictly ``mtime < cutoff``: an entry touched at or after the
    cutoff survives. Size is summed before removal so the reported ``bytes`` is
    what was actually reclaimed.
    """
    root = trash_root()
    if not root.is_dir():
        return {"purged": 0, "bytes": 0, "failed": []}

    cutoff = None if older_than_days is None else time.time() - older_than_days * SECONDS_PER_DAY
    purged = 0
    reclaimed = 0
    failed: list[str] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        try:
            if child.is_symlink() or not child.is_dir():
                continue
            if cutoff is not None and child.stat().st_mtime >= cutoff:
                continue
        except OSError as exc:
            failed.append(f"{child.name}: {exc}")
            continue

        size = _entry_size(child)
        try:
            shutil.rmtree(child)
        except OSError as exc:
            failed.append(f"{child.name}: {exc}")
            continue
        purged += 1
        reclaimed += size

    return {"purged": purged, "bytes": reclaimed, "failed": failed}
