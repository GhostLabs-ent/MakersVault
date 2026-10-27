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
* folders are still metadata rows until migration 004 gives them a directory
  identity, so a directory name that sanitises differently from its folder row
  can produce a collision (surfaced as an error, not a silent overwrite).
"""
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from sqlmodel import Session, select

from asset_service import (
    ensure_model_thumbnail,
    finalize_asset_record,
    managed_asset_path,
    save_thumb,
)
from db import STORAGE, engine
from file_utils import guess_mime_from_path
from models import Asset
from zip_service import resolve_zip_folder_id

# App-owned directories inside the storage root. Never library content.
RESERVED_DIRS = {"thumbs", "bundles"}
# OS/tool debris that is never a library item.
IGNORED_FILENAMES = {"Thumbs.db", "desktop.ini", ".DS_Store"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


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


def _register_file(session: Session, rel_path: str, size: int, folder_id: Optional[str]) -> None:
    """Create an asset row for a file that is already at ``rel_path``."""
    filename = Path(rel_path).name
    name = Path(rel_path).stem or filename
    mime = guess_mime_from_path(rel_path)
    asset = Asset(
        name=name,
        filename=filename,
        mime=mime,
        size=size,
        title=name,
        folder_id=folder_id,
        # the whole point of the scan: this row points at the real file
        storage_path=rel_path,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    try:
        path = managed_asset_path(asset)
        if (mime or "").lower().startswith("image/") and path.suffix.lower() in IMAGE_SUFFIXES:
            save_thumb(asset.id, path)
        elif path.suffix.lower() == ".3mf":
            ensure_model_thumbnail(asset.id, path)
    except Exception:
        # a thumbnail is nice to have; it must not cost us the registration
        pass

    finalize_asset_record(asset.id, size, mime)


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
        managed = session.exec(
            select(Asset.id, Asset.storage_path).where(
                Asset.source_path.is_(None), Asset.storage_path.is_not(None)
            )
        ).all()

        folder_cache: dict = {}
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current = Path(dirpath)
            at_root = current == root
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".")
                and not (at_root and d in RESERVED_DIRS)
                and not (current / d).is_symlink()
            ]

            for filename in filenames:
                if filename.startswith(".") or filename in IGNORED_FILENAMES:
                    with _state_lock:
                        _state.ignored += 1
                    continue
                path = current / filename
                if path.is_symlink() or not path.is_file():
                    with _state_lock:
                        _state.ignored += 1
                    continue

                rel_path = path.relative_to(root).as_posix()
                if rel_path in tracked:
                    with _state_lock:
                        _state.known += 1
                    continue
                try:
                    size = path.stat().st_size
                    folder_id = resolve_zip_folder_id(session, None, rel_path, folder_cache)
                    _register_file(session, rel_path, size, folder_id)
                    tracked.add(rel_path)
                    with _state_lock:
                        _state.registered += 1
                except Exception as exc:
                    _note_error(f"{rel_path}: {exc}")

        with _state_lock:
            _state.missing = sum(
                1 for _asset_id, storage_path in managed if not (root / storage_path).exists()
            )

    return _state
