import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine

import gate5_fixture
from migrations import run_migrations
from recovery import audit_live_paths


def test_representative_pre_v5_1_library_upgrades_without_data_loss(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    gate5_fixture.build_fixture(fixture, "makersvault-api:test")
    database = fixture / "database/app.db"
    storage = fixture / "storage"
    expected = json.loads((fixture / "expected.json").read_text(encoding="utf-8"))

    before = audit_live_paths(database, storage, Path("/imports"), fixture / "imports")
    assert before["database"]["schema_version"] == 4
    assert before["database"]["row_counts"] == {
        "folder": 3,
        "asset": 5,
        "assetfile": 2,
        "appconfig": 3,
        "mountscan": 0,
    }
    assert before["consistency"]["status"] == "ok"
    assert before["consistency"]["managed_primary_present"] == 3
    assert before["consistency"]["related_file_present"] == 2
    assert before["consistency"]["derived_thumbnail_files"] == 1
    assert before["consistency"]["external_state_counts"]["available"] == 1
    assert before["consistency"]["external_state_counts"]["unavailable"] == 1

    engine = create_engine(
        f"sqlite:///{database}", connect_args={"check_same_thread": False}
    )
    assert run_migrations(engine) == expected["post_upgrade_schema"]
    assert run_migrations(engine) == expected["post_upgrade_schema"]

    after = audit_live_paths(database, storage, Path("/imports"), fixture / "imports")
    assert after["consistency"] == before["consistency"]
    assert after["database"]["schema_version"] == 5
    assert after["database"]["row_counts"]["mountscan"] == 0

    connection = sqlite3.connect(database)
    try:
        assets = connection.execute(
            "SELECT id, name, filename, folder_id, preview_status, preview_reason "
            "FROM asset ORDER BY id"
        ).fetchall()
        folders = connection.execute(
            "SELECT id, parent_id FROM folder ORDER BY id"
        ).fetchall()
        prepared = connection.execute(
            "SELECT prepared_file_id, prepared_metadata_json, supporting_file_count "
            "FROM asset WHERE id = 'asset-prepared'"
        ).fetchone()
    finally:
        connection.close()

    assert [row[0] for row in assets] == expected["asset_ids"]
    assert ("asset-managed", "Renamed Bracket", "old-bracket-name.stl", "folder-fasteners", "ready", None) in assets
    assert ("asset-interrupted", "Interrupted Preview", "interrupted.stl", "folder-jigs", "pending", "worker_interrupted") in assets
    assert ("folder-fasteners", "folder-workshop") in folders
    assert ("folder-jigs", "folder-workshop") in folders
    assert prepared == ("file-prepared", json.dumps(expected["prepared_summary"], separators=(",", ":"), sort_keys=True), 1)
