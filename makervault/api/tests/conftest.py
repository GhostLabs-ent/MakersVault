import os
import tempfile
from pathlib import Path

# Tests must not depend on the developer's environment, and they must run
# without a reverse proxy in front of them. Everything here is set before any
# test module imports the application.
os.environ.setdefault("DB_URL", "sqlite:////tmp/makersvault-test.db")
os.environ.setdefault("FILE_STORAGE", "/tmp/makersvault-test-storage")
os.environ.setdefault("IMPORT_MOUNT_ON_STARTUP", "false")

# The published sample credentials (admin / super-secret) are what the smoke
# test logs in with; opt out of the insecure-defaults startup guard for tests
# only. The guard itself is covered explicitly in test_hardening.py.
os.environ.setdefault("AUTH_ALLOW_INSECURE_DEFAULTS", "1")

# A stale database from a previous run would break "library starts empty"
# assertions, so start from a clean slate.
for suffix in ("", "-wal", "-shm"):
    db_path = Path(f"/tmp/makersvault-test.db{suffix}")
    if db_path.exists():
        db_path.unlink()

# storage is owned by the test run: start from an empty tree so scans and
# uploads only ever see what the current test created
import shutil

storage_root = Path(os.environ["FILE_STORAGE"])
if storage_root.exists():
    shutil.rmtree(storage_root)
storage_root.mkdir(parents=True, exist_ok=True)
