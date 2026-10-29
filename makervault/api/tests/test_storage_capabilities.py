"""Snapshot capability detection, pinned against synthesised filesystem magics.

The magics below are test fixtures, not host facts: every detection test drives
``storage_capabilities.statfs_magic`` with a constant (or a path-keyed map) and
``MOUNTS_PATH`` with a fake mount table under ``tmp_path``. No test names
``/mnt/ceph``, reads the real storage root, or creates a ``.snap`` directory
outside the temporary tree that synthesises the CephFS case. The single host
smoke test at the bottom is the exception; it skips when there is no mount
table and never writes.

The endpoint test is the only one that needs accounts. It seeds an admin and a
viewer behind break-glass, then truncates them afterwards so the next module
still finds the break-glass login available.
"""

import ctypes
import json
import socket
import subprocess
import urllib.error
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

import config
import db
import login_throttle as login_throttle_module
import snapshot_btrfs
import snapshot_zfs
import storage_capabilities
from db import engine
from main import app
from migrations import run_migrations
from models import User, UserSession

ADMIN_USERNAME = "capability-admin"
ADMIN_PASSWORD = "capability-admin-1"
VIEWER_USERNAME = "capability-viewer"
VIEWER_PASSWORD = "capability-viewer-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}

CAPABILITY = storage_capabilities.VolumeCapability(
    roles=("library",),
    path="/data/library",
    fstype="ext",
    mount_point="/data",
    snapshot_method="none",
    usable=False,
    reason="no snapshot method for ext",
)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def truncate_accounts() -> None:
    with Session(engine) as session:
        session.execute(delete(UserSession))
        session.execute(delete(User))
        session.commit()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point storage at a temp root and make the default database in-memory.

    ``detect()`` defaults ``database_url`` to ``db.DB_URL``; an in-memory URL
    makes that default report the library volume only, so a test that wants a
    second volume must pass a real sqlite path explicitly.
    """
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(db, "DB_URL", "sqlite:///:memory:")
    run_migrations(engine)
    yield storage


@pytest.fixture(autouse=True)
def clean_accounts():
    """Start and finish every test without accounts; the endpoint test seeds its own."""
    run_migrations(engine)
    truncate_accounts()
    login_throttle_module.limiter.reset()
    yield
    truncate_accounts()
    login_throttle_module.limiter.reset()


def filesystem_snapshot(root: Path) -> tuple:
    """Paths, kinds and sizes of the whole tree; enough to prove nothing changed."""
    return tuple(
        sorted(
            (str(path.relative_to(root)) or ".", path.is_dir(), path.stat().st_size)
            for path in [root, *root.rglob("*")]
        )
    )


def write_mounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entries) -> Path:
    """Write a fake ``/proc/self/mounts`` and point the module at it."""
    lines = [f"device {mount_point} {fstype} rw 0 0" for mount_point, fstype in entries]
    mounts = tmp_path / "mounts"
    mounts.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(storage_capabilities, "MOUNTS_PATH", mounts)
    return mounts


def fake_magic(monkeypatch: pytest.MonkeyPatch, magic, only_for=None) -> None:
    """Return one magic for every path, or a per-resolved-path override."""
    if only_for is None:
        monkeypatch.setattr(storage_capabilities, "statfs_magic", lambda path: magic)
        return
    overrides = {str(Path(path).resolve()): value for path, value in only_for.items()}
    monkeypatch.setattr(storage_capabilities, "statfs_magic", lambda path: overrides.get(str(path), magic))


def fake_devices(monkeypatch: pytest.MonkeyPatch, mapping) -> None:
    """Return one device for every path (an int) or a per-path map."""
    if isinstance(mapping, int):
        monkeypatch.setattr(storage_capabilities, "device_id", lambda path: mapping)
        return
    monkeypatch.setattr(storage_capabilities, "device_id", lambda path: mapping.get(str(path)))


def make_library(tmp_path: Path) -> Path:
    library = tmp_path / "library"
    library.mkdir()
    return library


class FakeLibc:
    """A libc whose ``statfs`` writes a known ``f_type`` into the caller's buffer."""

    def __init__(self, magic: int, returncode: int = 0) -> None:
        self.magic = magic
        self.returncode = returncode

    def statfs(self, path, buffer_ref) -> int:
        if self.returncode == 0:
            value = self.magic
            if value & 0x80000000:
                # What a 32-bit C long reports: bit 31 becomes the sign, so the
                # read has to mask it back to the unsigned 32-bit magic.
                value -= 1 << 32
            ctypes.cast(buffer_ref._obj, ctypes.POINTER(ctypes.c_long))[0] = value
        return self.returncode


