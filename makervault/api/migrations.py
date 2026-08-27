from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
import uuid

from sqlalchemy.engine import Connection, Engine

from db import engine


MigrationCallable = Callable[[Connection], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationCallable


def _columns(conn: Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    }


def _add_column(conn: Connection, table: str, column: str, sql_type: str) -> None:
    if column not in _columns(conn, table):
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")


def _migration_001_initial_schema(conn: Connection) -> None:
    """Create the original pre-v5.1 schema without depending on current models."""
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS folder (
            id VARCHAR NOT NULL PRIMARY KEY,
            name VARCHAR NOT NULL,
            tags_json VARCHAR NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS asset (
            id VARCHAR NOT NULL PRIMARY KEY,
            filename VARCHAR NOT NULL,
            mime VARCHAR NOT NULL,
            size INTEGER NOT NULL,
            tags_json VARCHAR NOT NULL DEFAULT '[]',
            title VARCHAR,
            notes VARCHAR,
            folder_id VARCHAR
        )
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS appconfig (
            key VARCHAR NOT NULL PRIMARY KEY,
            value VARCHAR NOT NULL
        )
        """
    )


def _migration_002_nested_folders_and_mount_sources(conn: Connection) -> None:
    _add_column(conn, "folder", "parent_id", "TEXT")
    _add_column(conn, "asset", "source_path", "TEXT")


def _migration_003_asset_metadata_and_bundles(conn: Connection) -> None:
    additions = {
        "name": "TEXT",
        "creator": "TEXT",
        "collection": "TEXT",
        "storage_path": "TEXT",
        "supporting_file_count": "INTEGER NOT NULL DEFAULT 0",
        "prepared_file_id": "TEXT",
        "prepared_metadata_json": "TEXT",
    }
    for column, sql_type in additions.items():
        _add_column(conn, "asset", column, sql_type)

    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS assetfile (
            id VARCHAR NOT NULL PRIMARY KEY,
            asset_id VARCHAR NOT NULL,
            filename VARCHAR NOT NULL,
            mime VARCHAR NOT NULL,
            size INTEGER NOT NULL DEFAULT 0,
            role VARCHAR NOT NULL DEFAULT 'supporting',
            storage_path VARCHAR NOT NULL,
            metadata_json VARCHAR,
            FOREIGN KEY(asset_id) REFERENCES asset(id)
        )
        """
    )

    rows = conn.exec_driver_sql(
        "SELECT id, filename, title, folder_id, name, storage_path FROM asset ORDER BY id"
    ).fetchall()
    used: dict[str, set[str]] = {}
    for row in rows:
        asset_id, filename, title, folder_id, current_name, storage_path = row
        base = (current_name or title or Path(filename or "model").stem or "model").strip()
        base = base.replace("/", "_").replace("\\", "_") or "model"
        folder_key = folder_id or ""
        folder_names = used.setdefault(folder_key, set())
        candidate = base
        suffix = 2
        while candidate.casefold() in folder_names:
            candidate = f"{base} ({suffix})"
            suffix += 1
        folder_names.add(candidate.casefold())
        legacy_path = storage_path or f"{asset_id}/{filename}"
        conn.exec_driver_sql(
            "UPDATE asset SET name = ?, title = ?, storage_path = ? WHERE id = ?",
            (candidate, candidate, legacy_path, asset_id),
        )

    conn.exec_driver_sql(
        "UPDATE asset SET supporting_file_count = ("
        "SELECT COUNT(*) FROM assetfile "
        "WHERE assetfile.asset_id = asset.id AND assetfile.role = 'supporting'"
        ")"
    )

    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_asset_filename ON asset(filename)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_asset_folder_id ON asset(folder_id)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_asset_size ON asset(size)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_asset_name ON asset(name)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_asset_creator ON asset(creator)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_asset_collection ON asset(collection)")
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_folder_name_unique "
        "ON asset(COALESCE(folder_id, ''), name COLLATE NOCASE)"
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_storage_path_unique "
        "ON asset(storage_path) WHERE storage_path IS NOT NULL"
    )
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_assetfile_asset_id ON assetfile(asset_id)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_assetfile_role ON assetfile(role)")
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_assetfile_storage_path_unique "
        "ON assetfile(storage_path)"
    )


