"""Discover files that were put into the managed storage root by other tools.

This is the first half of making folders filesystem-authoritative: the library
is scanned as it exists on disk, and matching assets are registered *where they
lie* instead of being re-templated into a new location. Folders are created from
the directory tree, so ``rsync``/``cp`` followed by "rescan" is a supported way
to add files.

Missing files are flagged, never purged:

* a scan sets ``missing_since`` when it first notices that an asset's file is
  gone and clears it when the file reappears. The timestamp is when the scan
  noticed the absence, not when the file disappeared;
* rows and files are never deleted, moved or renamed by a scan - losing a row
  because a network mount hiccuped would be worse than showing a stale entry;
* ``disk_mtime`` stays reserved and unwritten; ``is_reference`` is written by
  mount import (migration 004 / Mf-k0kf) and a scan leaves it untouched;
* ``thumbs/`` and ``bundles/`` are app-owned and skipped.

The flag scope is wider than the ``missing`` counter scope: reference rows
(``source_path`` set) are flagged when their source is gone, but only managed
rows (``source_path`` NULL, ``storage_path`` set) are counted in ``missing``.
The flag answers "are the bytes gone?" and deliberately does not apply
``main.is_mount_source_allowed``: a source that exists but is outside the
current mount allowlist is present on disk and stays unflagged, even though
``/file`` will still refuse to serve it. Degenerate rows with both
``storage_path`` and ``source_path`` NULL are skipped by the candidate query.
Scanning a non-standard root (as the tests do) flags every managed asset that
is absent from that root. Thumbnails are untouched: a cached sidecar keeps
rendering, and ``/thumb`` / ``/file`` return 404 (never 500) when the bytes are
gone.

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
  this run - never eagerly on directory entry. For the storage scan they stay
  metadata-only (``storage_path`` is ``None``; migration 004 gave folders a
  directory identity for runtime-created ones, scan-created rows are converged
  later), while a plan that materialises directories (mount copy mode) gives its
  folder rows their real relative path, because folder rename and delete have to
  move the real directory. A directory name that sanitises differently from its
  folder row can therefore still collide, which is surfaced as an error rather
  than a silent overwrite;
* prepared-print metadata is inspected inline on a best-effort basis; a file
  that cannot be read registers anyway and is not counted as a failure (the
  startup backfill retries it);
* a same-stem collision (``gear.stl`` + ``gear.3mf`` in one folder derive the
  same model name) fails exactly that one row with ``"<rel_path>: <error>"``
  while the rest of the batch still lands.

Two registration writers share this machinery: the storage scan
(``scan_storage_root``, which also owns the missing-flag pass) and mount import
(``mount_import`` via ``register_tree``). They are serialised by
``_write_lock``, because both create folder rows. Only the storage scan flags
files missing, so pointing a registration walk at a mount can never mark the
library missing.
"""
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

from sqlalchemy import or_, update
from sqlmodel import Session, select

from asset_service import ensure_model_thumbnail, save_thumb
from db import STORAGE, engine
from file_utils import guess_mime_from_path
from models import Asset, Folder
from prepared_print import inspect_prepared_print
from zip_service import sanitize_folder_name

# App-owned directories inside the storage root. Never library content.
RESERVED_DIRS = {"thumbs", "bundles", ".incoming"}
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
class PendingAsset:
    """A file found on disk that is not tracked yet.

    Compared by identity (``eq=False``) so a batch can drop the rows it rejected.
    """

    asset: Asset
    rel_path: str
    rel_dir: str


@dataclass
class TreePlan:
    """What one registration walk over ``root`` registers, and how.

    The walk and the batch machinery are shared; everything that differs between
    the storage scan and a mounted source lives here. Callables are supplied by
    the caller so this module keeps no policy of its own beyond the walk.
    """

    root: Path
    tracked: set  # dedupe keys already in the database
    keys_for: Callable[[str], Sequence[str]]  # relative path -> its dedupe keys
    accept: Callable[[str, int], bool]  # relative path + size -> register it?
    build: Callable[[str, int], Asset]  # relative path + size -> unsaved row
    dest_root: Optional[Path] = None  # copy target; None registers files in place
    prepare: Optional[Callable[[Session, List[PendingAsset], dict], None]] = None
    include_hidden: bool = False


_state = ScanState()
_state_lock = threading.Lock()

