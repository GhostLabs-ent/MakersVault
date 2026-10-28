import atexit
import os
import re
import shutil
import tempfile
from pathlib import Path

_SQLITE_PREFIX = "sqlite:///"


def _worktree_name() -> str:
    """Name of the worktree this checkout lives in.

    The API image flattens the layout (/app/tests), so there is no worktree to
    find there and the pid alone has to be enough - which it is, because each
    container has its own /tmp.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent.name
    return ""


def _run_id() -> str:
    """One id per verification run.

    MV_RUN_ID is exported by the Makefile for a whole run, so a lane's DB,
    storage, image tags and ports all share it. Without it the pid keeps
    concurrent runs apart, including two runs in the same worktree.
    """
    raw = os.environ.get("MV_RUN_ID") or f"{os.getpid()}-{_worktree_name()}"
    # One path component and nothing else: no separators, and no dot, so a
    # caller-supplied "." or ".." cannot climb out of the run root and reach
    # another run's tree.
    return re.sub(r"[^a-z0-9_-]", "-", raw.lower()) or str(os.getpid())


def _sqlite_file(db_url: str) -> Path | None:
    """The database file behind a sqlite URL, or None for anything else."""
    if not db_url.startswith(_SQLITE_PREFIX):
        return None
    path = Path(db_url[len(_SQLITE_PREFIX):])
    return path if path.is_absolute() else None


# Tests must not depend on the developer's environment, and they must run
# without a reverse proxy in front of them. Everything here is set before any
# test module imports the application.
#
# Paths are per run: the run root carries the run id, so a second pytest run
# can never delete the first one's database mid-flight (Mf-ly4o).
owns_database = "DB_URL" not in os.environ
run_root = Path(tempfile.gettempdir()) / "makersvault-tests" / _run_id()
run_root.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DB_URL", f"{_SQLITE_PREFIX}{run_root / 'test.db'}")
os.environ.setdefault("FILE_STORAGE", str(run_root / "storage"))
os.environ.setdefault("IMPORT_MOUNT_ON_STARTUP", "false")

# The published sample credentials (admin / super-secret) are what the smoke
# test logs in with; opt out of the insecure-defaults startup guard for tests
# only. The guard itself is covered explicitly in test_hardening.py.
os.environ.setdefault("AUTH_ALLOW_INSECURE_DEFAULTS", "1")

# A stale database from a previous run would break "library starts empty"
# assertions, so start from a clean slate - but only delete a database this run
# created; an explicitly supplied DB_URL belongs to whoever supplied it.
database_file = _sqlite_file(os.environ["DB_URL"])
if owns_database and database_file is not None:
    for suffix in ("", "-wal", "-shm"):
        Path(f"{database_file}{suffix}").unlink(missing_ok=True)

# storage is owned by the test run: start from an empty tree so scans and
# uploads only ever see what the current test created
storage_root = Path(os.environ["FILE_STORAGE"])
if storage_root.exists():
    shutil.rmtree(storage_root)
storage_root.mkdir(parents=True, exist_ok=True)

# A run that created its own root owns it; do not leave it behind in /tmp.
if owns_database:
    atexit.register(shutil.rmtree, run_root, ignore_errors=True)