def _migration_004_preview_state(conn: Connection) -> None:
    additions = {
        "preview_status": "TEXT NOT NULL DEFAULT 'pending'",
        "preview_reason": "TEXT",
        "preview_attempts": "INTEGER NOT NULL DEFAULT 0",
        "preview_policy_version": "INTEGER NOT NULL DEFAULT 1",
        "preview_updated_at": "TEXT",
        "preview_source": "TEXT",
    }
    for column, sql_type in additions.items():
        _add_column(conn, "asset", column, sql_type)
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_asset_preview_status ON asset(preview_status)"
    )


def _migration_005_mount_scan_records(conn: Connection) -> None:
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS mountscan (
            id VARCHAR NOT NULL PRIMARY KEY,
            trigger VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            mode VARCHAR NOT NULL,
            root_path VARCHAR NOT NULL,
            started_at VARCHAR NOT NULL,
            finished_at VARCHAR,
            imported INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            failure_details_json VARCHAR NOT NULL DEFAULT '[]',
            failure_details_omitted INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_mountscan_trigger ON mountscan(trigger)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_mountscan_status ON mountscan(status)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_mountscan_started_at ON mountscan(started_at)"
    )


def _migration_006_artifact_revisions_and_content_identity(conn: Connection) -> None:
    _add_column(conn, "asset", "current_revision_id", "TEXT")
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS artifactrevision (
            id VARCHAR NOT NULL PRIMARY KEY,
            asset_id VARCHAR NOT NULL,
            revision_number INTEGER NOT NULL,
            created_at VARCHAR NOT NULL,
            origin_revision_id VARCHAR,
            filename VARCHAR NOT NULL,
            mime VARCHAR NOT NULL,
            size INTEGER NOT NULL DEFAULT 0,
            sha256 VARCHAR,
            observed_sha256 VARCHAR,
            content_state VARCHAR NOT NULL DEFAULT 'pending',
            content_reason VARCHAR,
            content_checked_at VARCHAR,
            storage_path VARCHAR,
            source_path VARCHAR,
            change_note VARCHAR,
            prepared_file_id VARCHAR,
            prepared_metadata_json VARCHAR,
            preview_status VARCHAR NOT NULL DEFAULT 'pending',
            preview_reason VARCHAR,
            preview_attempts INTEGER NOT NULL DEFAULT 0,
            preview_policy_version INTEGER NOT NULL DEFAULT 1,
            preview_updated_at VARCHAR,
            preview_source VARCHAR,
            preview_thumb_path VARCHAR,
            FOREIGN KEY(asset_id) REFERENCES asset(id),
            FOREIGN KEY(origin_revision_id) REFERENCES artifactrevision(id)
        )
        """
    )
    _add_column(conn, "assetfile", "revision_id", "TEXT")

    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_artifactrevision_asset_number_unique "
        "ON artifactrevision(asset_id, revision_number)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_artifactrevision_asset_id "
        "ON artifactrevision(asset_id)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_artifactrevision_sha256 "
        "ON artifactrevision(sha256)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_artifactrevision_content_state "
        "ON artifactrevision(content_state)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_asset_current_revision_id "
        "ON asset(current_revision_id)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_assetfile_revision_id "
        "ON assetfile(revision_id)"
    )

    assets = conn.exec_driver_sql(
        """
        SELECT id, filename, mime, size, storage_path, source_path,
               prepared_file_id, prepared_metadata_json,
               preview_status, preview_reason, preview_attempts,
               preview_policy_version, preview_updated_at, preview_source,
               current_revision_id
        FROM asset
        ORDER BY id
        """
    ).fetchall()
    for asset in assets:
        asset_id = str(asset[0])
        revision_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"makersvault:artifact:{asset_id}:revision:1")
        )
        current_revision_id = asset[14]
        if not current_revision_id:
            conn.exec_driver_sql(
                """
                INSERT OR IGNORE INTO artifactrevision(
                    id, asset_id, revision_number, created_at, filename, mime, size,
                    storage_path, source_path, prepared_file_id,
                    prepared_metadata_json, preview_status, preview_reason,
                    preview_attempts, preview_policy_version, preview_updated_at,
                    preview_source, preview_thumb_path, content_state
                ) VALUES (?, ?, 1, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    revision_id,
                    asset_id,
                    asset[1],
                    asset[2],
                    asset[3],
                    asset[4],
                    asset[5],
                    asset[6],
                    asset[7],
                    asset[8],
                    asset[9],
                    asset[10],
                    asset[11],
                    asset[12],
                    asset[13],
                    f"thumbs/{asset_id}.jpg",
                ),
            )
            conn.exec_driver_sql(
                "UPDATE asset SET current_revision_id = ? WHERE id = ?",
                (revision_id, asset_id),
            )
        if asset[6]:
            conn.exec_driver_sql(
                "UPDATE assetfile SET revision_id = ? WHERE id = ? AND role = 'prepared'",
                (revision_id, asset[6]),
            )

    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS contenthashjob (
            id VARCHAR NOT NULL PRIMARY KEY,
            trigger VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            started_at VARCHAR NOT NULL,
            finished_at VARCHAR,
            total INTEGER NOT NULL DEFAULT 0,
            processed INTEGER NOT NULL DEFAULT 0,
            ready INTEGER NOT NULL DEFAULT 0,
            unavailable INTEGER NOT NULL DEFAULT 0,
            changed INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            failure_details_json VARCHAR NOT NULL DEFAULT '[]',
            failure_details_omitted INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_contenthashjob_trigger ON contenthashjob(trigger)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_contenthashjob_status ON contenthashjob(status)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_contenthashjob_started_at ON contenthashjob(started_at)"
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS contenthashjobitem (
            job_id VARCHAR NOT NULL,
            revision_id VARCHAR NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'pending',
            reason VARCHAR,
            PRIMARY KEY(job_id, revision_id),
            FOREIGN KEY(job_id) REFERENCES contenthashjob(id),
            FOREIGN KEY(revision_id) REFERENCES artifactrevision(id)
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_contenthashjobitem_status "
        "ON contenthashjobitem(status)"
    )


def _migration_007_immutable_revision_workflows(conn: Connection) -> None:
    _add_column(conn, "asset", "current_thumb_path", "TEXT")
    conn.exec_driver_sql(
        """
        UPDATE asset
        SET current_thumb_path = (
            SELECT preview_thumb_path
            FROM artifactrevision
            WHERE artifactrevision.id = asset.current_revision_id
        )
        WHERE current_thumb_path IS NULL
        """
    )


def _migration_008_recoverable_trash(conn: Connection) -> None:
    _add_column(conn, "asset", "deleted_at", "TEXT")
    _add_column(conn, "asset", "trash_original_folder_id", "TEXT")
    _add_column(conn, "asset", "trash_original_folder_name", "TEXT")
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_asset_deleted_at ON asset(deleted_at)"
    )
    conn.exec_driver_sql("DROP INDEX IF EXISTS idx_asset_folder_name_unique")
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_folder_name_unique "
        "ON asset(COALESCE(folder_id, ''), LOWER(name)) WHERE deleted_at IS NULL"
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS trashpurgeoperation (
            id VARCHAR NOT NULL PRIMARY KEY,
            trigger VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            created_at VARCHAR NOT NULL,
            completed_at VARCHAR,
            asset_ids_json VARCHAR NOT NULL DEFAULT '[]',
            paths_json VARCHAR NOT NULL DEFAULT '[]',
            results_json VARCHAR NOT NULL DEFAULT '[]',
            quarantine_path VARCHAR,
            requested_bytes INTEGER NOT NULL DEFAULT 0,
            managed_bytes INTEGER NOT NULL DEFAULT 0,
            error VARCHAR
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_trashpurgeoperation_trigger "
        "ON trashpurgeoperation(trigger)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_trashpurgeoperation_status "
        "ON trashpurgeoperation(status)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_trashpurgeoperation_created_at "
        "ON trashpurgeoperation(created_at)"
    )


