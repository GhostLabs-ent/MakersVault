#!/usr/bin/env python3
"""Build a deterministic, disposable pre-v5.1 recovery-drill library."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path


MIGRATIONS = (
    (1, "initial_schema"),
    (2, "nested_folders_and_mount_sources"),
    (3, "asset_metadata_and_bundles"),
    (4, "persistent_preview_state"),
)

FILES = {
    "Workshop/Fasteners/Renamed Bracket/old-bracket-name.stl": (
        b"solid bracket\nendsolid bracket\n"
    ),
    "Workshop/Jigs/P1S Plate/plate-layout.3mf": b"gate5-3mf-plate-layout",
    "Workshop/Jigs/Interrupted Preview/interrupted.stl": (
        b"solid interrupted\nendsolid interrupted\n"
    ),
    "bundles/asset-prepared/file-doc/assembly.pdf": b"%PDF-1.4 gate5 assembly\n",
    "bundles/asset-prepared/file-prepared/plate.gcode": (
        b"; printer_model = Bambu Lab P1S\n"
        b"; filament_type = PLA\n"
        b"; nozzle_diameter = 0.4\n"
        b"; estimated_time = 3h 12m\nG28\n"
    ),
    "thumbs/asset-managed.jpg": b"legacy-derived-thumbnail",
}


def prepared_metadata() -> str:
    return json.dumps(
        {
            "printer": "Bambu Lab P1S",
            "material": "PLA",
            "nozzle_mm": 0.4,
            "estimated_seconds": 11520,
            "format": "gcode",
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def create_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE folder (
                id TEXT NOT NULL PRIMARY KEY,
                name TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                parent_id TEXT
            );
            CREATE TABLE asset (
                id TEXT NOT NULL PRIMARY KEY,
                filename TEXT NOT NULL,
                mime TEXT NOT NULL,
                size INTEGER NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                title TEXT,
                notes TEXT,
                folder_id TEXT,
                source_path TEXT,
                name TEXT,
                creator TEXT,
                collection TEXT,
                storage_path TEXT,
                supporting_file_count INTEGER NOT NULL DEFAULT 0,
                prepared_file_id TEXT,
                prepared_metadata_json TEXT,
                preview_status TEXT NOT NULL DEFAULT 'pending',
                preview_reason TEXT,
                preview_attempts INTEGER NOT NULL DEFAULT 0,
                preview_policy_version INTEGER NOT NULL DEFAULT 1,
                preview_updated_at TEXT,
                preview_source TEXT
            );
            CREATE TABLE assetfile (
                id TEXT NOT NULL PRIMARY KEY,
                asset_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                mime TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                role TEXT NOT NULL DEFAULT 'supporting',
                storage_path TEXT NOT NULL,
                metadata_json TEXT,
                FOREIGN KEY(asset_id) REFERENCES asset(id)
            );
            CREATE TABLE appconfig (
                key TEXT NOT NULL PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE schema_migration (
                version INTEGER NOT NULL PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX idx_asset_folder_name_unique
                ON asset(COALESCE(folder_id, ''), name COLLATE NOCASE);
            CREATE UNIQUE INDEX idx_asset_storage_path_unique
                ON asset(storage_path) WHERE storage_path IS NOT NULL;
            CREATE UNIQUE INDEX idx_assetfile_storage_path_unique
                ON assetfile(storage_path);
            """
        )
        connection.executemany(
            "INSERT INTO schema_migration(version, name) VALUES (?, ?)",
            MIGRATIONS,
        )
        connection.executemany(
            "INSERT INTO folder(id, name, tags_json, parent_id) VALUES (?, ?, ?, ?)",
            (
                ("folder-workshop", "Workshop", '["shop"]', None),
                ("folder-fasteners", "Fasteners", '["hardware"]', "folder-workshop"),
                ("folder-jigs", "Jigs", '["production"]', "folder-workshop"),
            ),
        )
        metadata = prepared_metadata()
        assets = (
            (
                "asset-managed", "old-bracket-name.stl", "model/stl",
                len(FILES["Workshop/Fasteners/Renamed Bracket/old-bracket-name.stl"]),
                '["bracket","renamed"]', "Renamed Bracket", "Renamed without changing identity",
                "folder-fasteners", None, "Renamed Bracket", "MakersVault Fixture",
                "Workshop Upgrade", "Workshop/Fasteners/Renamed Bracket/old-bracket-name.stl",
                0, None, None, "ready", None, 1, 1,
                "2026-08-20T12:00:00Z", "legacy_thumbnail",
            ),
            (
                "asset-prepared", "plate-layout.3mf", "model/3mf",
                len(FILES["Workshop/Jigs/P1S Plate/plate-layout.3mf"]),
                '["bambu","fixture"]', "P1S Plate", "Plate layout with private prepared toolpath",
                "folder-jigs", None, "P1S Plate", "Fixture Creator", "Workshop Upgrade",
                "Workshop/Jigs/P1S Plate/plate-layout.3mf", 1, "file-prepared", metadata,
                "skipped_policy", "embedded_complexity", 0, 1,
                "2026-08-20T12:01:00Z", "embedded_thumbnail",
            ),
            (
                "asset-external-available", "available.step", "model/step", 23,
                '["mounted"]', "Available Mounted Source", "No-copy source is externally owned",
                "folder-fasteners", "/imports/available/available.step", "Available Mounted Source",
                "Fixture Creator", "Mounted Sources", None, 0, None, None,
                "pending", None, 0, 1, None, None,
            ),
            (
                "asset-external-missing", "missing.step", "model/step", 29,
                '["mounted","offline"]', "Missing Mounted Source", "Expected unavailable source",
                "folder-fasteners", "/imports/offline/missing.step", "Missing Mounted Source",
                "Fixture Creator", "Mounted Sources", None, 0, None, None,
                "pending", None, 0, 1, None, None,
            ),
            (
                "asset-interrupted", "interrupted.stl", "model/stl",
                len(FILES["Workshop/Jigs/Interrupted Preview/interrupted.stl"]),
                '["interrupted"]', "Interrupted Preview", "Prior preview work can be retried",
                "folder-jigs", None, "Interrupted Preview", "Fixture Creator", "Workshop Upgrade",
                "Workshop/Jigs/Interrupted Preview/interrupted.stl", 0, None, None,
                "pending", "worker_interrupted", 1, 1,
                "2026-08-20T12:02:00Z", None,
            ),
        )
        connection.executemany(
            """
            INSERT INTO asset(
                id, filename, mime, size, tags_json, title, notes, folder_id,
                source_path, name, creator, collection, storage_path,
                supporting_file_count, prepared_file_id, prepared_metadata_json,
                preview_status, preview_reason, preview_attempts,
                preview_policy_version, preview_updated_at, preview_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            assets,
        )
        connection.executemany(
            """
            INSERT INTO assetfile(
                id, asset_id, filename, mime, size, role, storage_path, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    "file-doc", "asset-prepared", "assembly.pdf", "application/pdf",
                    len(FILES["bundles/asset-prepared/file-doc/assembly.pdf"]), "supporting",
                    "bundles/asset-prepared/file-doc/assembly.pdf", None,
                ),
                (
                    "file-prepared", "asset-prepared", "plate.gcode", "text/x.gcode",
                    len(FILES["bundles/asset-prepared/file-prepared/plate.gcode"]), "prepared",
                    "bundles/asset-prepared/file-prepared/plate.gcode", metadata,
                ),
            ),
        )
        connection.executemany(
            "INSERT INTO appconfig(key, value) VALUES (?, ?)",
            (
                ("mount_import_enabled", "1"),
                ("mount_import_copy", "0"),
                ("storage_template", "{folder}/{name}/{filename}"),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def build_fixture(output: Path, api_image: str) -> None:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Fixture output must be empty: {output}")
    database_dir = output / "database"
    storage_dir = output / "storage"
    imports_dir = output / "imports"
    database_dir.mkdir(parents=True, exist_ok=True)
    storage_dir.mkdir(parents=True, exist_ok=True)
    (imports_dir / "available").mkdir(parents=True, exist_ok=True)
    create_database(database_dir / "app.db")
    for name, data in FILES.items():
        destination = storage_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (imports_dir / "available/available.step").write_bytes(b"externally-owned-step\n")

    expected = {
        "pre_upgrade_schema": 4,
        "post_upgrade_schema": 5,
        "asset_ids": sorted(
            (
                "asset-managed", "asset-prepared", "asset-external-available",
                "asset-external-missing", "asset-interrupted",
            )
        ),
        "managed_sha256": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(FILES.items())
            if not name.startswith("thumbs/")
        },
        "prepared_summary": json.loads(prepared_metadata()),
    }
    (output / "expected.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "deploy.env").write_text(
        "\n".join(
            (
                f"API_IMAGE={api_image}",
                "WEB_IMAGE=makersvault-web:gate5-unused",
                "AUTH_USERNAME=gate5",
                "AUTH_PASSWORD=gate5-recovery-password",
                "AUTH_SECRET=gate5-recovery-signing-secret-32-bytes-minimum-value",
                "API_PORT=0",
                "WEB_PORT=0",
                "CORS_ORIGINS=http://localhost",
                "TRUSTED_HOSTS=localhost,127.0.0.1",
                "IMPORT_MOUNT_PATH=/imports",
                f"IMPORT_MOUNT_PATH_HOST={imports_dir.resolve()}",
                "IMPORT_MOUNT_COPY=false",
                "IMPORT_MOUNT_ON_STARTUP=false",
                f"PUID={os.getuid()}",
                f"PGID={os.getgid()}",
                "",
            )
        ),
        encoding="utf-8",
    )
    os.chmod(output / "deploy.env", 0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-image", required=True)
    args = parser.parse_args()
    build_fixture(args.output, args.api_image)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
