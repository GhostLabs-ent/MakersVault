"""Discover files that were put into the managed storage root by other tools.

This is the first half of making folders filesystem-authoritative: the library
is scanned as it exists on disk, and matching assets are registered *where they
lie* instead of being re-templated into a new location. Folders are created from
the directory tree, so ``rsync``/``cp`` followed by "rescan" is a supported way
to add files.

Deliberately not done here (later phases):

* no file is moved, renamed or deleted;
* missing files are counted, never purged or mutated - losing a row because a
  network mount hiccuped would be worse than showing a stale entry;
* ``thumbs/`` and ``bundles/`` are app-owned and skipped;
* ``missing_since``, ``disk_mtime`` and ``is_reference`` are owned by later
  work (Mf-itr4); a scan leaves them at their defaults.

How a scan behaves:

* the tree is walked iteratively, one directory at a time, so peak memory is a
  single directory's entry list, the batch being registered and the set of
  relative paths already known - not the whole tree of rows;
* rows are committed in batches of ``BATCH_SIZE``. An interruption (a crash, a
  killed process, a raised error) leaves whole committed batches behind and the
  in-flight batch rolled back, so a rescan picks up exactly where the last one
  stopped;
* counters are per run and describe this scan only. ``registered`` counts rows
  that were actually committed; a row that failed and was rolled back is
  ``failed``, never ``registered``;
* folder rows are created only for a directory that had a file to register in
  this run - never eagerly on directory entry - and they stay metadata-only
  (``storage_path`` is ``None``; migration 004 gave folders a directory
  identity for runtime-created ones, scan-created rows are converged later).
  A directory name that sanitises differently from its folder row can therefore
  still collide, which is surfaced as an error rather than a silent overwrite;
* prepared-print metadata is inspected inline on a best-effort basis; a file
  that cannot be read registers anyway and is not counted as a failure (the
  startup backfill retries it);
* a same-stem collision (``gear.stl`` + ``gear.3mf`` in one folder derive the
  same model name) fails exactly that one row with ``"<rel_path>: <error>"``
  while the rest of the batch still lands.
"""
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from sqlmodel import Session, select

from asset_service import ensure_model_thumbnail, save_thumb
from db import STORAGE, engine
from file_utils import guess_mime_from_path
from models import Asset, Folder
from prepared_print import inspect_prepared_print
from zip_service import sanitize_folder_name

