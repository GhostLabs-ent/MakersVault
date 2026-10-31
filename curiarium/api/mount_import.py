"""Import an external folder tree (a mount) into the library.

Two modes, chosen by the ``mount_import_copy`` setting:

* **copy mode** mirrors the mount's relative directory structure into the
  storage root. A mount containing ``a/b/c.stl`` registers ``STORAGE/a/b/c.stl``
  and a folder chain ``a`` -> ``a/b`` whose folder rows carry those real relative
  paths, so renaming or deleting such a folder moves the real directory.
* **reference mode** registers ``is_reference=1`` rows that point at
  ``source_path`` and copies nothing, which survives its source disappearing
  (the storage scan flags it ``missing_since`` but never deletes it).

The registration path is the library scanner's (``register_tree``): the same
walk, the same 200-row batching, and no per-file ``finalize_asset_record``. A
mount import run never flags files missing - only the storage scan does.

Idempotency is by destination storage path and by the absolute ``source_path``
of files under this mount, so re-running registers nothing. Switching modes does
not convert existing rows: the first mode wins. The extension allowlist, the
hidden-files policy and ``IMPORT_MAX_BYTES`` still apply. A mount may not contain
or sit inside the storage root (copy mode tolerates an identical root by
registering it in place), because importing the library into itself would
re-mirror it on every run.

Ruling (Mf-k0kf): the startup mount scan is opt-in by configuration. It runs at
startup if and only if (a) `IMPORT_MOUNT_PATH`/`MOUNT_IMPORT_PATH` is configured
and (b) the `mount_import_enabled` setting (env `IMPORT_MOUNT_ON_STARTUP`,
default `true`, overridable in the database) is not false. Out of the box no
mount path is configured, so nothing ever runs; configuring a mount path is the
opt-in, and `IMPORT_MOUNT_ON_STARTUP` is the opt-out for deployments that
configure a mount but do not want a startup scan. The env default stays `true`:
flipping it would silently disable startup imports for existing deployments that
already configured a mount.
"""
import os
import re
import shutil
import time
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

import import_runs
import library_scan
from config import (
    DEFAULT_MOUNT_IMPORT_EXTS,
    IMPORT_MAX_BYTES,
    MOUNT_IMPORT_COPY,
    MOUNT_IMPORT_ENABLED,
    MOUNT_IMPORT_EXTS_RAW,
    MOUNT_IMPORT_INCLUDE_HIDDEN,
    MOUNT_IMPORT_PATH,
)
from db import engine
from library_scan import ScanState, TreePlan, build_asset, note_error, register_tree, resolve_dir_folder
from models import Asset
from settings_service import get_mount_import_copy, get_mount_import_enabled


def parse_mount_import_exts(raw: str) -> Optional[set]:
    if not raw:
        return set(DEFAULT_MOUNT_IMPORT_EXTS)
    lowered = raw.strip().lower()
    if lowered == "*":
        return None
    parts = re.split(r"[,\s]+", lowered)
    exts = set()
    for part in parts:
        if not part:
            continue
        ext = part if part.startswith(".") else f".{part}"
        exts.add(ext)
    return exts or set(DEFAULT_MOUNT_IMPORT_EXTS)


def mount_import_should_run() -> bool:
    """Whether the startup mount import may start (reads config at call time)."""
    return bool(MOUNT_IMPORT_PATH) and get_mount_import_enabled(MOUNT_IMPORT_ENABLED)


def _overlap_kind(root: Path, storage_root: Path) -> Optional[str]:
    """How a mount root and the storage root overlap, or None when they do not.

    ``same`` is only workable for copy mode: the files already lie where they
    belong, so nothing is copied and the tree is registered in place.
    """
    if root == storage_root:
        return "same"
    if storage_root in root.parents:
        return "contains"
    if root in storage_root.parents:
        return "inside"
    return None


def _source_key(root: Path, rel_path: str) -> str:
    """The absolute path a file under ``root`` came from."""
    return (root / rel_path).as_posix()


def _tracked_keys(root: Path) -> set:
    """Everything a run under ``root`` must not register again.

    Managed rows are deduplicated by the relative path they lie at; rows that
    came from this mount are deduplicated by their absolute source path.
    """
    prefix = root.as_posix().rstrip("/")
    keys: set = set()
    with Session(engine) as session:
        keys.update(
            session.exec(
                select(Asset.storage_path).where(Asset.storage_path.is_not(None))
            ).all()
        )
        source_query = select(Asset.source_path)
        if prefix:
            # escape the LIKE wildcards so a mount path containing % or _ is literal
            escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            source_query = source_query.where(Asset.source_path.like(f"{escaped}/%", escape="\\"))
        else:
            source_query = source_query.where(Asset.source_path.is_not(None))
        keys.update(session.exec(source_query).all())
    keys.discard(None)
    return keys


