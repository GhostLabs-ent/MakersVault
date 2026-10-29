"""The one test that needs a real snapshottable filesystem, opt-in only.

CI has no CephFS mount and must not assume one, so the whole module is skipped
unless ``SNAPSHOT_INTEGRATION=1``. When it does run it proves the one thing a
synthesised ``.snap`` directory cannot: that a CephFS snapshot is a copy-on-write
view, so bytes written to the live file after the snapshot do not appear through
``path_for``.

Every guard below exists so a mistyped variable can never point this test at real
data: the root must be named like a scratch directory, must be at least three
path components deep, and must be neither the library root nor inside it nor a
parent of it. The test still writes only inside a subdirectory it creates and
removes in a ``finally``.

The ``os.access`` check is the same caveat S1 documents: as root it is always
true, so a container running as root can pass the writability guard on a
``.snap`` the service principal could not use.
"""

import os
import shutil
from pathlib import Path

import pytest

import db
import snapshots

pytestmark = pytest.mark.skipif(
    os.environ.get("SNAPSHOT_INTEGRATION") != "1",
    reason="set SNAPSHOT_INTEGRATION=1 on a host with a real snapshottable mount",
)

SCRATCH_PREFIX = "makersvault-snapshot-scratch-"
MIN_SCRATCH_COMPONENTS = 3


def scratch_root() -> Path:
    """The explicit scratch directory, or a skip that says exactly what is wrong."""
    raw = os.environ.get("SNAPSHOT_INTEGRATION_ROOT", "").strip()
    if not raw:
        pytest.skip("SNAPSHOT_INTEGRATION_ROOT is unset: name an explicit scratch directory")
    root = Path(raw)
    if not root.is_dir():
        pytest.skip(f"SNAPSHOT_INTEGRATION_ROOT {root} is not an existing directory")
    resolved = root.resolve()
    if not resolved.name.startswith(SCRATCH_PREFIX):
        pytest.skip(f"{resolved} is not a {SCRATCH_PREFIX}* scratch directory")
    if len(resolved.parts) < MIN_SCRATCH_COMPONENTS:
        pytest.skip(f"{resolved} is too close to the filesystem root to be a scratch directory")
    library = Path(db.STORAGE).resolve()
    if resolved == library or resolved in library.parents or library in resolved.parents:
        pytest.skip(f"{resolved} is, contains, or is inside the library root {library}")
    return resolved


def test_a_cephfs_snapshot_is_a_copy_on_write_view() -> None:
    root = scratch_root()
    scratch = root / f"tree-{os.getpid()}"
    scratch.mkdir()
    try:
        live = scratch / "sub" / "model.bin"
        live.parent.mkdir()
        before = b"solid pre-snapshot\n"
        live.write_bytes(before)

        snapshot_dir = scratch / snapshots.SNAPSHOT_DIRNAME
        if not snapshot_dir.is_dir():
            pytest.skip(f"{snapshot_dir} is not a directory: this root is not a CephFS snap directory")
        if not os.access(snapshot_dir, os.W_OK):
            pytest.skip(f"{snapshot_dir} is not writable by this process")

        provider = snapshots.CephFsSnapdirProvider(scratch, policy=snapshots.RetentionPolicy())
        created = provider.create(snapshots.SnapshotReason.MANUAL)
        assert [snapshot.name for snapshot in provider.list()] == [created.snapshot.name]

        after = b"solid post-snapshot\n"
        live.write_bytes(after)

        view = provider.path_for(created.snapshot.name, "sub/model.bin")
        assert view.read_bytes() == before

        provider.delete(created.snapshot.name)

        assert provider.list() == []
        assert not (snapshot_dir / created.snapshot.name).exists()
        assert live.read_bytes() == after
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
