import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

import migrations
from migrations import MIGRATIONS, applied_migrations, run_migrations

# Names of migrations that have shipped. Later versions may be appended (005,
# ...) without touching this map; the assertion below only pins the entries
# listed here, so it keeps meaning "shipped entries never change".
SHIPPED_LEDGER = {
    1: "initial_schema",
    2: "nested_folders_and_mount_sources",
    3: "asset_metadata_and_bundles",
    4: "folder_identity_and_reference_flags",
}

ASSET_REFERENCE_COLUMNS = {"missing_since", "disk_mtime", "is_reference"}


@pytest.fixture(autouse=True)
def temp_storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every migration-004 run at a throwaway storage root."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setattr(migrations, "_storage_root", lambda: storage_root)
    return storage_root


def sqlite_engine(path: Path) -> Engine:
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def make_v3_engine(path: Path) -> Engine:
    engine = sqlite_engine(path)
    assert run_migrations(engine, MIGRATIONS[:3]) == 3
    return engine


def insert_folder(conn: Connection, folder_id: str, name: str, parent_id: str | None = None) -> None:
    conn.exec_driver_sql(
        "INSERT INTO folder(id, name, tags_json, parent_id) VALUES (?, ?, '[]', ?)",
        (folder_id, name, parent_id),
    )


def insert_asset(
    conn: Connection,
    asset_id: str,
    storage_path: str | None = None,
    source_path: str | None = None,
) -> None:
    conn.exec_driver_sql(
        "INSERT INTO asset(id, filename, mime, size, tags_json, title, notes, folder_id, source_path, name, storage_path) "
        "VALUES (?, 'model.stl', 'model/stl', 10, '[]', NULL, NULL, NULL, ?, ?, ?)",
        (asset_id, source_path, asset_id, storage_path),
    )


def folder_paths(database_engine: Engine) -> dict[str, str]:
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT id, storage_path FROM folder ORDER BY id").fetchall()
    return {str(folder_id): str(storage_path) for folder_id, storage_path in rows}


def table_snapshot(database_engine: Engine, *tables: str) -> tuple[tuple[str, tuple], ...]:
    with database_engine.connect() as conn:
        return tuple(
            (table, tuple(conn.exec_driver_sql(f"SELECT * FROM {table} ORDER BY id").fetchall())) for table in tables
        )


def shipped_ledger_entries(database_engine: Engine) -> dict[int, str]:
    applied = applied_migrations(database_engine)
    return {version: applied[version] for version in SHIPPED_LEDGER if version in applied}


def filesystem_snapshot(root: Path) -> tuple[tuple[str, bool, int, int], ...]:
    entries = []
    for path in [root, *sorted(root.rglob("*"))]:
        stat = path.stat()
        entries.append((str(path.relative_to(root)) or ".", path.is_dir(), stat.st_size, stat.st_mtime_ns))
    return tuple(sorted(entries))


def write_placeholder_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder")


def test_fresh_database_reaches_v4(tmp_path: Path) -> None:
    database_engine = sqlite_engine(tmp_path / "fresh.db")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert shipped_ledger_entries(database_engine) == SHIPPED_LEDGER
    with database_engine.connect() as conn:
        folder_columns = {str(row[1]) for row in conn.exec_driver_sql("PRAGMA table_info(folder)").fetchall()}
        asset_columns = {str(row[1]) for row in conn.exec_driver_sql("PRAGMA table_info(asset)").fetchall()}
        index_names = {
            str(row[0])
            for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
        }
    assert "storage_path" in folder_columns
    assert ASSET_REFERENCE_COLUMNS.issubset(asset_columns)
    assert "idx_folder_storage_path_unique" in index_names


