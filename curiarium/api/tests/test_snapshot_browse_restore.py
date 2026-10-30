"""The S4 snapshot HTTP surface: browse, restore, retention, create, delete.

The provider layer is S2's and is tested in `test_snapshots.py`; this module drives
`routers/snapshots.py` and `snapshot_service.py` where the things that matter are
the ones a unit test cannot see: a restore must never write a snapshot's original
live path, never overwrite an existing destination, and never unlink the snapshot
source it reads from. The ticket's most dangerous line is the publish step of a
restore, so `test_restore_never_unlinks_the_snapshot_source` fingerprints the
whole snapshot view before and after a full restore.

Every test works in a temporary storage root (`db.STORAGE` and the other storage
bindings are patched by `isolated_storage`), every route test pins
`main.start_scan` so no background scan thread starts, and the retention policy is
saved and restored around each test: it is operator configuration, and a policy
written here must not leak into another module.
"""

import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
import snapshot_fakes
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import asset_file_service
import asset_service
import audit
import db
import library_scan
import main
import permissions
import snapshots
import storage_capabilities
from db import engine
from main import app
from migrations import run_migrations
from models import AppConfig, Asset, AssetFile, AuditEvent, Folder

REQUEST_ID_HEADER = "X-Request-ID"

# A name the provider would write, and nothing in the store: the well-formed but
# absent case for the delete and browse routes.
ABSENT_SNAPSHOT = "20200101T000000Z-manual-000000"

RETENTION_KEYS = (
    snapshots.RETENTION_KEEP_LAST_N_KEY,
    snapshots.RETENTION_KEEP_DAILY_KEY,
    snapshots.RETENTION_MAX_AGE_DAYS_KEY,
    snapshots.RETENTION_HARD_CAP_KEY,
)


# --- infrastructure ---------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage and thumbnails at temp roots, then undo the rows a test made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    monkeypatch.setattr(main, "THUMBS", storage / "thumbs")

    # The schema is created by the app lifespan; a single-file run needs it first.
    run_migrations(engine)
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        files_before = {row.id for row in session.exec(select(AssetFile))}
    yield storage
    with Session(engine) as session:
        for row in list(session.exec(select(AssetFile))):
            if row.id not in files_before:
                session.delete(row)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        session.commit()


@pytest.fixture(autouse=True)
def restored_retention(isolated_storage: Path) -> None:
    """Put the four retention settings back after each test, exactly as they were.

    They are operator configuration, and `POST /snapshots/retention` writes them;
    a policy set here must not change any later test's pruning. The rows are saved
    and restored raw rather than through `snapshots.set_retention_policy` so a
    configuration that had no rows still has none afterwards: `test_snapshots.py`
    asserts the table starts empty.
    """
    with Session(engine) as session:
        previous = {
            key: (row.value if (row := session.get(AppConfig, key)) is not None else None)
            for key in RETENTION_KEYS
        }
    yield
    with Session(engine) as session:
        for key, value in previous.items():
            row = session.get(AppConfig, key)
            if value is None:
                if row is not None:
                    session.delete(row)
            elif row is None:
                session.add(AppConfig(key=key, value=value))
            else:
                row.value = value
        session.commit()


@pytest.fixture(autouse=True)
def no_background_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """A restore ends by asking for a scan; no test here wants the real thread.

    `seams.start_scan` resolves `main.start_scan` at call time, so this is the
    same patch point the rest of the suite uses. A test that wants the refusal
    path patches it again with `lambda: False`.
    """
    monkeypatch.setattr(main, "start_scan", lambda: True)


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def request_id_for(test_name: str) -> str:
    """A unique, header-legal id: letters, digits and dashes only."""
    return f"{test_name}-{uuid4().hex}"


def admin_headers(client: TestClient, value: Optional[str] = None) -> dict:
    """Bearer token (or nothing when auth is disabled), plus the request id."""
    health = client.get("/health").json()
    headers = {}
    if health.get("auth_required"):
        token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
        headers["Authorization"] = f"Bearer {token}"
    if value is not None:
        headers[REQUEST_ID_HEADER] = value
    return headers


