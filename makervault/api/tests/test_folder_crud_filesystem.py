"""Folder CRUD: filesystem materialisation and transactional path rewrites.

Every test here derives its paths from a temp storage root: `folder_service`
resolves its root through the monkeypatched `storage_root()` and `_absolute`
resolves through that, so nothing ever touches a real mount. The test database
is shared for the whole session, so rows created by a test are deleted again at
teardown.
"""

import errno
import os
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlmodel import Session, select

import asset_service
import folder_paths
import folder_service
import main
import migrations
from db import engine
from main import app
from migrations import MIGRATIONS, run_migrations
from models import Asset, Folder

# --- infrastructure ---------------------------------------------------------

def auth_header(client: TestClient) -> dict:
    """Bearer token, or empty when the app is running with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _snapshot(root: Path, *, directory_mtimes: bool) -> tuple[tuple[str, bool, int, Optional[int]], ...]:
    entries = []
    for path in [root, *sorted(root.rglob("*"))]:
        stat_result = path.stat()
        is_directory = path.is_dir()
        mtime_ns = stat_result.st_mtime_ns if (directory_mtimes or not is_directory) else None
        entries.append((str(path.relative_to(root)) or ".", is_directory, stat_result.st_size, mtime_ns))
    return tuple(sorted(entries))


def filesystem_snapshot(root: Path) -> tuple[tuple[str, bool, int, Optional[int]], ...]:
    """Paths, kinds, sizes and mtimes of the whole tree (the migration-004 helper)."""
    return _snapshot(root, directory_mtimes=True)


def tree_snapshot(root: Path) -> tuple[tuple[str, bool, int, Optional[int]], ...]:
    """Same shape, but directory mtimes are ignored.

    Creating and deleting a directory in the same place - or a rename that is
    undone - rewrites the parent directory's mtime without changing the tree, so
    only file mtimes are meaningful when asking "did anything really move?".
    """
    return _snapshot(root, directory_mtimes=False)


def write_placeholder_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder")


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point folder storage at a temp root and undo every row this test created."""
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(folder_service, "storage_root", lambda: storage)
    # The schema is created by the app lifespan; a single-file run needs it first.
    run_migrations(engine)
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
    yield storage
    with Session(engine) as session:
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        session.commit()


def insert_folder_row(name: str, parent_id: Optional[str] = None, storage_path: Optional[str] = None) -> str:
    """Insert a folder row the way a legacy or scan-created folder looks."""
    folder = Folder(name=name, tags_json="[]", parent_id=parent_id, storage_path=storage_path)
    with Session(engine) as session:
        session.add(folder)
        session.commit()
        session.refresh(folder)
        return folder.id


def insert_asset_row(name: str, folder_id: Optional[str], storage_path: str) -> str:
    """Insert an asset row the way an import or scan would."""
    asset = Asset(
        filename="model.stl",
        mime="model/stl",
        size=10,
        name=name,
        folder_id=folder_id,
        storage_path=storage_path,
    )
    with Session(engine) as session:
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset.id


def read_folder(folder_id: str) -> Folder:
    with Session(engine) as session:
        folder = session.get(Folder, folder_id)
        assert folder is not None
        session.expunge(folder)
    return folder


def read_asset(asset_id: str) -> Asset:
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        session.expunge(asset)
    return asset


def storage_paths_in_db() -> dict[str, Optional[str]]:
    with Session(engine) as session:
        return {folder.id: folder.storage_path for folder in session.exec(select(Folder))}


def post_folder(client: TestClient, headers: dict, name: str, parent_id: Optional[str] = None, tags: Optional[list] = None):
    return client.post("/folders", json={"name": name, "tags": tags or [], "parent_id": parent_id}, headers=headers)


def patch_folder(
    client: TestClient,
    headers: dict,
    folder_id: str,
    name: str,
    parent_id: Optional[str] = None,
    tags: Optional[list] = None,
):
    return client.patch(
        f"/folder/{folder_id}",
        json={"name": name, "tags": tags or [], "parent_id": parent_id},
        headers=headers,
    )


def created_folder(client: TestClient, headers: dict, name: str, parent_id: Optional[str] = None) -> dict:
    response = post_folder(client, headers, name, parent_id)
    assert response.status_code == 200, response.text
    return response.json()


def sqlite_engine(path: Path) -> Engine:
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def insert_v3_folder(conn: Connection, folder_id: str, name: str, parent_id: Optional[str] = None) -> None:
    conn.exec_driver_sql(
        "INSERT INTO folder(id, name, tags_json, parent_id) VALUES (?, ?, '[]', ?)",
        (folder_id, name, parent_id),
    )