# Only one registration run writes at a time: folder rows are looked up and then
# created, and there is no unique index on (name, parent_id), so two writers can
# duplicate a whole branch. Lock order is always _write_lock -> _state_lock.
_write_lock = threading.Lock()
# Run-scoped counters and plan for the walk active in this thread. The batch
# helpers below are entered from several call sites with frozen signatures, so
# the active run is resolved here instead of being threaded through arguments.
_local = threading.local()


def _active_state() -> ScanState:
    """Counters of the registration run active in this thread, else the scan's."""
    return getattr(_local, "state", None) or _state


def _active_plan() -> Optional["TreePlan"]:
    """The plan of the registration run active in this thread, if any."""
    return getattr(_local, "plan", None)


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


def note_error(message: str) -> None:
    """Count one failed file against the active registration run."""
    state = _active_state()
    with _state_lock:
        state.failed += 1
        if len(state.errors) < 200:
            state.errors.append(message)


def _note_batch_failure(message: str, count: int) -> None:
    """One note for a whole rolled-back batch; every file in it is failed."""
    state = _active_state()
    with _state_lock:
        state.failed += count
        if len(state.errors) < 200:
            state.errors.append(message)


def _walk_storage(root: Path, *, include_hidden: bool = False) -> Iterator[Tuple[str, List[os.DirEntry], int]]:
    """Yield ``(rel_dir, file_entries, ignored_entries)`` per directory.

    Iterative on purpose: a deep tree must not hit the recursion limit. One
    directory is read at a time, so peak memory is that directory's entry list
    plus one pending pair per discovered directory.
    ``file_entries`` are the regular, non-symlink entries; the caller applies
    library policy (hidden names) and does the single ``stat`` per file.

    Directories that cannot be read are skipped, exactly like ``os.walk`` with
    the default ``onerror``. Symlinked directories and the root-level app-owned
    directories are always pruned silently and not counted; so are hidden
    directories, unless the caller passes ``include_hidden=True`` for a source
    whose dot-directories are real content.
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
                    if not include_hidden and entry.name.startswith("."):
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


def _asset_file_is_present(
    asset_id: str,
    filename: str,
    storage_path: Optional[str],
    source_path: Optional[str],
    root: Path,
    seen: set,
) -> bool:
    """Whether the bytes an asset row points at still exist on disk.

    The walk's ``seen`` set covers ordinary library files; the direct existence
    checks cover paths the walk prunes or filters (``thumbs/``, dotfiles, debris)
    and reference rows whose ``source_path`` lives outside the storage root.
    """
    managed_rel = storage_path or f"{asset_id}/{filename}"
    if managed_rel in seen:
        return True
    if (root / managed_rel).exists():
        return True
    if source_path and Path(source_path).exists():
        return True
    return False


def _apply_missing_flags(session: Session, flag_ids: List[str], clear_ids: List[str], now: str) -> None:
    """Write one batch of ``missing_since`` changes and commit it once.

    Bulk ``UPDATE`` statements are used so a concurrent ``DELETE`` between the
    candidate read and the write does not raise ``StaleDataError``. The caller
    owns rollback and retry.
    """
    if flag_ids:
        session.execute(update(Asset).where(Asset.id.in_(flag_ids)).values(missing_since=now))
    if clear_ids:
        session.execute(update(Asset).where(Asset.id.in_(clear_ids)).values(missing_since=None))
    session.commit()


def _flag_missing_assets(session: Session, root: Path, seen: set, now: str) -> None:
    """Set or clear ``missing_since`` for every candidate row, in bounded batches.

    Candidates are keyset-paginated by id and written with at most one commit per
    ``BATCH_SIZE`` changes, so neither the candidate set nor the dirty ids are
    held in memory for a whole tree.
    """
    flag_ids: List[str] = []
    clear_ids: List[str] = []
    consecutive_failures = 0
    last_id = ""

    def flush() -> None:
        """Commit the accumulated ids, retrying once after a transaction failure."""
        nonlocal consecutive_failures
        if not flag_ids and not clear_ids:
            return
        try:
            _apply_missing_flags(session, flag_ids, clear_ids, now)
        except Exception:
            session.rollback()
            try:
                _apply_missing_flags(session, flag_ids, clear_ids, now)
            except Exception as exc:
                session.rollback()
                # not a registration failure: these rows simply stay un-flagged
                # (or flagged) and the next scan converges.
                with _state_lock:
                    if len(_state.errors) < 200:
                        _state.errors.append(
                            f"missing-flag batch of {len(flag_ids) + len(clear_ids)} rolled back: {exc}"
                        )
                flag_ids.clear()
                clear_ids.clear()
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_BATCH_FAILURES:
                    raise RuntimeError(
                        f"{consecutive_failures} consecutive flag batches failed to commit"
                    ) from exc
                return
        flag_ids.clear()
        clear_ids.clear()
        consecutive_failures = 0

    while True:
        rows = session.exec(
            select(Asset.id, Asset.filename, Asset.storage_path, Asset.source_path, Asset.missing_since)
            .where(
                or_(Asset.storage_path.is_not(None), Asset.source_path.is_not(None)),
                Asset.id > last_id,
            )
            .order_by(Asset.id)
            .limit(BATCH_SIZE)
        ).all()
        if not rows:
            break

        page_missing = 0
        for asset_id, filename, storage_path, source_path, missing_since in rows:
            last_id = asset_id
            present = _asset_file_is_present(asset_id, filename, storage_path, source_path, root, seen)
            if present:
                if missing_since is not None:
                    clear_ids.append(asset_id)
                continue
            if source_path is None and storage_path is not None:
                page_missing += 1
            # never re-stamp an already-flagged row: its timestamp must stay stable
            if missing_since is None:
                flag_ids.append(asset_id)
        if page_missing:
            with _state_lock:
                _state.missing += page_missing
        if len(flag_ids) + len(clear_ids) >= BATCH_SIZE:
            flush()

    flush()


def resolve_dir_folder(
    session: Session,
    rel_dir: str,
    cache: dict,
    *,
    with_storage_path: bool = False,
) -> Optional[str]:
    """Return the folder id for a scanned directory, creating missing rows.

    Mirrors ``zip_service.resolve_zip_folder_id`` for the scan's case (no base
    folder), except that folder rows belong to the caller's batch transaction
    rather than being committed one folder at a time. The flush is not optional:
    it keeps the folder INSERTs out of the per-row savepoints, so a rejected
    asset row can never roll back a folder that its siblings still reference.
    There is also no unique index on ``folder(name, parent_id)``, so an unflushed
    duplicate would silently duplicate a whole branch.

    ``with_storage_path=True`` is for a caller that materialises directories
    (mount copy mode): its folder rows carry the real, unsanitised relative path
    so that renaming or deleting such a folder can move the actual directory.
    The storage scan leaves it False, keeping its rows metadata-only. Rows reused
    by ``(parent_id, name)`` keep whatever ``storage_path`` they already have.
    """
    parent_id: Optional[str] = None
    parent_key = "root"
    consumed: List[str] = []
    for segment in rel_dir.split("/"):
        if not segment:
            continue
        consumed.append(segment)
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
                storage_path = "/".join(consumed) if with_storage_path else None
                folder = Folder(name=name, tags_json="[]", parent_id=parent_id, storage_path=storage_path)
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


def build_asset(root: Path, rel_path: str, size: int) -> Asset:
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


def _assign_folders(session: Session, pending: List[PendingAsset], cache: dict) -> None:
    """Resolve every folder id before any of these assets enters the session."""
    folder_ids = [resolve_dir_folder(session, item.rel_dir, cache) for item in pending]
    for item, folder_id in zip(pending, folder_ids, strict=True):
        item.asset.folder_id = folder_id


def _commit_batch(
    session: Session,
    pending: List[PendingAsset],
    cache: dict,
) -> List[Tuple[str, str, str]]:
    """Insert one batch in a single transaction and return its thumbnail work.

    Each row gets its own savepoint so a row that cannot be inserted (a name
    collision, a bad value) is dropped without poisoning the batch. Raises when
    the batch transaction itself fails; ``pending`` then only holds the rows
    that were not individually rejected.
    """
    plan = _active_plan()
    if plan is not None and plan.prepare is not None:
        # mount-only side effects (materialise folders, copy bytes) have to run on
        # every attempt: _flush_batch retries _commit_batch after a failed commit,
        # and a retry with a cleared folder cache must not fall back to
        # metadata-only folders.
        plan.prepare(session, pending, cache)
    _assign_folders(session, pending, cache)
    rejected: List[PendingAsset] = []
    for item in pending:
        asset = item.asset
        try:
            with session.begin_nested():
                session.add(asset)
                session.flush()
        except Exception as exc:
            if asset in session:
                session.expunge(asset)
            note_error(f"{item.rel_path}: {exc}")
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
    pending: List[PendingAsset],
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


def _register_tree(session: Session, plan: TreePlan, state: ScanState, seen: set) -> None:
    """Walk ``plan.root`` and register what the plan accepts, in batches.

    Registers only: it never stamps or clears ``missing_since``, so a caller can
    point it at a root that is not the library (a mounted source) without
    flagging the whole library. Counters and error notes go to ``state`` via the
    thread-local active run.
    """
    previous_state = getattr(_local, "state", None)
    previous_plan = getattr(_local, "plan", None)
    _local.state = state
    _local.plan = plan

    folder_cache: dict = {}
    pending: List[PendingAsset] = []
    consecutive_failures = 0

    def flush() -> None:
        """Commit what is pending and account for it."""
        nonlocal consecutive_failures
        if not pending:
            return
        committed = _flush_batch(session, pending, folder_cache, plan.root)
        pending.clear()
        if committed is None:
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_BATCH_FAILURES:
                raise RuntimeError(f"{consecutive_failures} consecutive batches failed to commit")
            return
        consecutive_failures = 0
        for rel_path in committed:
            plan.tracked.update(plan.keys_for(rel_path))
        with _state_lock:
            state.registered += len(committed)

    try:
        walk = _walk_storage(plan.root, include_hidden=True) if plan.include_hidden else _walk_storage(plan.root)
        for rel_dir, file_entries, ignored in walk:
            if ignored:
                with _state_lock:
                    state.ignored += ignored
            for entry in file_entries:
                if entry.name in IGNORED_FILENAMES or (not plan.include_hidden and entry.name.startswith(".")):
                    with _state_lock:
                        state.ignored += 1
                    continue
                rel_path = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                # everything this run actually saw, so the missing pass never
                # has to look at a present file twice
                seen.add(rel_path)
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError as exc:
                    note_error(f"{rel_path}: {exc}")
                    continue
                if not plan.accept(rel_path, size):
                    with _state_lock:
                        state.ignored += 1
                    continue
                if any(key in plan.tracked for key in plan.keys_for(rel_path)):
                    with _state_lock:
                        state.known += 1
                    continue
                pending.append(PendingAsset(asset=plan.build(rel_path, size), rel_path=rel_path, rel_dir=rel_dir))
                if len(pending) >= BATCH_SIZE:
                    flush()

        flush()
    finally:
        _local.state = previous_state
        _local.plan = previous_plan


def _self_key(rel_path: str) -> Tuple[str, ...]:
    """A storage file is tracked by the relative path it lies at."""
    return (rel_path,)


def _accept_every_file(_rel_path: str, _size: int) -> bool:
    """The storage scan takes every file the walk offers."""
    return True


def _storage_plan(root: Path, tracked: set) -> TreePlan:
    """The plan for the library itself: register every file where it lies."""
    return TreePlan(root=root, tracked=tracked, keys_for=_self_key, accept=_accept_every_file, build=partial(build_asset, root))


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
        note_error(f"storage root not found: {root}")
        return _state

    # one timestamp per run: every asset the scan first notices as missing this
    # pass shares it, so the value is stable and order-independent.
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with _write_lock, Session(engine) as session:
        tracked = set(
            session.exec(
                select(Asset.storage_path).where(Asset.storage_path.is_not(None))
            ).all()
        )

        seen: set = set()
        _register_tree(session, _storage_plan(root, tracked), _state, seen)

        # registers nothing and deletes nothing: it only stamps or clears
        # ``missing_since``. The ``missing`` counter covers managed rows only,
        # while reference rows may be flagged too.
        _flag_missing_assets(session, root, seen, now)

    return _state


def register_tree(plan: TreePlan) -> ScanState:
    """Register what ``plan`` accepts under its root, in batches.

    Every counter belongs to the returned state, so a mounted import never
    clobbers the library-scan status and never stamps ``missing_since``. Runs are
    serialised with the storage scan, because both create folder rows.
    """
    state = ScanState(started_at=time.time())
    if not plan.root.exists() or not plan.root.is_dir():
        with _state_lock:
            state.failed += 1
            state.errors.append(f"root not found: {plan.root}")
        return state
    try:
        with _write_lock, Session(engine) as session:
            _register_tree(session, plan, state, set())
    finally:
        state.finished_at = time.time()
    return state