def events_for(value: str) -> list[AuditEvent]:
    """Every audit row this request wrote; the table is append-only, so never all of it."""
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.request_id == value)))


def write_file(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(path: Path) -> tuple[str, int, int]:
    """(sha256, size, mtime_ns): bytes and the timestamps a copy must not disturb."""
    stat = path.stat()
    return sha256_of(path), stat.st_size, stat.st_mtime_ns


def tree_fingerprints(root: Path) -> dict[str, tuple[str, int, int]]:
    """Every file under `root`, keyed by its POSIX-relative name."""
    return {
        path.relative_to(root).as_posix(): fingerprint(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def seed_library(root: Path) -> Path:
    """A few real files plus a nested directory, and one file that is easy to sha256.

    Returns the easy file: it is the subject of the single-file restores, and its
    bytes are short enough to spell out in an assertion.
    """
    write_file(root / "scene" / "notes.txt", b"notes\n")
    write_file(root / "scene" / "props" / "lamp.stl", b"solid lamp\nendsolid lamp\n")
    write_file(root / "pair" / "one.stl", b"one\n")
    write_file(root / "pair" / "two.stl", b"two\n")
    return write_file(root / "cube.stl", b"solid cube\nendsolid cube\n")


def make_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    policy: Optional[snapshots.RetentionPolicy] = None,
) -> tuple[str, Path]:
    """Install the tree-copy fake over `root`, take one snapshot, return (name, view).

    The create is called without a context, so it writes no rows: each test owns
    exactly the rows its own route call writes. `policy` sets the instance's
    policy because `snapshot_fakes` pins `RetentionPolicy()` at construction and
    a provider reads its policy once, when it is built - so a test that wants
    retention to prune passes the tight policy here.
    """
    provider = snapshot_fakes.use_tree_copy(monkeypatch, root)
    if policy is not None:
        provider.policy = policy
    created = provider.create()
    return created.snapshot.name, provider.path_for(created.snapshot.name)


# --- AC-1: a restore is byte-identical --------------------------------------


def test_ac1_a_restored_file_is_byte_identical_to_the_snapshot(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1: one file restored, compared by hash and by size, not by eyeball."""
    storage = isolated_storage
    seed_library(storage)
    name, view = make_snapshot(monkeypatch, storage)
    source = view / "cube.stl"

    response = client.post(f"/snapshots/{name}/restore", json={"path": "cube.stl"}, headers=admin_headers(client))

    assert response.status_code == 201, response.text
    destination = storage / response.json()["destination"]
    assert sha256_of(destination) == sha256_of(source)
    assert destination.stat().st_size == source.stat().st_size
    assert destination.read_bytes() == b"solid cube\nendsolid cube\n"


# --- AC-1b: the snapshot is never the thing that moves ---------------------


def test_restore_never_unlinks_the_snapshot_source(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1b: a restore reads the snapshot and moves only its own `.part` copy.

    This is THE test for the ticket's most dangerous line. Publishing the copy
    through `asset_service._move_without_clobber` moves (link + unlink) its first
    argument; doing that from the snapshot would delete the snapshot a restore
    just used. The whole snapshot is restored here, then every source name, hash,
    size and mtime is compared with what was there before.
    """
    storage = isolated_storage
    seed_library(storage)
    name, view = make_snapshot(monkeypatch, storage)
    before = tree_fingerprints(view)
    assert set(before) == {"cube.stl", "pair/one.stl", "pair/two.stl", "scene/notes.txt", "scene/props/lamp.stl"}

    response = client.post(f"/snapshots/{name}/restore", json={"path": ""}, headers=admin_headers(client))

    assert response.status_code == 201, response.text
    assert response.json()["destination"] == f"recovered/{name}"
    assert response.json()["files"] == len(before)
    assert tree_fingerprints(view) == before, "the snapshot source must be byte-for-byte what it was"
    for relative in before:
        assert (view / relative).is_file(), f"the restore unlinked the snapshot's {relative}"


# --- AC-2: recovery lands under recovered/, never in place -----------------


def test_ac2_a_restore_lands_under_recovered_and_never_in_place(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-2: the destination is `recovered/<name>/<rel>`, and the live file is untouched."""
    storage = isolated_storage
    live = seed_library(storage)
    original = live.read_bytes()
    name, view = make_snapshot(monkeypatch, storage)
    source = view / "cube.stl"

    response = client.post(f"/snapshots/{name}/restore", json={"path": "cube.stl"}, headers=admin_headers(client))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["destination"] == f"recovered/{name}/cube.stl"
    assert (storage / body["destination"]).read_bytes() == source.read_bytes()
    assert live.read_bytes() == original, "a restore must not write the original live path"
    assert source.read_bytes() == original, "a restore must not modify the snapshot it reads"


# --- AC-3: a restore never overwrites --------------------------------------


def test_ac3_restoring_twice_refuses_and_leaves_no_residue(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-3: the second restore is a 409 that names the destination it refused to clobber."""
    storage = isolated_storage
    seed_library(storage)
    name, _ = make_snapshot(monkeypatch, storage)
    headers = admin_headers(client)

    first = client.post(f"/snapshots/{name}/restore", json={"path": "cube.stl"}, headers=headers)
    assert first.status_code == 201, first.text
    destination = first.json()["destination"]
    first_bytes = (storage / destination).read_bytes()

    second = client.post(f"/snapshots/{name}/restore", json={"path": "cube.stl"}, headers=headers)

    assert second.status_code == 409, second.text
    detail = second.json()["detail"]
    assert destination in detail
    assert "never overwrite" in detail
    assert (storage / destination).read_bytes() == first_bytes
    assert list(storage.rglob("*.part")) == [], "the copy is either published or gone"


def test_ac3b_a_directory_restore_is_all_or_nothing(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-3b: a directory with an occupied destination is refused before the first byte."""
    storage = isolated_storage
    seed_library(storage)
    name, _ = make_snapshot(monkeypatch, storage)
    headers = admin_headers(client)

    first = client.post(f"/snapshots/{name}/restore", json={"path": "pair"}, headers=headers)
    assert first.status_code == 201, first.text
    destination = first.json()["destination"]
    destination_dir = storage / destination
    assert sorted(path.name for path in destination_dir.iterdir()) == ["one.stl", "two.stl"]

    second = client.post(f"/snapshots/{name}/restore", json={"path": "pair"}, headers=headers)

    assert second.status_code == 409, second.text
    assert destination in second.json()["detail"]
    assert sorted(path.name for path in destination_dir.iterdir()) == ["one.stl", "two.stl"]
    assert list(storage.rglob("*.part")) == []

    # Plant only the second destination: the preflight must refuse the whole
    # restore, so the file it would have written first never appears.
    shutil.rmtree(destination_dir)
    write_file(destination_dir / "two.stl", b"planted\n")

    third = client.post(f"/snapshots/{name}/restore", json={"path": "pair"}, headers=headers)

    assert third.status_code == 409, third.text
    assert sorted(path.name for path in destination_dir.iterdir()) == ["two.stl"]
    assert not (destination_dir / "one.stl").exists(), "the preflight refuses before the first byte"
    assert list(storage.rglob("*.part")) == []


# --- AC-4: a recovered file is a library asset -----------------------------


def test_ac4_a_scan_registers_the_restored_file_and_skips_the_snapshot_store(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-4: `recovered/` is scan-visible and `.snap` stays hidden."""
    storage = isolated_storage
    seed_library(storage)
    name, _ = make_snapshot(monkeypatch, storage)

    response = client.post(f"/snapshots/{name}/restore", json={"path": "cube.stl"}, headers=admin_headers(client))

    assert response.status_code == 201, response.text
    destination = response.json()["destination"]
    library_scan.scan_storage_root()

    with Session(engine) as session:
        paths = {asset.storage_path for asset in session.exec(select(Asset)) if asset.storage_path is not None}
    assert destination in paths
    assert not [path for path in paths if path.split("/")[0] == snapshots.SNAPSHOT_DIRNAME], (
        "the snapshot store is a hidden directory and must never be registered"
    )


# --- AC-5: browse and restore refuse escapes --------------------------------


ESCAPES = [
    pytest.param("../outside.txt", id="parent-escape"),
    pytest.param("/etc/passwd", id="absolute"),
    pytest.param(".snap/x", id="snapshot-store"),
    pytest.param("thumbs/x", id="thumbs"),
    pytest.param(".trash/x", id="trash"),
]


@pytest.mark.parametrize("path", ESCAPES)
def test_ac5_browse_and_restore_refuse_an_escape(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """AC-5: both routes go through `SnapshotPathError`, so both answer 400."""
    storage = isolated_storage
    seed_library(storage)
    name, _ = make_snapshot(monkeypatch, storage)
    headers = admin_headers(client)

    browse = client.get(f"/snapshots/{name}/browse", params={"path": path}, headers=headers)
    restore = client.post(f"/snapshots/{name}/restore", json={"path": path}, headers=headers)

    assert browse.status_code == 400, browse.text
    assert restore.status_code == 400, restore.text


def test_ac5_a_missing_path_is_not_found_on_restore(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-5: a missing path in an existing snapshot is `SnapshotNotFound` on restore.

    A browse of a missing path answers 400 rather than 404: `browse_out` refuses
    anything that is not a directory with `SnapshotPathError`, and the single
    status mapping (400/404/409/409/500) makes a non-directory a path error, not a
    missing snapshot. The 404 browse case is a missing snapshot, asserted below.
    """
    storage = isolated_storage
    seed_library(storage)
    name, _ = make_snapshot(monkeypatch, storage)
    headers = admin_headers(client)

    restore = client.post(f"/snapshots/{name}/restore", json={"path": "not-here.stl"}, headers=headers)
    browse = client.get(f"/snapshots/{name}/browse", params={"path": "not-here.stl"}, headers=headers)
    absent = client.get(f"/snapshots/{ABSENT_SNAPSHOT}/browse", headers=headers)

    assert restore.status_code == 404, restore.text
    assert "not in snapshot" in restore.json()["detail"]
    assert browse.status_code == 400, browse.text
    assert "is not a directory" in browse.json()["detail"]
    assert absent.status_code == 404, absent.text


# --- a destination a restore cannot use -------------------------------------


def test_an_empty_directory_restore_creates_the_destination_it_names(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recovery with no files still names a path, so the path has to exist."""
    storage = isolated_storage
    seed_library(storage)
    (storage / "empty").mkdir()
    name, _ = make_snapshot(monkeypatch, storage)

    response = client.post(f"/snapshots/{name}/restore", json={"path": "empty"}, headers=admin_headers(client))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["files"] == 0
    assert body["bytes"] == 0
    assert (storage / body["destination"]).is_dir()


def test_a_file_where_a_directory_must_go_is_a_409_not_a_500(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blocked parent path refuses the restore instead of failing a `mkdir`."""
    storage = isolated_storage
    seed_library(storage)
    name, _ = make_snapshot(monkeypatch, storage)
    headers = admin_headers(client)
    write_file(storage / "recovered" / name / "pair", b"in the way\n")

    response = client.post(f"/snapshots/{name}/restore", json={"path": "pair"}, headers=headers)

    assert response.status_code == 409, response.text
    assert f"recovered/{name}/pair" in response.json()["detail"]
    assert (storage / "recovered" / name / "pair").read_bytes() == b"in the way\n"
    assert list(storage.rglob("*.part")) == []


def test_a_file_above_the_recovered_root_is_a_409_not_a_500(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same refusal one level up: `recovered/` itself cannot be a file.

    `mkdir` would raise `NotADirectoryError` on the way down, which without the
    translation is a 500 for a request that wrote nothing.
    """
    storage = isolated_storage
    seed_library(storage)
    name, _ = make_snapshot(monkeypatch, storage)
    write_file(storage / "recovered", b"in the way\n")

    response = client.post(f"/snapshots/{name}/restore", json={"path": "cube.stl"}, headers=admin_headers(client))

    assert response.status_code == 409, response.text
    assert "recovered" in response.json()["detail"]
    assert (storage / "recovered").read_bytes() == b"in the way\n"
    assert list(storage.rglob("*.part")) == []


# --- the listing S5 navigates with -------------------------------------------


def test_browse_lists_directories_first_then_names_with_posix_paths(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The browse entry shape, pinned: S5 navigates with `entry.path`.

    Directories come before files and each group is name-sorted; `path` is always
    snapshot-relative POSIX so the client can join it onto `/browse?path=` without
    knowing the host separator; a directory has no size.
    """
    storage = isolated_storage
    seed_library(storage)
    name, _ = make_snapshot(monkeypatch, storage)
    headers = admin_headers(client)

    listing = client.get(f"/snapshots/{name}/browse", params={"path": ""}, headers=headers)

    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["snapshot"] == name
    assert body["path"] == ""
    entries = body["entries"]
    # The rule, not a hardcoded set: the snapshot is a view of the whole storage
    # tree, so the app-owned `thumbs` directory is legitimately in it too.
    keys = [(0 if entry["is_dir"] else 1, entry["name"]) for entry in entries]
    assert keys == sorted(keys), "directories first, then name-sorted"
    by_name = {entry["name"]: entry for entry in entries}
    assert by_name["pair"]["is_dir"] is True
    assert by_name["pair"]["size"] is None
    assert by_name["scene"]["is_dir"] is True
    assert by_name["cube.stl"]["is_dir"] is False
    assert by_name["cube.stl"]["size"] == len(b"solid cube\nendsolid cube\n")
    for entry in entries:
        assert entry["path"] == entry["name"], "a root entry's path is its name"
        modified = datetime.fromisoformat(entry["modified_at"])
        assert modified.tzinfo is not None

    nested = client.get(f"/snapshots/{name}/browse", params={"path": "scene"}, headers=headers)

    assert nested.status_code == 200, nested.text
    assert nested.json()["path"] == "scene"
    assert [entry["path"] for entry in nested.json()["entries"]] == ["scene/props", "scene/notes.txt"]


# --- AC-6: a restore writes exactly one row; a browse writes none -----------


def test_ac6_restore_writes_one_row_and_browse_writes_none(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-6: one `snapshot.restore` row naming the snapshot, and nothing for a GET."""
    storage = isolated_storage
    seed_library(storage)
    name, view = make_snapshot(monkeypatch, storage)
    value = request_id_for("ac6")

    response = client.post(
        f"/snapshots/{name}/restore", json={"path": "cube.stl"}, headers=admin_headers(client, value)
    )

    assert response.status_code == 201, response.text
    body = response.json()
    rows = events_for(value)
    assert [row.action for row in rows] == [audit.SNAPSHOT_RESTORE]
    row = rows[0]
    assert row.target == name
    assert json.loads(row.detail_json) == {
        "path": "cube.stl",
        "destination": body["destination"],
        "files": 1,
        "bytes": (view / "cube.stl").stat().st_size,
        "scan_started": True,
    }

    browse_value = request_id_for("ac6-browse")
    browse = client.get(f"/snapshots/{name}/browse", params={"path": ""}, headers=admin_headers(client, browse_value))

    assert browse.status_code == 200, browse.text
    assert events_for(browse_value) == [], "a browse is a read and writes no row"


# --- AC-7: POST /snapshots --------------------------------------------------


def test_ac7_post_snapshots_creates_one_snapshot_and_reports_it(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-7: 201, a well-formed name, an aware timestamp and a fresh store's prune."""
    storage = isolated_storage
    seed_library(storage)
    snapshot_fakes.use_tree_copy(monkeypatch, storage)
    value = request_id_for("ac7")

    response = client.post("/snapshots", headers=admin_headers(client, value))

    assert response.status_code == 201, response.text
    body = response.json()
    created = body["snapshot"]
    assert snapshots.NAME_RE.fullmatch(created["name"])
    assert created["reason"] == "manual"
    assert created["age_seconds"] >= 0
    created_at = datetime.fromisoformat(created["created_at"])
    assert created_at.tzinfo is not None
    assert created_at.utcoffset() is not None
    assert body["prune"]["pruned"] == 0
    assert body["prune"]["names"] == []
    assert body["prune"]["kept"] == 1

    rows = events_for(value)
    assert [row.action for row in rows] == [audit.SNAPSHOT_CREATE]
    assert rows[0].target == created["name"]
    assert json.loads(rows[0].detail_json)["pruned"] == 0


def test_ac7_a_pruned_name_gets_its_own_prune_row(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-7: one `snapshot.prune` row per pruned name, proved by a tight policy."""
    storage = isolated_storage
    seed_library(storage)
    tight = snapshots.RetentionPolicy(keep_last_n=1, keep_daily=0, max_age_days=1, hard_cap=1)
    # The fake pins `RetentionPolicy()` when it builds the provider, and a
    # provider reads its policy once: the tight policy has to go on the instance.
    provider = snapshot_fakes.use_tree_copy(monkeypatch, storage)
    provider.policy = tight
    old = snapshots.snapshot_name(
        snapshots.SnapshotReason.MANUAL,
        datetime.now(timezone.utc) - timedelta(days=10),
        suffix="0000aa",
    )
    (provider.snapshot_dir / old).mkdir()
    value = request_id_for("ac7-prune")

    response = client.post("/snapshots", headers=admin_headers(client, value))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["prune"]["pruned"] == 1
    assert body["prune"]["names"] == [old]
    assert not (provider.snapshot_dir / old).exists()

    rows = events_for(value)
    create_rows = [row for row in rows if row.action == audit.SNAPSHOT_CREATE]
    prune_rows = [row for row in rows if row.action == audit.SNAPSHOT_PRUNE]
    assert len(create_rows) == 1
    assert create_rows[0].target == body["snapshot"]["name"]
    assert json.loads(create_rows[0].detail_json)["pruned"] == 1
    assert [row.target for row in prune_rows] == [old]
    assert json.loads(prune_rows[0].detail_json)["trigger"] == body["snapshot"]["name"]


def test_ac7_an_unavailable_host_is_a_409_and_writes_nothing(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-7: the null provider refuses a manual snapshot rather than pretending."""
    snapshot_fakes.use_unavailable(monkeypatch)
    value = request_id_for("ac7-unavailable")

    response = client.post("/snapshots", headers=admin_headers(client, value))

    assert response.status_code == 409, response.text
    assert "no snapshot method" in response.json()["detail"]
    assert events_for(value) == []


# --- AC-8: DELETE /snapshots/{name} ----------------------------------------


def test_ac8_delete_removes_one_snapshot_and_writes_one_row(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-8: 200, gone from the listing, one `snapshot.delete` row."""
    storage = isolated_storage
    seed_library(storage)
    name, view = make_snapshot(monkeypatch, storage)
    value = request_id_for("ac8")
    headers = admin_headers(client, value)

    response = client.delete(f"/snapshots/{name}", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "name": name}
    assert not view.exists()
    listed = client.get("/snapshots", headers=admin_headers(client)).json()
    assert name not in [item["name"] for item in listed["snapshots"]]
    rows = events_for(value)
    assert [row.action for row in rows] == [audit.SNAPSHOT_DELETE]
    assert rows[0].target == name
    assert json.loads(rows[0].detail_json) == {"method": snapshots.LOCAL_COPY_METHOD}


def test_ac8_an_unparseable_name_is_a_400_and_writes_nothing(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-8: a real provider refuses a name this module did not write."""
    snapshot_fakes.use_tree_copy(monkeypatch, isolated_storage)
    value = request_id_for("ac8-nonsense")

    response = client.delete("/snapshots/nonsense", headers=admin_headers(client, value))

    assert response.status_code == 400, response.text
    assert "is not a snapshot name" in response.json()["detail"]
    assert events_for(value) == []


def test_ac8_an_absent_well_formed_name_is_a_404_and_writes_nothing(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-8: a name that parses but is not in the store is a 404, not a 400."""
    snapshot_fakes.use_tree_copy(monkeypatch, isolated_storage)
    value = request_id_for("ac8-absent")

    response = client.delete(f"/snapshots/{ABSENT_SNAPSHOT}", headers=admin_headers(client, value))

    assert response.status_code == 404, response.text
    assert events_for(value) == []


def test_ac8_delete_is_admin_only() -> None:
    """AC-8: the route is declared admin.

    The 403s an editor and a viewer get are proved by `test_permissions_matrix.py`,
    whose admin/editor sweeps cover this exact key with a real DELETE; the account
    bootstrap those sweeps need is not duplicated here.
    """
    assert permissions.ROUTE_PERMISSIONS[("DELETE", "/snapshots/{name}")] == permissions.ADMIN


# --- AC-9: retention round trip --------------------------------------------


DEFAULTS = {
    "keep_last_n": snapshots.DEFAULT_KEEP_LAST_N,
    "keep_daily": snapshots.DEFAULT_KEEP_DAILY,
    "max_age_days": snapshots.DEFAULT_MAX_AGE_DAYS,
    "hard_cap": snapshots.DEFAULT_HARD_CAP,
}
CUSTOM = {"keep_last_n": 5, "keep_daily": 2, "max_age_days": 10, "hard_cap": 12}


def test_ac9_retention_round_trips_through_the_route(
    isolated_storage: Path, client: TestClient
) -> None:
    """AC-9: defaults, a POST that persists, one audit row, and validation."""
    snapshots.set_retention_policy(snapshots.RetentionPolicy())
    headers = admin_headers(client)

    current = client.get("/snapshots/retention", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json() == DEFAULTS

    value = request_id_for("ac9")
    posted = client.post("/snapshots/retention", json=CUSTOM, headers=admin_headers(client, value))
    assert posted.status_code == 200, posted.text
    assert posted.json() == CUSTOM
    assert client.get("/snapshots/retention", headers=headers).json() == CUSTOM

    rows = events_for(value)
    assert [row.action for row in rows] == [audit.SETTINGS_SNAPSHOT_RETENTION_UPDATE]
    row = rows[0]
    assert row.target == "snapshot_retention"
    assert json.loads(row.detail_json) == {"from": DEFAULTS, "to": CUSTOM}

    refused_value = request_id_for("ac9-refused")
    refused = client.post(
        "/snapshots/retention", json={**CUSTOM, "keep_last_n": 0}, headers=admin_headers(client, refused_value)
    )
    assert refused.status_code == 422, refused.text
    assert client.get("/snapshots/retention", headers=headers).json() == CUSTOM
    assert events_for(refused_value) == []

    # Only keep_last_n is positive; keep_daily may legitimately be 0.
    accepted = client.post("/snapshots/retention", json={**CUSTOM, "keep_daily": 0}, headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["keep_daily"] == 0


# --- AC-10: the literal route is matched before the name template ----------


def test_ac10_the_retention_literal_is_matched_before_the_name_template(
    isolated_storage: Path, client: TestClient
) -> None:
    """AC-10: `retention` is a literal, not a snapshot name.

    This fails with a 400 the moment a one-segment `/snapshots/{name}` route is
    hoisted above the literal: "retention" would be read as a name, and a name
    this module did not write is `SnapshotPathError` (400).
    """
    response = client.get("/snapshots/retention", headers=admin_headers(client))

    assert response.status_code == 200, response.text
    assert "keep_last_n" in response.json()


# --- a running scan is not a failure, and no method is not an error --------


def test_a_running_scan_does_not_turn_a_restore_into_a_failure(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bytes are copied before the scan is asked for; a refusal is reported, not raised."""
    storage = isolated_storage
    seed_library(storage)
    name, view = make_snapshot(monkeypatch, storage)
    monkeypatch.setattr(main, "start_scan", lambda: False)

    response = client.post(f"/snapshots/{name}/restore", json={"path": "cube.stl"}, headers=admin_headers(client))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["scan_started"] is False
    assert (storage / body["destination"]).read_bytes() == (view / "cube.stl").read_bytes()


def test_listing_on_a_host_with_no_snapshot_method_is_empty_not_an_error(
    isolated_storage: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A volume without a method lists nothing; it does not 409 a plain read."""
    snapshot_fakes.use_unavailable(monkeypatch)

    response = client.get("/snapshots", headers=admin_headers(client))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "snapshots": [],
        "method": storage_capabilities.NO_METHOD,
        "supports_browse": False,
        "supports_restore": False,
    }