# --- create -----------------------------------------------------------------

def test_create_folder_creates_exactly_one_directory(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        before = filesystem_snapshot(storage)
        response = post_folder(client, headers, "Foo")
        assert response.status_code == 200, response.text
        relative = response.json()["storage_path"]
        assert relative == "Foo"
        assert (storage / relative).is_dir()
        after = filesystem_snapshot(storage)

    added = {entry[0] for entry in after} - {entry[0] for entry in before}
    assert added == {relative}
    kinds = {entry[0]: entry[1] for entry in after}
    assert kinds[relative] is True


def test_create_nested_folder_lands_under_parent_directory(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        parent = created_folder(client, headers, "Parts")
        child = created_folder(client, headers, "Boxes", parent_id=parent["id"])

    assert parent["storage_path"] == "Parts"
    assert child["storage_path"] == "Parts/Boxes"
    assert child["parent_id"] == parent["id"]
    assert (storage / "Parts" / "Boxes").is_dir()
    assert storage_paths_in_db()[child["id"]] == "Parts/Boxes"


def test_create_duplicate_names_are_deduped(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        first = created_folder(client, headers, "Foo")
        second = created_folder(client, headers, "Foo")
        upper = created_folder(client, headers, "Parts")
        lower = created_folder(client, headers, "parts")

    assert [first["storage_path"], second["storage_path"]] == ["Foo", "Foo (2)"]
    # The NOCASE unique index must never be reached: the scope is casefolded.
    assert [upper["storage_path"], lower["storage_path"]] == ["Parts", "parts (2)"]
    for folder in (first, second, upper, lower):
        assert (storage / folder["storage_path"]).is_dir()


def test_create_dedupe_reserves_literal_suffixed_sibling_name(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        first = created_folder(client, headers, "Foo")
        second = created_folder(client, headers, "Foo")
        # A sibling that is literally named `Foo (2)` but was never converged to a
        # path, exactly like a folder created before Mf-oh78.
        literal_id = insert_folder_row("Foo (2)", storage_path=None)
        newcomer = created_folder(client, headers, "Foo")

    assert [first["storage_path"], second["storage_path"]] == ["Foo", "Foo (2)"]
    assert newcomer["storage_path"] == "Foo (3)"
    assert read_folder(literal_id).storage_path is None
    assert (storage / "Foo (3)").is_dir()


def test_failed_create_removes_the_created_directory(isolated_storage: Path) -> None:
    storage = isolated_storage
    # The unique index on folder.storage_path is global, so a path claimed in a
    # different scope still makes the insert fail after the directory was made.
    other_parent = insert_folder_row("Other", storage_path="Other")
    insert_folder_row("Zzz", parent_id=other_parent, storage_path="Foo")
    before = tree_snapshot(storage)

    with TestClient(app) as client:
        headers = auth_header(client)
        response = post_folder(client, headers, "Foo")
        assert response.status_code == 409
        assert response.json()["detail"] == "Storage path already exists: Foo"

    assert not (storage / "Foo").exists()
    assert tree_snapshot(storage) == before
    with Session(engine) as session:
        assert session.exec(select(Folder).where(Folder.name == "Foo")).first() is None


def test_create_under_path_less_parent_converges_the_parent_chain(isolated_storage: Path) -> None:
    storage = isolated_storage
    parent_id = insert_folder_row("Pathless", storage_path=None)

    with TestClient(app) as client:
        headers = auth_header(client)
        child = created_folder(client, headers, "Child", parent_id=parent_id)

    assert child["storage_path"] == "Pathless/Child"
    assert (storage / "Pathless" / "Child").is_dir()
    assert read_folder(parent_id).storage_path == "Pathless"


# --- rename / reparent ------------------------------------------------------

def test_rename_renames_directory_and_rewrites_descendant_asset_paths(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        outer = created_folder(client, headers, "Foo")
        inner = created_folder(client, headers, "Boxes", parent_id=outer["id"])
        assert inner["storage_path"] == "Foo/Boxes"
        write_placeholder_file(storage / "Foo" / "model.stl")
        write_placeholder_file(storage / "Foo" / "Boxes" / "model.stl")
        outer_asset = insert_asset_row("Outer model", outer["id"], "Foo/model.stl")
        inner_asset = insert_asset_row("Inner model", inner["id"], "Foo/Boxes/model.stl")

        response = patch_folder(client, headers, outer["id"], "Bar")
        assert response.status_code == 200, response.text
        assert response.json()["storage_path"] == "Bar"

    assert not (storage / "Foo").exists()
    assert (storage / "Bar" / "model.stl").is_file()
    assert (storage / "Bar" / "Boxes" / "model.stl").is_file()
    assert read_asset(outer_asset).storage_path == "Bar/model.stl"
    assert read_asset(inner_asset).storage_path == "Bar/Boxes/model.stl"
    paths = storage_paths_in_db()
    assert paths[outer["id"]] == "Bar"
    assert paths[inner["id"]] == "Bar/Boxes"


@pytest.mark.parametrize("failing_helper", ["apply_asset_path_rewrites", "apply_folder_paths"])
def test_rename_rolls_back_disk_and_db_when_it_fails_midway(
    isolated_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_helper: str,
) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        outer = created_folder(client, headers, "Foo")
        inner = created_folder(client, headers, "Boxes", parent_id=outer["id"])
        write_placeholder_file(storage / "Foo" / "Boxes" / "model.stl")
        asset_id = insert_asset_row("Model", inner["id"], "Foo/Boxes/model.stl")
        paths_before = storage_paths_in_db()
        snapshot_before = tree_snapshot(storage)

        def boom_asset_rewrites(session, rewrites):
            asset, new_path = rewrites[0]
            asset.storage_path = new_path
            session.add(asset)
            session.flush()
            raise RuntimeError("boom")

        def boom_folder_paths(session, folders, paths):
            folder_id = next(iter(paths))
            folders[folder_id].storage_path = paths[folder_id]
            session.add(folders[folder_id])
            session.flush()
            raise RuntimeError("boom")

        failing = boom_asset_rewrites if failing_helper == "apply_asset_path_rewrites" else boom_folder_paths
        monkeypatch.setattr(folder_service, failing_helper, failing)
        with pytest.raises(RuntimeError, match="boom"):
            patch_folder(client, headers, outer["id"], "Bar")

    assert storage_paths_in_db() == paths_before
    assert read_asset(asset_id).storage_path == "Foo/Boxes/model.stl"
    assert tree_snapshot(storage) == snapshot_before
    assert (storage / "Foo" / "Boxes" / "model.stl").is_file()
    assert not (storage / "Bar").exists()


def test_rename_onto_existing_directory_conflicts_without_changes(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        folder = created_folder(client, headers, "Foo")
        # A directory the database knows nothing about, e.g. an interrupted move.
        (storage / "Bar").mkdir()
        paths_before = storage_paths_in_db()
        snapshot_before = filesystem_snapshot(storage)

        response = patch_folder(client, headers, folder["id"], "Bar")
        assert response.status_code == 409
        assert response.json()["detail"] == "Storage path already exists: Bar"

    assert storage_paths_in_db() == paths_before
    assert read_folder(folder["id"]).name == "Foo"
    assert filesystem_snapshot(storage) == snapshot_before


@pytest.mark.parametrize("racer", ["file", "nonempty_directory", "windows_eexist"])
def test_rename_destination_race_is_409_not_500(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch, racer: str
) -> None:
    """A destination that appears after the exists() pre-check is still a 409."""
    storage = isolated_storage
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        folder = created_folder(client, headers, "Foo")
        write_placeholder_file(storage / "Foo" / "model.stl")
        paths_before = storage_paths_in_db()
        target = storage / "Bar"
        real_rename = os.rename

        def rename_with_racer(src, dst, *args, **kwargs):
            # The racer is created inside the rename itself, i.e. after the real
            # exists() pre-check: that gap is exactly the window under test.
            if Path(dst).resolve() == target.resolve():
                if racer == "file":
                    Path(dst).write_bytes(b"racer bytes")
                elif racer == "nonempty_directory":
                    Path(dst).mkdir()
                    (Path(dst) / "racer.stl").write_bytes(b"racer bytes")
                else:
                    raise OSError(errno.EEXIST, "destination exists")
            return real_rename(src, dst, *args, **kwargs)

        monkeypatch.setattr(folder_service.os, "rename", rename_with_racer)
        response = patch_folder(client, headers, folder["id"], "Bar")

    assert response.status_code == 409
    assert response.status_code != 500
    assert response.json()["detail"] == "Storage path already exists: Bar"
    assert read_folder(folder["id"]).name == "Foo"
    assert storage_paths_in_db() == paths_before
    assert (storage / "Foo" / "model.stl").is_file()
    # Whatever the racer wrote is not ours to destroy.
    if racer == "file":
        assert (storage / "Bar").read_bytes() == b"racer bytes"
    elif racer == "nonempty_directory":
        assert (storage / "Bar" / "racer.stl").read_bytes() == b"racer bytes"


def test_reparent_rederives_descendant_paths(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        base = created_folder(client, headers, "Base")
        wide = created_folder(client, headers, "Wide")
        inner = created_folder(client, headers, "Inner", parent_id=wide["id"])
        # Two casefold-colliding descendants that were never converged to a path.
        lower_dupe = insert_folder_row("dupe", parent_id=wide["id"], storage_path=None)
        upper_dupe = insert_folder_row("Dupe", parent_id=wide["id"], storage_path=None)
        write_placeholder_file(storage / "Wide" / "Inner" / "model.stl")
        asset_id = insert_asset_row("Model", inner["id"], "Wide/Inner/model.stl")

        response = patch_folder(client, headers, wide["id"], "Wide", parent_id=base["id"])
        assert response.status_code == 200, response.text
        assert response.json()["storage_path"] == "Base/Wide"

    paths = storage_paths_in_db()
    assert paths[wide["id"]] == "Base/Wide"
    assert paths[inner["id"]] == "Base/Wide/Inner"
    # The runtime overlay allocates the two NULL-path siblings against each other,
    # so they never derive the same segment and never hit the unique index.
    dupe_paths = [paths[lower_dupe], paths[upper_dupe]]
    assert all(path.startswith("Base/Wide/") for path in dupe_paths)
    assert {path.rsplit("/", 1)[-1].casefold() for path in dupe_paths} == {"dupe", "dupe (2)"}
    assert read_asset(asset_id).storage_path == "Base/Wide/Inner/model.stl"
    assert (storage / "Base" / "Wide" / "Inner" / "model.stl").is_file()


def test_reparent_prunes_the_vacated_parent_directory(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        outer = created_folder(client, headers, "Outer")
        middle = created_folder(client, headers, "Middle", parent_id=outer["id"])
        inner = created_folder(client, headers, "Inner", parent_id=middle["id"])
        destination = created_folder(client, headers, "Destination")

        response = patch_folder(client, headers, inner["id"], "Inner", parent_id=destination["id"])
        assert response.status_code == 200, response.text
        assert response.json()["storage_path"] == "Destination/Inner"

    assert (storage / "Destination" / "Inner").is_dir()
    # The vacated chain is empty now; the library scan would otherwise re-import
    # it as a folder of its own.
    assert not (storage / "Outer").exists()


def test_converge_ancestor_paths_tolerates_a_folder_deleted_meanwhile() -> None:
    with Session(engine) as session:
        assert folder_paths.converge_ancestor_paths(session, "no-such-folder") == ""
        assert folder_paths.converge_ancestor_paths(session, None) == ""


def test_metadata_only_patch_moves_no_files(isolated_storage: Path) -> None:
    storage = isolated_storage

    # The metadata-edit path must have no reorganize hook left to call at all.
    assert not hasattr(main, "reorganize_managed_assets")
    assert not hasattr(asset_service, "relocate_asset")

    with TestClient(app) as client:
        headers = auth_header(client)
        folder = created_folder(client, headers, "Foo")
        write_placeholder_file(storage / "Foo" / "model.stl")
        insert_asset_row("Model", folder["id"], "Foo/model.stl")
        paths_before = storage_paths_in_db()
        snapshot_before = filesystem_snapshot(storage)

        response = patch_folder(client, headers, folder["id"], "Foo", tags=["tags-only"])
        assert response.status_code == 200, response.text
        assert response.json()["tags"] == ["tags-only"]
        assert response.json()["storage_path"] == "Foo"
        assert filesystem_snapshot(storage) == snapshot_before

    assert storage_paths_in_db() == paths_before


@pytest.mark.parametrize("folder_name,initial_path", [("Legacy", "Missing"), ("Pathless", None)])
def test_patch_legacy_folder_without_directory_converges_without_filesystem_work(
    isolated_storage: Path,
    folder_name: str,
    initial_path: Optional[str],
) -> None:
    storage = isolated_storage
    before = filesystem_snapshot(storage)
    # Either a 004-era path whose directory was never materialised, or no path at all.
    folder_id = insert_folder_row(folder_name, storage_path=initial_path)
    assert filesystem_snapshot(storage) == before

    with TestClient(app) as client:
        headers = auth_header(client)
        response = patch_folder(client, headers, folder_id, "Renamed")
        assert response.status_code == 200, response.text
        assert response.json()["storage_path"] == "Renamed"

    # Convergence is metadata-only: no directory was created, moved or deleted.
    assert read_folder(folder_id).storage_path == "Renamed"
    assert filesystem_snapshot(storage) == before


def test_patch_scan_created_folder_leaves_files_and_asset_rows_untouched(isolated_storage: Path) -> None:
    storage = isolated_storage
    write_placeholder_file(storage / "Scanner" / "model.stl")
    folder_id = insert_folder_row("Scanned", storage_path=None)
    write_placeholder_file(storage / "Collection" / "model.stl")
    asset_id = insert_asset_row("Collection model", folder_id, "Collection/model.stl")
    before = filesystem_snapshot(storage)

    with TestClient(app) as client:
        headers = auth_header(client)
        response = patch_folder(client, headers, folder_id, "Moved")
        assert response.status_code == 200, response.text

    assert (storage / "Scanner" / "model.stl").is_file()
    assert read_asset(asset_id).storage_path == "Collection/model.stl"
    assert filesystem_snapshot(storage) == before


def test_rename_leaves_assets_outside_the_folder_prefix_untouched(isolated_storage: Path) -> None:
    storage = isolated_storage
    with TestClient(app) as client:
        headers = auth_header(client)
        folder = created_folder(client, headers, "Foo")
        write_placeholder_file(storage / "Collection" / "model.stl")
        # A storage template without {folder}: the file does not live under Foo.
        asset_id = insert_asset_row("Collection model", folder["id"], "Collection/model.stl")

        response = patch_folder(client, headers, folder["id"], "Bar")
        assert response.status_code == 200, response.text

    assert (storage / "Bar").is_dir()
    assert not (storage / "Foo").exists()
    assert (storage / "Collection" / "model.stl").is_file()
    assert read_asset(asset_id).storage_path == "Collection/model.stl"


# --- boundaries -------------------------------------------------------------

def test_long_name_segment_truncates_to_120_and_suffix_goes_after_truncation(isolated_storage: Path) -> None:
    storage = isolated_storage
    long_name = "x" * 200
    with TestClient(app) as client:
        headers = auth_header(client)
        first = created_folder(client, headers, long_name)
        second = created_folder(client, headers, long_name)

    assert first["storage_path"] == "x" * 120
    assert second["storage_path"] == "x" * 120 + " (2)"
    assert len(second["storage_path"]) == 124
    assert (storage / second["storage_path"]).is_dir()


# --- parity with migration 004 ---------------------------------------------

PARITY_CORPUS = [
    "  Foo  ",
    'a<b>c:d"e|f?g*h',
    "a/b\\c",
    "...",
    "",
    "Foo (2)",
    "x" * 200,
    "Ünïcode",
]


def test_path_rules_match_migration_004(tmp_path: Path) -> None:
    for name in PARITY_CORPUS:
        assert folder_paths.folder_path_segment(name) == migrations._folder_path_segment(name)

    # Half (b): drive the runtime allocator the way 004 drives its backfill and
    # compare it with what `_backfill_folder_storage_paths` really writes.
    database_engine = sqlite_engine(tmp_path / "parity.db")
    assert run_migrations(database_engine, MIGRATIONS[:3]) == 3
    names = {"f-a": "Foo", "f-b": "Foo", "f-c": "Foo (2)", "f-d": "Foo"}
    assigned = {"f-d": "Foo (4)"}
    with database_engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE folder ADD COLUMN storage_path TEXT")
        for folder_id, name in names.items():
            insert_v3_folder(conn, folder_id, name)
        conn.exec_driver_sql("UPDATE folder SET storage_path = 'Foo (4)' WHERE id = 'f-d'")
        migrations._backfill_folder_storage_paths(conn)
        rows = conn.exec_driver_sql("SELECT id, storage_path FROM folder ORDER BY id").fetchall()
    expected = {str(folder_id): str(storage_path) for folder_id, storage_path in rows}

    reserved = {folder_paths.folder_path_segment(name).casefold() for name in names.values()}
    # `used` only knows about siblings that already have an assigned segment.
    used = {path.rsplit("/", 1)[-1].casefold() for path in assigned.values()}
    derived = dict(assigned)
    pending = sorted(
        (folder_id for folder_id in names if folder_id not in assigned),
        key=lambda folder_id: (0, "", names[folder_id].casefold(), folder_id),
    )
    for folder_id in pending:
        candidate = folder_paths.allocate_segment(names[folder_id], used, reserved)
        used.add(candidate.casefold())
        derived[folder_id] = candidate

    assert derived == expected
    assert [expected["f-a"], expected["f-b"], expected["f-c"], expected["f-d"]] == [
        "Foo",
        "Foo (3)",
        "Foo (2)",
        "Foo (4)",
    ]
