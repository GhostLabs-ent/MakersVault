from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

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


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "initial_schema", _migration_001_initial_schema),
    Migration(2, "nested_folders_and_mount_sources", _migration_002_nested_folders_and_mount_sources),
    Migration(3, "asset_metadata_and_bundles", _migration_003_asset_metadata_and_bundles),
    Migration(4, "persistent_preview_state", _migration_004_preview_state),
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