# --- the statfs read --------------------------------------------------------


@pytest.mark.parametrize(
    "magic",
    [
        storage_capabilities.CEPHFS_MAGIC,
        storage_capabilities.BTRFS_MAGIC,
        storage_capabilities.ZFS_MAGIC,
        0xEF53,
    ],
)
def test_the_statfs_buffer_reads_the_magic_through_a_c_long(tmp_path, monkeypatch, magic) -> None:
    """A sign-extended bit-31 magic must read back as its unsigned 32-bit value."""
    monkeypatch.setattr(storage_capabilities, "_libc", FakeLibc(magic))

    assert storage_capabilities.statfs_magic(tmp_path) == magic


def test_a_failing_statfs_call_reads_as_unknown(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage_capabilities, "_libc", FakeLibc(0, returncode=-1))

    assert storage_capabilities.statfs_magic(tmp_path) is None


# --- detection --------------------------------------------------------------


def test_cephfs_with_a_writable_snap_directory_is_usable(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    (library / ".snap").mkdir()
    fake_magic(monkeypatch, storage_capabilities.CEPHFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "ceph"), ("/", "ext4")])

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    assert len(volumes) == 1
    volume = volumes[0]
    assert volume.snapshot_method == "cephfs_snapdir"
    assert volume.usable is True
    assert volume.fstype == "ceph"


def test_cephfs_without_a_snap_directory_is_not_usable_and_creates_nothing(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, storage_capabilities.CEPHFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "ceph"), ("/", "ext4")])

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.snapshot_method == "cephfs_snapdir"
    assert volume.usable is False
    assert ".snap" in volume.reason
    assert not (library / ".snap").exists()


def test_cephfs_with_an_unwritable_snap_directory_is_not_usable(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    (library / ".snap").mkdir()
    fake_magic(monkeypatch, storage_capabilities.CEPHFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "ceph"), ("/", "ext4")])
    monkeypatch.setattr(storage_capabilities.os, "access", lambda path, mode: False)

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.snapshot_method == "cephfs_snapdir"
    assert volume.usable is False
    assert "writable" in volume.reason


def test_ext_volume_has_no_snapshot_method(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, 0xEF53)
    write_mounts(tmp_path, monkeypatch, [(str(library), "ext4"), ("/", "ext4")])

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.snapshot_method == "none"
    assert volume.usable is False
    assert "ext" in volume.reason


@pytest.mark.parametrize(
    ("magic", "fstype"),
    [
        (0x01021994, "tmpfs"),
        (0x794C7630, "overlay"),
        (0x6969, "nfs"),
        (0xFF534D42, "cifs"),
    ],
)
def test_named_filesystems_without_a_snapshot_method(tmp_path, monkeypatch, magic, fstype) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, magic)
    write_mounts(tmp_path, monkeypatch, [(str(library), fstype), ("/", "ext4")])

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.fstype == fstype
    assert volume.snapshot_method == "none"
    assert volume.usable is False
    assert fstype in volume.reason


def test_unknown_magic_claims_no_method(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, 0x12345678)
    write_mounts(tmp_path, monkeypatch, [(str(library), "mystery"), ("/", "ext4")])

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.fstype == "unknown"
    assert volume.snapshot_method == "none"
    assert volume.usable is False
    assert "unknown" in volume.reason


def test_statfs_failure_reports_unknown_without_raising(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, None)
    write_mounts(tmp_path, monkeypatch, [(str(library), "ext4"), ("/", "ext4")])

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.fstype == "unknown"
    assert volume.snapshot_method == "none"
    assert volume.usable is False


# --- volume merging ---------------------------------------------------------