def test_v3_fixture_upgrades_to_v4(tmp_path: Path, temp_storage_root: Path) -> None:
    database_engine = make_v3_engine(tmp_path / "upgrade.db")
    mount_root = tmp_path / "mount"
    with database_engine.begin() as conn:
        insert_folder(conn, "f-parts", "Parts")
        insert_folder(conn, "f-workshop", "Workshop")
        insert_folder(conn, "f-prints", "Prints", "f-parts")
        insert_folder(conn, "f-dupe-a", "Dupe", "f-parts")
        insert_folder(conn, "f-dupe-b", "Dupe", "f-parts")
        insert_folder(conn, "f-slash", "A/B", "f-parts")
        insert_folder(conn, "f-pipe", "A|B", "f-parts")
        insert_asset(conn, "a-managed", storage_path="a-managed/model.stl")
        insert_asset(conn, "a-nocopy", storage_path="a-nocopy/model.stl", source_path=str(mount_root / "nocopy.stl"))
        insert_asset(conn, "a-copy", storage_path="a-copy/model.stl", source_path=str(mount_root / "copy.stl"))
    write_placeholder_file(temp_storage_root / "a-managed" / "model.stl")
    write_placeholder_file(temp_storage_root / "a-copy" / "model.stl")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert folder_paths(database_engine) == {
        "f-dupe-a": "Parts/Dupe",
        "f-dupe-b": "Parts/Dupe (2)",
        "f-parts": "Parts",
        "f-pipe": "Parts/A_B (2)",
        "f-prints": "Parts/Prints",
        "f-slash": "Parts/A_B",
        "f-workshop": "Workshop",
    }
    with database_engine.connect() as conn:
        references = conn.exec_driver_sql("SELECT id, is_reference FROM asset ORDER BY id").fetchall()
        unscanned = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM asset WHERE missing_since IS NOT NULL OR disk_mtime IS NOT NULL"
        ).scalar_one()
    assert [(str(asset_id), int(flag)) for asset_id, flag in references] == [
        ("a-copy", 0),
        ("a-managed", 0),
        ("a-nocopy", 1),
    ]
    assert unscanned == 0


def test_migration_004_is_idempotent(tmp_path: Path, temp_storage_root: Path) -> None:
    database_engine = make_v3_engine(tmp_path / "idempotent.db")
    with database_engine.begin() as conn:
        insert_folder(conn, "f-parts", "Parts")
        insert_folder(conn, "f-prints", "Prints", "f-parts")
        insert_asset(conn, "a-nocopy", storage_path="a-nocopy/model.stl", source_path=str(tmp_path / "mount" / "x.stl"))

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    before = table_snapshot(database_engine, "folder", "asset")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    assert table_snapshot(database_engine, "folder", "asset") == before
    assert shipped_ledger_entries(database_engine) == SHIPPED_LEDGER

    migration = next(migration for migration in MIGRATIONS if migration.version == 4)
    with database_engine.begin() as conn:
        migration.apply(conn)

    assert table_snapshot(database_engine, "folder", "asset") == before


def test_duplicate_sibling_names_get_deterministic_suffixes(tmp_path: Path) -> None:
    siblings = [("f-foo-a", "Foo"), ("f-foo-b", "Foo"), ("f-foo-literal", "Foo (2)")]
    expected = {
        "f-foo-a": "Foo",
        "f-foo-b": "Foo (3)",
        "f-foo-literal": "Foo (2)",
    }

    forward_engine = make_v3_engine(tmp_path / "forward.db")
    with forward_engine.begin() as conn:
        for folder_id, name in siblings:
            insert_folder(conn, folder_id, name)
    assert run_migrations(forward_engine) == MIGRATIONS[-1].version
    assert folder_paths(forward_engine) == expected
    assert run_migrations(forward_engine) == MIGRATIONS[-1].version
    assert folder_paths(forward_engine) == expected

    reverse_engine = make_v3_engine(tmp_path / "reverse.db")
    with reverse_engine.begin() as conn:
        for folder_id, name in reversed(siblings):
            insert_folder(conn, folder_id, name)
    assert run_migrations(reverse_engine) == MIGRATIONS[-1].version
    assert folder_paths(reverse_engine) == expected


def test_folder_storage_path_unique_index_is_case_insensitive(tmp_path: Path) -> None:
    database_engine = make_v3_engine(tmp_path / "unique.db")
    with database_engine.begin() as conn:
        insert_folder(conn, "f-parts", "Parts")
        insert_folder(conn, "f-other", "Other")
        insert_folder(conn, "f-parts-copy", "Parts", "f-other")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version
    paths = folder_paths(database_engine)
    assert paths["f-parts"] == "Parts"
    assert paths["f-parts-copy"] == "Other/Parts"

    with pytest.raises(IntegrityError):
        with database_engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO folder(id, name, tags_json, parent_id, storage_path) "
                "VALUES ('f-case-clash', 'Clash', '[]', NULL, 'parts')"
            )