# App-owned directories inside the storage root. Never library content.
RESERVED_DIRS = {"thumbs", "bundles"}
# OS/tool debris that is never a library item.
IGNORED_FILENAMES = {"Thumbs.db", "desktop.ini", ".DS_Store"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# Rows are committed in batches so one run does not hold a write transaction for
# the whole tree, and so a long scan leaves a usable partial state.
BATCH_SIZE = 200
# Three batches in a row that cannot commit means the database is not coming
# back on its own; stop instead of hammering it.
MAX_CONSECUTIVE_BATCH_FAILURES = 3


@dataclass
class ScanState:
    running: bool = False
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    registered: int = 0      # files newly added to the library
    known: int = 0           # files already tracked (nothing to do)
    ignored: int = 0         # hidden files, app-owned dirs, debris
    missing: int = 0         # tracked files that are no longer on disk
    failed: int = 0          # files that could not be registered
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["errors"] = self.errors[-20:]
        return data


@dataclass(eq=False)
class _PendingAsset:
    """A file found on disk that is not tracked yet.

    Compared by identity (``eq=False``) so a batch can drop the rows it rejected.
    """

    asset: Asset
    rel_path: str
    rel_dir: str


_state = ScanState()
_state_lock = threading.Lock()


def scan_status() -> dict:
    with _state_lock:
        return _state.as_dict()


def start_scan() -> bool:
    """Start a background scan. Returns False when one is already running."""
    with _state_lock:
        if _state.running:
            return False
        _state.running = True
        _state.started_at = time.time()
        _state.finished_at = None
    threading.Thread(target=_run_scan, name="library-scan", daemon=True).start()
    return True


def _run_scan() -> None:
    try:
        scan_storage_root()
    except Exception as exc:  # keep the status endpoint honest on unexpected failure
        with _state_lock:
            _state.failed += 1
            _state.errors.append(f"scan aborted: {exc}")
    finally:
        with _state_lock:
            _state.running = False
            _state.finished_at = time.time()


def _note_error(message: str) -> None:
    with _state_lock:
        _state.failed += 1
        if len(_state.errors) < 200:
            _state.errors.append(message)


def _note_batch_failure(message: str, count: int) -> None:
    """One note for a whole rolled-back batch; every file in it is failed."""
    with _state_lock:
        _state.failed += count
        if len(_state.errors) < 200:
            _state.errors.append(message)


def _walk_storage(root: Path) -> Iterator[Tuple[str, List[os.DirEntry], int]]:
    """Yield ``(rel_dir, file_entries, ignored_entries)`` per directory.

    Iterative on purpose: a deep tree must not hit the recursion limit. One
    directory is read at a time, so peak memory is that directory's entry list
    plus one pending pair per discovered directory.
    ``file_entries`` are the regular, non-symlink entries; the caller applies
    library policy (hidden names) and does the single ``stat`` per file.

    Directories that cannot be read are skipped, exactly like ``os.walk`` with
    the default ``onerror``. Symlinked directories, hidden directories and the
    root-level app-owned directories are pruned silently and not counted.
    """
    stack: List[Tuple[str, Path]] = [("", root)]
    while stack:
        rel_dir, directory = stack.pop()
        try:
            with os.scandir(directory) as scan:
                entries = list(scan)
        except OSError:
            continue

        file_entries: List[os.DirEntry] = []
        ignored = 0
        for entry in entries:
            try:
                if entry.is_symlink():
                    if entry.is_dir():
                        # a symlinked directory leads outside the root
                        continue
                    ignored += 1
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.startswith("."):
                        continue
                    if rel_dir == "" and entry.name in RESERVED_DIRS:
                        continue
                    child_rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                    stack.append((child_rel, Path(entry.path)))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    ignored += 1
                    continue
            except OSError:
                continue
            file_entries.append(entry)
        yield rel_dir, file_entries, ignored


def _resolve_dir_folder(session: Session, rel_dir: str, cache: dict) -> Optional[str]:
    """Return the folder id for a scanned directory, creating missing rows.

    Mirrors ``zip_service.resolve_zip_folder_id`` for the scan's case (no base
    folder), except that folder rows belong to the caller's batch transaction
    rather than being committed one folder at a time. The flush is not optional:
    it keeps the folder INSERTs out of the per-row savepoints, so a rejected
    asset row can never roll back a folder that its siblings still reference.
    There is also no unique index on ``folder(name, parent_id)``, so an unflushed
    duplicate would silently duplicate a whole branch.
    """
    parent_id: Optional[str] = None
    parent_key = "root"
    for segment in rel_dir.split("/"):
        if not segment:
            continue
        name = sanitize_folder_name(segment)
        key = f"{parent_key}/{name}"
        folder_id = cache.get(key)
        if not folder_id:
            existing = session.exec(
                select(Folder).where(Folder.parent_id == parent_id, Folder.name == name)
            ).first()
            if existing:
                folder_id = existing.id
            else:
                folder = Folder(name=name, tags_json="[]", parent_id=parent_id, storage_path=None)
                session.add(folder)
                session.flush()
                folder_id = folder.id
            cache[key] = folder_id
        parent_id = folder_id
        parent_key = key
    return parent_id


def _prepared_metadata(path: Path, filename: str) -> Optional[str]:
    """Best-effort prepared-print metadata; never a reason to fail a row."""
    if not filename.lower().endswith(".3mf"):
        return None
    try:
        metadata = inspect_prepared_print(path, filename)
    except Exception:
        return None
    return json.dumps(metadata) if metadata else None


def _build_asset(root: Path, rel_path: str, size: int) -> Asset:
    """Build the whole row up front, so the write phase needs no extra reads."""
    file_path = Path(rel_path)
    filename = file_path.name
    name = file_path.stem or filename
    return Asset(
        name=name,
        filename=filename,
        mime=guess_mime_from_path(rel_path),
        size=size,
        title=name,
        # the whole point of the scan: this row points at the real file
        storage_path=rel_path,
        prepared_metadata_json=_prepared_metadata(root / rel_path, filename),
    )


def _assign_folders(session: Session, pending: List[_PendingAsset], cache: dict) -> None:
    """Resolve every folder id before any of these assets enters the session."""
    folder_ids = [_resolve_dir_folder(session, item.rel_dir, cache) for item in pending]
    for item, folder_id in zip(pending, folder_ids, strict=True):
        item.asset.folder_id = folder_id


def _commit_batch(
    session: Session,
    pending: List[_PendingAsset],
    cache: dict,
) -> List[Tuple[str, str, str]]:
    """Insert one batch in a single transaction and return its thumbnail work.

    Each row gets its own savepoint so a row that cannot be inserted (a name
    collision, a bad value) is dropped without poisoning the batch. Raises when
    the batch transaction itself fails; ``pending`` then only holds the rows
    that were not individually rejected.
    """
    _assign_folders(session, pending, cache)
    rejected: List[_PendingAsset] = []
    for item in pending:
        asset = item.asset
        try:
            with session.begin_nested():
                session.add(asset)
                session.flush()
        except Exception as exc:
            if asset in session:
                session.expunge(asset)
            _note_error(f"{item.rel_path}: {exc}")
            rejected.append(item)
    for item in rejected:
        pending.remove(item)

    thumbnails = [(item.asset.id, item.rel_path, item.asset.mime) for item in pending]
    session.commit()
    # the identity map would otherwise grow to the size of the whole tree
    session.expunge_all()
    return thumbnails


def _save_thumbnails(root: Path, thumbnails: List[Tuple[str, str, str]]) -> None:
    """Best-effort thumbnails, outside any write transaction."""
    for asset_id, rel_path, mime in thumbnails:
        path = root / rel_path
        try:
            suffix = path.suffix.lower()
            if (mime or "").lower().startswith("image/") and suffix in IMAGE_SUFFIXES:
                save_thumb(asset_id, path)
            elif suffix == ".3mf":
                ensure_model_thumbnail(asset_id, path)
        except Exception:
            # a thumbnail is nice to have; it must not cost us the registration
            pass


def _flush_batch(
    session: Session,
    pending: List[_PendingAsset],
    cache: dict,
    root: Path,
) -> Optional[List[str]]:
    """Commit a batch, retrying once after a transaction-level failure.

    Returns the rel paths that were committed, or ``None`` when the batch could
    not be committed at all; those files are counted as failed and left for the
    next scan.
    """
    try:
        thumbnails = _commit_batch(session, pending, cache)
    except Exception:
        # a lock timeout or an IO error: a half-applied transaction must not be
        # trusted, and cached folder ids may now point at rolled-back rows
        session.rollback()
        cache.clear()
        try:
            thumbnails = _commit_batch(session, pending, cache)
        except Exception as exc:
            session.rollback()
            cache.clear()
            _note_batch_failure(f"batch of {len(pending)} rolled back: {exc}", len(pending))
            return None
    _save_thumbnails(root, thumbnails)
    return [rel_path for _asset_id, rel_path, _mime in thumbnails]


def scan_storage_root() -> ScanState:
    """Walk the storage root and register unknown files. Safe to call directly.

    Counters describe this scan only; callers that need history should read the
    status endpoint before starting another run.
    """
    with _state_lock:
        _state.registered = 0
        _state.known = 0
        _state.ignored = 0
        _state.missing = 0
        _state.failed = 0
        _state.errors = []

    root = STORAGE.resolve()
    if not root.exists() or not root.is_dir():
        _note_error(f"storage root not found: {root}")
        return _state

    with Session(engine) as session:
        tracked = set(
            session.exec(
                select(Asset.storage_path).where(Asset.storage_path.is_not(None))
            ).all()
        )
        # only managed assets own a file in the storage root; mount references
        # point at paths outside it and must not be reported as missing
        managed_paths = session.exec(
            select(Asset.storage_path).where(
                Asset.source_path.is_(None), Asset.storage_path.is_not(None)
            )
        ).all()

        seen: set = set()
        folder_cache: dict = {}
        pending: List[_PendingAsset] = []
        consecutive_failures = 0

        def flush() -> None:
            """Commit what is pending and account for it."""
            nonlocal consecutive_failures
            if not pending:
                return
            committed = _flush_batch(session, pending, folder_cache, root)
            pending.clear()
            if committed is None:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_BATCH_FAILURES:
                    raise RuntimeError(f"{consecutive_failures} consecutive batches failed to commit")
                return
            consecutive_failures = 0
            tracked.update(committed)
            with _state_lock:
                _state.registered += len(committed)

        for rel_dir, file_entries, ignored in _walk_storage(root):
            if ignored:
                with _state_lock:
                    _state.ignored += ignored
            for entry in file_entries:
                if entry.name.startswith(".") or entry.name in IGNORED_FILENAMES:
                    with _state_lock:
                        _state.ignored += 1
                    continue
                rel_path = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                # everything this scan actually saw, so the missing pass never
                # has to look at a present file twice
                seen.add(rel_path)
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError as exc:
                    _note_error(f"{rel_path}: {exc}")
                    continue
                if rel_path in tracked:
                    with _state_lock:
                        _state.known += 1
                    continue
                pending.append(_PendingAsset(asset=_build_asset(root, rel_path, size), rel_path=rel_path, rel_dir=rel_dir))
                if len(pending) >= BATCH_SIZE:
                    flush()

        flush()

        with _state_lock:
            _state.missing = sum(
                1
                for storage_path in managed_paths
                if storage_path not in seen and not (root / storage_path).exists()
            )

    return _state