def test_library_and_database_on_the_same_device_merge_into_one_volume(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    database_dir = tmp_path / "data"
    database_dir.mkdir()
    fake_magic(monkeypatch, 0xEF53)
    write_mounts(tmp_path, monkeypatch, [(str(library), "ext4"), ("/", "ext4")])
    fake_devices(monkeypatch, 42)

    volumes = storage_capabilities.detect(
        library_root=library,
        database_url=f"sqlite:///{database_dir / 'app.db'}",
    )

    assert len(volumes) == 1
    assert list(volumes[0].roles) == ["library", "database"]
    assert volumes[0].path == str(library.resolve())


def test_library_and_database_on_different_devices_are_separate_volumes(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    database_dir = tmp_path / "data"
    database_dir.mkdir()
    fake_magic(monkeypatch, 0xEF53)
    write_mounts(tmp_path, monkeypatch, [(str(library), "ext4"), ("/", "ext4")])
    fake_devices(monkeypatch, {str(library.resolve()): 1, str(database_dir.resolve()): 2})

    volumes = storage_capabilities.detect(
        library_root=library,
        database_url=f"sqlite:///{database_dir / 'app.db'}",
    )

    assert len(volumes) == 2
    assert list(volumes[0].roles) == ["library"]
    assert list(volumes[1].roles) == ["database"]
    assert volumes[1].path == str(database_dir.resolve())


def test_the_cephfs_library_and_ext_database_pair_report_usable_and_none(tmp_path, monkeypatch) -> None:
    """AC-1: the canonical deployment pair, both answers in one report."""
    library = make_library(tmp_path)
    (library / ".snap").mkdir()
    database_dir = tmp_path / "data"
    database_dir.mkdir()
    fake_magic(
        monkeypatch,
        None,
        only_for={library: storage_capabilities.CEPHFS_MAGIC, database_dir: 0xEF53},
    )
    write_mounts(tmp_path, monkeypatch, [(str(library), "ceph"), (str(database_dir), "ext4"), ("/", "ext4")])
    fake_devices(monkeypatch, {str(library.resolve()): 1, str(database_dir.resolve()): 2})

    volumes = storage_capabilities.detect(
        library_root=library,
        database_url=f"sqlite:///{database_dir / 'app.db'}",
    )

    library_volume, database_volume = volumes
    assert list(library_volume.roles) == ["library"]
    assert library_volume.fstype == "ceph"
    assert library_volume.snapshot_method == "cephfs_snapdir"
    assert library_volume.usable is True
    assert list(database_volume.roles) == ["database"]
    assert database_volume.fstype == "ext"
    assert database_volume.snapshot_method == "none"
    assert database_volume.usable is False


@pytest.mark.parametrize("database_url", ["postgresql://x/y", "sqlite:///:memory:"])
def test_a_non_sqlite_or_in_memory_database_reports_only_the_library_volume(tmp_path, monkeypatch, database_url) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, 0xEF53)
    write_mounts(tmp_path, monkeypatch, [(str(library), "ext4"), ("/", "ext4")])

    volumes = storage_capabilities.detect(library_root=library, database_url=database_url)

    assert len(volumes) == 1
    assert list(volumes[0].roles) == ["library"]


# --- zfs and btrfs ----------------------------------------------------------

ALLOW_ALL = "---- Permissions on tank/library ----\nLocal permissions:\n    user alice snapshot,destroy,mount\n"


def fake_zfs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_output: str = ALLOW_ALL,
    dataset: str = "tank/library",
    error: Optional[BaseException] = None,
) -> list[list[str]]:
    """Scripted ``zfs`` for the capability tests: records every argv, answers list and allow."""

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        if error is not None:
            raise error
        if argv[1] == "list":
            return subprocess.CompletedProcess(list(argv), 0 if dataset else 1, f"{dataset}\n", "")
        return subprocess.CompletedProcess(list(argv), 0, allow_output, "")

    calls: list[list[str]] = []
    monkeypatch.setattr(snapshot_zfs, "run_zfs", runner)
    return calls


def test_zfs_without_the_binary_is_not_usable(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, storage_capabilities.ZFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "zfs"), ("/", "ext4")])
    fake_zfs(monkeypatch, error=OSError("zfs: not found"))

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.snapshot_method == "zfs_dataset"
    assert volume.usable is False
    assert "zfs" in volume.reason


def test_zfs_dataset_with_delegated_snapshot_rights_is_usable(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, storage_capabilities.ZFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "zfs"), ("/", "ext4")])
    calls = fake_zfs(monkeypatch)

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.snapshot_method == "zfs_dataset"
    assert volume.usable is True
    assert "tank/library" in volume.reason
    # The capability report now asks the provider's own probe: an argv list for
    # this principal, with a ``--`` before the operand.
    assert calls[-1] == ["zfs", "allow", "--", "tank/library"]