def test_mount_reference_assets_are_flagged(tmp_path: Path, temp_storage_root: Path) -> None:
    database_engine = make_v3_engine(tmp_path / "references.db")
    mount_root = tmp_path / "mount"
    with database_engine.begin() as conn:
        insert_asset(conn, "a-nocopy", storage_path="a-nocopy/model.stl", source_path=str(mount_root / "nocopy.stl"))
        insert_asset(conn, "a-copy", storage_path="a-copy/model.stl", source_path=str(mount_root / "copy.stl"))
        insert_asset(conn, "a-plain", storage_path="a-plain/model.stl")
        insert_asset(
            conn,
            "a-selfscan",
            storage_path="a-selfscan/model.stl",
            source_path=str(temp_storage_root / "imports" / "scanned.stl"),
        )
    write_placeholder_file(temp_storage_root / "a-copy" / "model.stl")
    write_placeholder_file(temp_storage_root / "imports" / "scanned.stl")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.connect() as conn:
        flags = conn.exec_driver_sql("SELECT id, is_reference FROM asset ORDER BY id").fetchall()
    assert [(str(asset_id), int(flag)) for asset_id, flag in flags] == [
        ("a-copy", 0),
        ("a-nocopy", 1),
        ("a-plain", 0),
        ("a-selfscan", 0),
    ]


def test_migration_does_not_touch_the_filesystem(tmp_path: Path, temp_storage_root: Path) -> None:
    (temp_storage_root / "keep" / "nested").mkdir(parents=True)
    files = [
        temp_storage_root / "keep" / "a.stl",
        temp_storage_root / "keep" / "nested" / "b.stl",
        temp_storage_root / "c.txt",
    ]
    for index, path in enumerate(files):
        path.write_text(f"contents-{index}")
        os.utime(path, ns=(1_600_000_000_000_000_000 + index, 1_600_000_000_000_000_000 + index))
    for index, directory in enumerate([temp_storage_root, temp_storage_root / "keep", temp_storage_root / "keep" / "nested"]):
        os.utime(directory, ns=(1_500_000_000_000_000_000 + index, 1_500_000_000_000_000_000 + index))

    database_engine = make_v3_engine(tmp_path / "filesystem.db")
    with database_engine.begin() as conn:
        insert_folder(conn, "f-parts", "Parts")
        insert_asset(conn, "a-nocopy", storage_path="a-nocopy/model.stl", source_path=str(tmp_path / "mount" / "x.stl"))
    before = filesystem_snapshot(temp_storage_root)

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert filesystem_snapshot(temp_storage_root) == before


def test_orphan_parent_and_parent_cycle_are_treated_as_root_level(tmp_path: Path) -> None:
    database_engine = make_v3_engine(tmp_path / "broken-parents.db")
    with database_engine.begin() as conn:
        insert_folder(conn, "f-orphan", "Orphan", "f-missing")
        insert_folder(conn, "f-cycle-a", "CycleA", "f-cycle-b")
        insert_folder(conn, "f-cycle-b", "CycleB", "f-cycle-a")

    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    assert folder_paths(database_engine) == {
        "f-cycle-a": "CycleA",
        "f-cycle-b": "CycleB",
        "f-orphan": "Orphan",
    }


def test_null_storage_path_remains_allowed_after_migration(tmp_path: Path) -> None:
    database_engine = make_v3_engine(tmp_path / "late-folders.db")
    with database_engine.begin() as conn:
        insert_folder(conn, "f-parts", "Parts")
    assert run_migrations(database_engine) == MIGRATIONS[-1].version

    with database_engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO folder(id, name, tags_json, parent_id) VALUES ('f-late-a', 'Late A', '[]', NULL)")
        conn.exec_driver_sql("INSERT INTO folder(id, name, tags_json, parent_id) VALUES ('f-late-b', 'Late B', '[]', NULL)")
        late = conn.exec_driver_sql(
            "SELECT id, storage_path FROM folder WHERE id IN ('f-late-a', 'f-late-b') ORDER BY id"
        ).fetchall()

    assert [(str(folder_id), storage_path) for folder_id, storage_path in late] == [
        ("f-late-a", None),
        ("f-late-b", None),
    ]