def _migration_009_projects_and_membership(conn: Connection) -> None:
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS project (
            id VARCHAR NOT NULL PRIMARY KEY,
            name VARCHAR NOT NULL,
            notes VARCHAR,
            creator VARCHAR,
            source_url VARCHAR,
            license VARCHAR,
            tags_json VARCHAR NOT NULL DEFAULT '[]',
            created_at VARCHAR NOT NULL,
            updated_at VARCHAR NOT NULL,
            deleted_at VARCHAR
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_project_active_name_unique "
        "ON project(LOWER(name)) WHERE deleted_at IS NULL"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_project_deleted_at ON project(deleted_at)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_project_updated_at ON project(updated_at)"
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS projectmembership (
            project_id VARCHAR NOT NULL,
            asset_id VARCHAR NOT NULL,
            created_at VARCHAR NOT NULL,
            PRIMARY KEY(project_id, asset_id),
            FOREIGN KEY(project_id) REFERENCES project(id) ON DELETE CASCADE,
            FOREIGN KEY(asset_id) REFERENCES asset(id) ON DELETE CASCADE
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_projectmembership_asset_id "
        "ON projectmembership(asset_id)"
    )


def _migration_010_project_relationships(conn: Connection) -> None:
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS projectrelationship (
            id VARCHAR NOT NULL PRIMARY KEY,
            project_id VARCHAR NOT NULL,
            source_asset_id VARCHAR NOT NULL,
            target_asset_id VARCHAR NOT NULL,
            kind VARCHAR NOT NULL CHECK (
                kind IN ('derived_from', 'documentation_for', 'component_of')
            ),
            created_at VARCHAR NOT NULL,
            CHECK (source_asset_id <> target_asset_id),
            FOREIGN KEY(project_id) REFERENCES project(id) ON DELETE CASCADE,
            FOREIGN KEY(source_asset_id) REFERENCES asset(id) ON DELETE CASCADE,
            FOREIGN KEY(target_asset_id) REFERENCES asset(id) ON DELETE CASCADE
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_projectrelationship_canonical_unique "
        "ON projectrelationship(project_id, source_asset_id, target_asset_id, kind)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_projectrelationship_project_id "
        "ON projectrelationship(project_id)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_projectrelationship_source_asset_id "
        "ON projectrelationship(source_asset_id)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_projectrelationship_target_asset_id "
        "ON projectrelationship(target_asset_id)"
    )


def _migration_011_machine_profiles(conn: Connection) -> None:
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS machineprofile (
            id VARCHAR NOT NULL PRIMARY KEY,
            name VARCHAR NOT NULL,
            category VARCHAR NOT NULL CHECK (
                category IN (
                    'fdm_printer', 'resin_printer', 'laser',
                    'cnc', 'pcb', 'other'
                )
            ),
            manufacturer VARCHAR,
            model VARCHAR,
            location VARCHAR,
            notes VARCHAR,
            created_at VARCHAR NOT NULL,
            updated_at VARCHAR NOT NULL,
            archived_at VARCHAR
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_machineprofile_active_name_unique "
        "ON machineprofile(name COLLATE NOCASE) WHERE archived_at IS NULL"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_machineprofile_category "
        "ON machineprofile(category)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_machineprofile_updated_at "
        "ON machineprofile(updated_at)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_machineprofile_archived_at "
        "ON machineprofile(archived_at)"
    )


def _migration_012_artifact_machine_context(conn: Connection) -> None:
    _add_column(
        conn,
        "asset",
        "prepared_machine_id",
        "TEXT REFERENCES machineprofile(id) ON DELETE SET NULL",
    )
    _add_column(
        conn,
        "artifactrevision",
        "prepared_machine_id",
        "TEXT REFERENCES machineprofile(id) ON DELETE SET NULL",
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS artifactmachine (
            asset_id VARCHAR NOT NULL,
            machine_id VARCHAR NOT NULL,
            created_at VARCHAR NOT NULL,
            PRIMARY KEY (asset_id, machine_id),
            FOREIGN KEY(asset_id) REFERENCES asset(id) ON DELETE CASCADE,
            FOREIGN KEY(machine_id) REFERENCES machineprofile(id) ON DELETE CASCADE
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_artifactmachine_machine_id "
        "ON artifactmachine(machine_id)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_asset_prepared_machine_id "
        "ON asset(prepared_machine_id)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_artifactrevision_prepared_machine_id "
        "ON artifactrevision(prepared_machine_id)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "initial_schema", _migration_001_initial_schema),
    Migration(2, "nested_folders_and_mount_sources", _migration_002_nested_folders_and_mount_sources),
    Migration(3, "asset_metadata_and_bundles", _migration_003_asset_metadata_and_bundles),
    Migration(4, "persistent_preview_state", _migration_004_preview_state),
    Migration(5, "persistent_mount_scan_records", _migration_005_mount_scan_records),
    Migration(6, "artifact_revisions_and_content_identity", _migration_006_artifact_revisions_and_content_identity),
    Migration(7, "immutable_revision_workflows", _migration_007_immutable_revision_workflows),
    Migration(8, "recoverable_trash", _migration_008_recoverable_trash),
    Migration(9, "projects_and_membership", _migration_009_projects_and_membership),
    Migration(10, "project_relationships", _migration_010_project_relationships),
    Migration(11, "machine_profiles", _migration_011_machine_profiles),
    Migration(12, "artifact_machine_context", _migration_012_artifact_machine_context),
)


def _ensure_migration_table(database_engine: Engine) -> None:
    with database_engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS schema_migration (
                version INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR NOT NULL,
                applied_at VARCHAR NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def applied_migrations(database_engine: Engine = engine) -> dict[int, str]:
    _ensure_migration_table(database_engine)
    with database_engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT version, name FROM schema_migration ORDER BY version"
        ).fetchall()
    return {int(version): str(name) for version, name in rows}


def run_migrations(
    database_engine: Engine = engine,
    migrations: Iterable[Migration] = MIGRATIONS,
) -> int:
    """Apply each missing migration once and return the resulting schema version."""
    _ensure_migration_table(database_engine)
    ordered = tuple(sorted(migrations, key=lambda migration: migration.version))
    if len({migration.version for migration in ordered}) != len(ordered):
        raise RuntimeError("Duplicate schema migration version")
    expected_versions = {migration.version for migration in ordered}
    unexpected_versions = set(applied_migrations(database_engine)) - expected_versions
    if unexpected_versions:
        versions = ", ".join(str(version) for version in sorted(unexpected_versions))
        raise RuntimeError(
            f"Database contains schema migration version(s) newer or unknown to this build: {versions}"
        )

    for migration in ordered:
        with database_engine.begin() as conn:
            existing = conn.exec_driver_sql(
                "SELECT name FROM schema_migration WHERE version = ?",
                (migration.version,),
            ).fetchone()
            if existing:
                if str(existing[0]) != migration.name:
                    raise RuntimeError(
                        f"Schema migration {migration.version} is recorded as "
                        f"{existing[0]!r}, expected {migration.name!r}"
                    )
                continue
            migration.apply(conn)
            conn.exec_driver_sql(
                "INSERT INTO schema_migration(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )

    applied = applied_migrations(database_engine)
    return max(applied, default=0)


if __name__ == "__main__":
    print(f"MakersVault schema version: {run_migrations(engine)}")