def test_zfs_dataset_that_cannot_be_resolved_is_not_usable(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, storage_capabilities.ZFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "zfs"), ("/", "ext4")])
    fake_zfs(monkeypatch, dataset="")

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.snapshot_method == "zfs_dataset"
    assert volume.usable is False
    assert "could not resolve" in volume.reason


def test_zfs_capability_refuses_a_root_that_is_a_dataset_subdirectory(tmp_path, monkeypatch) -> None:
    # B2: the old inline check only looked for the substring "snapshot" in `zfs
    # allow`, so a library that is a subdirectory of a delegated dataset reported
    # usable -- and a strict trash purge then 409s, because a subdirectory has no
    # .zfs view of its own.
    dataset_root = tmp_path / "tank"
    dataset_root.mkdir()
    library = dataset_root / "library"
    library.mkdir()
    fake_magic(monkeypatch, storage_capabilities.ZFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(dataset_root), "zfs"), ("/", "ext4")])
    fake_zfs(monkeypatch)

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.snapshot_method == "zfs_dataset"
    assert volume.usable is False
    assert "subdirectory" in volume.reason


def test_zfs_capability_refuses_a_snapshot_only_delegation(tmp_path, monkeypatch) -> None:
    # B2: "snapshot" alone was enough for the old substring check, so the volume
    # reported usable and `zfs destroy` failed at prune time.
    library = make_library(tmp_path)
    fake_magic(monkeypatch, storage_capabilities.ZFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "zfs"), ("/", "ext4")])
    fake_zfs(monkeypatch, allow_output="Local permissions:\n\tuser alice snapshot\n")

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.snapshot_method == "zfs_dataset"
    assert volume.usable is False
    assert "destroy" in volume.reason
    assert "mount" in volume.reason


def test_cephfs_ext_and_tmpfs_detection_never_enters_a_subprocess(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    write_mounts(tmp_path, monkeypatch, [(str(library), "ext4"), ("/", "ext4")])

    def forbidden(*args, **kwargs):
        raise AssertionError("a subprocess was entered for a non-zfs filesystem")

    monkeypatch.setattr(snapshot_zfs, "run_zfs", forbidden)

    for magic in (storage_capabilities.CEPHFS_MAGIC, 0xEF53, 0x01021994):
        fake_magic(monkeypatch, magic)
        volumes = storage_capabilities.detect(library_root=library, database_url="sqlite:///:memory:")
        assert len(volumes) == 1


def test_btrfs_without_a_sidecar_url_is_not_usable_and_opens_no_socket(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, storage_capabilities.BTRFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "btrfs"), ("/", "ext4")])
    monkeypatch.setattr(config, "SNAPSHOT_BTRFS_SIDECAR_URL", "")

    def forbidden_socket(*args, **kwargs):
        raise AssertionError("a socket was opened for a disabled btrfs sidecar")

    monkeypatch.setattr(socket, "socket", forbidden_socket)

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    # The method surviving proves no socket was attempted: a raised exception
    # would have been swallowed into "capability detection failed" / "none".
    assert volume.snapshot_method == "btrfs_subvol"
    assert volume.usable is False
    assert "CONFIGURATION.md" in volume.reason


def test_btrfs_with_an_unreachable_sidecar_names_the_state(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, storage_capabilities.BTRFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "btrfs"), ("/", "ext4")])
    monkeypatch.setattr(config, "SNAPSHOT_BTRFS_SIDECAR_URL", "http://sidecar.test:8765")

    def refuse(method, path, payload=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(snapshot_btrfs, "http_call", refuse)

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.snapshot_method == "btrfs_subvol"
    assert volume.usable is False
    assert "unreachable" in volume.reason


def test_btrfs_with_a_ready_sidecar_is_usable(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    fake_magic(monkeypatch, storage_capabilities.BTRFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "btrfs"), ("/", "ext4")])
    monkeypatch.setattr(config, "SNAPSHOT_BTRFS_SIDECAR_URL", "http://sidecar.test:8765")
    # A ready sidecar must also be writing the store this API lists: same path here.
    health = json.dumps({"state": "ready", "store": str(library / ".snap"), "store_exists": False})
    monkeypatch.setattr(snapshot_btrfs, "http_call", lambda method, path, payload=None: (200, health))

    volumes = storage_capabilities.detect(library_root=library, database_url=None)

    volume = volumes[0]
    assert volume.snapshot_method == "btrfs_subvol"
    assert volume.usable is True