def scan_mount_imports() -> Optional[ScanState]:
    """Register the files of the configured mount. Returns its counters.

    ``None`` means the run did not start (no mount configured, mount missing, a
    mount that contains or sits inside the storage root, a reference-mode mount
    that is the storage root, or an aborted run). Every started or skipped
    attempt after the no-path early return is recorded in ``import_run``.
    """
    root_raw = MOUNT_IMPORT_PATH
    if not root_raw:
        return None
    root = Path(root_raw)
    if not root.exists() or not root.is_dir():
        reason = f"mount path not found: {root_raw}"
        import_runs.skip_run(root_raw, None, reason)
        print(f"[mount-import] Skipping: {reason}")
        return None

    root = root.resolve()
    allowed_exts = parse_mount_import_exts(MOUNT_IMPORT_EXTS_RAW)
    copy_files = get_mount_import_copy(MOUNT_IMPORT_COPY)
    mode = "copy" if copy_files else "reference"
    storage_root = Path(library_scan.STORAGE).resolve()
    overlap = _overlap_kind(root, storage_root)
    if overlap == "same" and not copy_files:
        reason = "reference mode needs a source outside the storage root"
        import_runs.skip_run(str(root), mode, reason)
        print(f"[mount-import] Skipping: {reason}")
        return None
    if overlap in {"contains", "inside"}:
        relation = "contains" if overlap == "contains" else "is inside"
        reason = f"the mount {root} {relation} the storage root {storage_root}"
        import_runs.skip_run(str(root), mode, reason)
        print(f"[mount-import] Skipping: {reason}")
        return None

    rejected: list[str] = []

    def keys_for(rel_path: str) -> tuple:
        """Symmetric dedupe: copy and reference imports never re-import each other."""
        return (rel_path, _source_key(root, rel_path))

    def accept(rel_path: str, size: int) -> bool:
        suffix = Path(rel_path).suffix.lower()
        if allowed_exts is not None and suffix not in allowed_exts:
            return False
        if size > IMPORT_MAX_BYTES:
            rejected.append(rel_path)
            return False
        return True

    def build(rel_path: str, size: int) -> Asset:
        row = build_asset(root, rel_path, size, created_via="mount-import")
        if not copy_files:
            row.storage_path = None
            row.source_path = _source_key(root, rel_path)
            row.is_reference = 1
        return row

    def prepare(session: Session, pending: list, cache: dict) -> None:
        """Materialise folders and copy bytes, dropping the files that fail."""
        for item in list(pending):
            resolve_dir_folder(session, item.rel_dir, cache, with_storage_path=True)
            src = root / item.rel_path
            dst = storage_root / item.rel_path
            if src == dst:
                # the mount is the storage root: the file already lies there
                continue
            tmp = dst.with_name(f".{dst.name}.mvimport")
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, tmp)
                os.replace(tmp, dst)
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                note_error(f"{item.rel_path}: {exc}")
                pending.remove(item)

    state = ScanState(started_at=time.time())
    run_id = import_runs.begin_run(str(root), mode, state.started_at)
    import_runs.set_active(run_id, state)
    try:
        plan = TreePlan(
            root=root,
            tracked=_tracked_keys(root),
            keys_for=keys_for,
            accept=accept,
            build=build,
            dest_root=storage_root if copy_files else None,
            prepare=prepare if copy_files else None,
            include_hidden=MOUNT_IMPORT_INCLUDE_HIDDEN,
            # copy mode mirrors the mount into storage, so its folder rows stand
            # for real directories; reference mode only groups what lives outside
            folders_are_directories=bool(copy_files),
        )
        register_tree(plan, state)
        import_runs.finish_run(run_id, state, len(rejected))
    except Exception as exc:  # the startup thread is a daemon: a raise would be invisible
        import_runs.fail_run(run_id, state, len(rejected), str(exc))
        print(f"[mount-import] aborted: {exc}")
        return None
    finally:
        import_runs.clear_active(run_id)

    print(
        f"[mount-import] Done ({mode}) {root}: registered {state.registered}, "
        f"known {state.known}, ignored {state.ignored}, failed {state.failed}"
    )
    if rejected:
        print(f"[mount-import] Skipped {len(rejected)} oversize file(s): {', '.join(rejected[:5])}")
    if state.errors:
        print(f"[mount-import] {len(state.errors)} error(s):")
        for error in state.errors[:5]:
            print(f"[mount-import]   {error}")
    return state