# --- side-effect freedom ----------------------------------------------------


def test_detection_writes_nothing(tmp_path, monkeypatch) -> None:
    library = make_library(tmp_path)
    (library / "existing").mkdir()
    (library / "existing" / "model.stl").write_bytes(b"model")
    fake_magic(monkeypatch, storage_capabilities.CEPHFS_MAGIC)
    write_mounts(tmp_path, monkeypatch, [(str(library), "ceph"), ("/", "ext4")])
    before = filesystem_snapshot(tmp_path)

    storage_capabilities.detect(library_root=library, database_url="sqlite:///:memory:")

    assert filesystem_snapshot(tmp_path) == before
    assert not (library / ".snap").exists()


# --- the endpoint -----------------------------------------------------------


def test_storage_capabilities_endpoint_serves_admin_and_viewer(monkeypatch) -> None:
    monkeypatch.setattr(storage_capabilities, "detect", lambda: [CAPABILITY])

    with TestClient(app) as client:
        glass = client.post("/login", json=BREAK_GLASS)
        assert glass.status_code == 200, glass.text
        admin = client.post(
            "/users",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "role": "admin"},
            headers=bearer(glass.json()["token"]),
        )
        assert admin.status_code == 201, admin.text
        admin_token = client.post("/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}).json()["token"]
        viewer = client.post(
            "/users",
            json={"username": VIEWER_USERNAME, "password": VIEWER_PASSWORD, "role": "viewer"},
            headers=bearer(admin_token),
        )
        assert viewer.status_code == 201, viewer.text
        viewer_token = client.post("/login", json={"username": VIEWER_USERNAME, "password": VIEWER_PASSWORD}).json()["token"]

        admin_response = client.get("/storage/capabilities", headers=bearer(admin_token))
        viewer_response = client.get("/storage/capabilities", headers=bearer(viewer_token))
        anonymous_response = client.get("/storage/capabilities")

    assert admin_response.status_code == 200, admin_response.text
    assert viewer_response.status_code == 200, viewer_response.text
    assert anonymous_response.status_code == 401
    assert viewer_response.json() == admin_response.json()

    body = admin_response.json()
    assert body["volumes"]
    item = body["volumes"][0]
    assert set(item) == {"roles", "path", "fstype", "mount_point", "snapshot_method", "usable", "reason"}
    assert isinstance(item["roles"], list)
    assert isinstance(item["path"], str)
    assert isinstance(item["fstype"], str)
    assert isinstance(item["mount_point"], str)
    assert isinstance(item["snapshot_method"], str)
    assert isinstance(item["usable"], bool)
    assert isinstance(item["reason"], str)


# --- host smoke and docs ----------------------------------------------------


def test_the_real_mount_table_resolves_a_temporary_directory(tmp_path) -> None:
    """AC-1, on the host only: this is the one test that reads the real table."""
    if not storage_capabilities.MOUNTS_PATH.exists():
        pytest.skip("host-only: no /proc/self/mounts")

    table = storage_capabilities.mount_table()
    assert table

    resolved = tmp_path.resolve()
    device = storage_capabilities.device_id(resolved)
    mount = storage_capabilities.resolve_mount(resolved, device)
    assert mount is not None
    mount_point, mount_fstype = mount
    assert mount_point == resolved or mount_point in resolved.parents

    magic = storage_capabilities.statfs_magic(resolved)
    if magic is not None:
        assert storage_capabilities.fstype_name(magic) != "unknown"
        assert storage_capabilities.fstype_name(magic) == storage_capabilities.normalised_fstype(mount_fstype)


def test_configuration_docs_describe_storage_snapshot_capabilities() -> None:
    path = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "CONFIGURATION.md"
    # The API image build context is makervault/api, so makervault/docs is absent there.
    # This must be a function-level skip, not a module-level one: the other tests in
    # this module still have to run inside the image.
    if not path.exists():
        pytest.skip("host-only: makervault/docs is outside the API image build context")

    text = path.read_text(encoding="utf-8")
    assert "## Storage snapshot capabilities" in text
    for needle in ("GET /storage/capabilities", "0x00C36400", ".snap", "zfs", "btrfs"):
        assert needle in text
