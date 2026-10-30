import re
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


_INVALID_PATH_SEGMENT_RE = re.compile(r'[<>:"|?*\x00-\x1f]')


def _folder_path_segment(name: str) -> str:
    """Same rules as asset_service.sanitize_path_segment, copied locally.

    migrations are immutable, so 004 must not depend on a helper that may change
    later; the copy also keeps fastapi/PIL out of `python -m migrations`.
    """
    cleaned = _INVALID_PATH_SEGMENT_RE.sub("_", (name or "").strip())
    cleaned = cleaned.replace("/", "_").replace("\\", "_").strip(" .")
    if cleaned in {"", ".", ".."}:
        cleaned = "Folder"
    return cleaned[:120]


def _storage_root() -> Path:
    """Resolve the storage root at call time so tests can monkeypatch it."""
    import db

    return Path(db.STORAGE)


def _effective_folder_parent(folder_id: str, parent_id: str | None, parents: dict[str, str | None]) -> str | None:
    """Parent id, or None when the parent is missing or the chain loops."""
    if parent_id is None or parent_id not in parents:
        return None
    walked = {folder_id}
    current = parent_id
    while True:
        if current in walked:
            return None
        walked.add(current)
        next_parent = parents.get(current)
        if next_parent is None:
            return parent_id
        if next_parent not in parents:
            return None
        current = next_parent


def _backfill_folder_storage_paths(conn: Connection) -> None:
    """Assign a relative storage_path to every folder that has none.

    Assignment depends only on (casefold(name), id) ordering, so it is
    independent of row insertion order. Siblings that collide get the
    `Name (2)`, `Name (3)`, ... suffixes used by the shipped asset-name dedupe,
    and a folder whose own name is the literal name of a sibling never takes
    that sibling's name. A suffix is appended after the 120-character segment
    truncation, so paths may be up to 124 characters; Mf-oh78 must not assume
    a 120-character ceiling.
    """
    rows = conn.exec_driver_sql("SELECT id, name, parent_id, storage_path FROM folder").fetchall()
    names = {str(row[0]): str(row[1] or "") for row in rows}
    parents = {str(row[0]): (None if row[2] is None else str(row[2])) for row in rows}
    assigned = {str(row[0]): str(row[3]) for row in rows if row[3] is not None}
    effective = {folder_id: _effective_folder_parent(folder_id, parents[folder_id], parents) for folder_id in names}

    def scope(folder_id: str | None) -> str:
        return str(folder_id or "")

    used: dict[str, set[str]] = {}
    reserved: dict[str, set[str]] = {}
    for folder_id, name in names.items():
        reserved.setdefault(scope(effective[folder_id]), set()).add(_folder_path_segment(name).casefold())
    for folder_id, path in assigned.items():
        used.setdefault(scope(effective[folder_id]), set()).add(path.rsplit("/", 1)[-1].casefold())

    depths: dict[str, int] = {}

    def depth(folder_id: str) -> int:
        if folder_id not in depths:
            parent = effective[folder_id]
            depths[folder_id] = 0 if parent is None else depth(parent) + 1
        return depths[folder_id]

    pending = sorted(
        (folder_id for folder_id in names if folder_id not in assigned),
        key=lambda folder_id: (depth(folder_id), scope(effective[folder_id]), names[folder_id].casefold(), folder_id),
    )
    for folder_id in pending:
        parent = effective[folder_id]
        scope_key = scope(parent)
        segment = _folder_path_segment(names[folder_id])
        sibling_used = used.setdefault(scope_key, set())
        sibling_names = reserved.setdefault(scope_key, set())
        candidate = segment
        suffix = 2
        while candidate.casefold() in sibling_used or (
            candidate.casefold() != segment.casefold() and candidate.casefold() in sibling_names
        ):
            candidate = f"{segment} ({suffix})"
            suffix += 1
        sibling_used.add(candidate.casefold())
        prefix = assigned[parent] if parent else ""
        assigned[folder_id] = f"{prefix}/{candidate}" if prefix else candidate

    for folder_id in pending:
        conn.exec_driver_sql(
            "UPDATE folder SET storage_path = ? WHERE id = ? AND storage_path IS NULL",
            (assigned[folder_id], folder_id),
        )


def _is_mount_reference(storage_root: Path, storage_path: str, source_path: str) -> bool:
    """True when the managed copy is gone and the source lives outside storage."""
    try:
        if (storage_root / storage_path).exists():
            return False
    except OSError:
        return False
    try:
        resolved_source = Path(source_path).resolve()
    except OSError:
        return False
    return resolved_source != storage_root and storage_root not in resolved_source.parents


def _backfill_asset_reference_flags(conn: Connection) -> None:
    storage_root = _storage_root().resolve()
    rows = conn.exec_driver_sql("SELECT id, filename, storage_path, source_path FROM asset ORDER BY id").fetchall()
    flagged = 0
    for asset_id, filename, storage_path, source_path in rows:
        managed_relative = str(storage_path or f"{asset_id}/{filename}")
        is_reference = 1 if source_path is not None and _is_mount_reference(storage_root, managed_relative, str(source_path)) else 0
        flagged += is_reference
        conn.exec_driver_sql(
            "UPDATE asset SET is_reference = ? WHERE id = ? AND is_reference != ?",
            (is_reference, asset_id, is_reference),
        )
    print(f"[migration-004] flagged {flagged} of {len(rows)} assets as mount references")


def _migration_004_folder_identity_and_reference_flags(conn: Connection) -> None:
    """Add folder storage paths and asset reference bookkeeping (append-only).

    DB-only: no file is created, moved, renamed or deleted. Folder siblings get
    `Name (2)`, `Name (3)`, ... suffixes, and duplicates are resolved from
    (casefold(name), id) ordering so the result never depends on insertion
    order. `is_reference = 1` means the asset has a source_path, its managed
    file at `storage_path` is absent, and the source resolves outside the
    storage root.

    NULL `missing_since` and `disk_mtime` mean "never scanned" and are owned by
    Mf-itr4. A NULL folder `storage_path` means "not yet assigned" and is owned
    by Mf-oh78. `is_reference` is a point-in-time snapshot: if the storage
    volume is unmounted when 004 runs, copy-mode mount imports would be
    misflagged, which is why the run prints how many assets it flagged.
    """
    _add_column(conn, "folder", "storage_path", "TEXT")
    _add_column(conn, "asset", "missing_since", "TEXT")
    _add_column(conn, "asset", "disk_mtime", "INTEGER")
    _add_column(conn, "asset", "is_reference", "INTEGER NOT NULL DEFAULT 0")
    _backfill_folder_storage_paths(conn)
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_folder_storage_path_unique ON folder(storage_path COLLATE NOCASE)"
    )
    _backfill_asset_reference_flags(conn)


def _migration_005_users_and_sessions(conn: Connection) -> None:
    """Add accounts and revocable sessions (append-only, no data backfill).

    `users.username` and `users.email` are unique case-insensitively, so a
    login cannot be shadowed by a copy that differs only in case. `sessions`
    stores `user_id NULL` for the env break-glass admin and keeps `username`
    denormalized so `/me` and audit trails survive user deletion. Timestamps
    are epoch seconds where they drive expiry and ISO-8601 UTC where they are
    only read by humans. `IF NOT EXISTS` everywhere keeps a re-applied 005
    harmless; later session features (listing, pruning, reuse detection) belong
    to Mf-7op4 and must not change this file.
    """
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS users (
            id VARCHAR NOT NULL PRIMARY KEY,
            username VARCHAR NOT NULL,
            email VARCHAR,
            password_hash VARCHAR,
            role VARCHAR NOT NULL DEFAULT 'viewer',
            disabled INTEGER NOT NULL DEFAULT 0,
            created_at VARCHAR NOT NULL,
            updated_at VARCHAR NOT NULL
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_unique ON users(username COLLATE NOCASE)"
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email COLLATE NOCASE) "
        "WHERE email IS NOT NULL"
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id VARCHAR NOT NULL PRIMARY KEY,
            user_id VARCHAR,
            username VARCHAR NOT NULL,
            kind VARCHAR NOT NULL DEFAULT 'password',
            refresh_token_hash VARCHAR NOT NULL,
            device VARCHAR,
            user_agent VARCHAR,
            client_ip VARCHAR,
            created_at INTEGER NOT NULL,
            last_used_at INTEGER NOT NULL,
            access_expires_at INTEGER NOT NULL,
            refresh_expires_at INTEGER NOT NULL,
            revoked_at INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_refresh_hash_unique ON sessions(refresh_token_hash)"
    )
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_sessions_refresh_expires_at ON sessions(refresh_expires_at)"
    )


def _migration_006_audit_log(conn: Connection) -> None:
    """Add the append-only audit log (new table, no backfill).

    The log starts when it starts: there is nothing older to backfill. `actor`
    and `actor_role` are denormalised copies taken at write time so a row still
    reads correctly after the account is renamed, re-roled or deleted.
    `created_at` is ISO-8601 UTC written by Python, which is also the format the
    `GET /audit` date bounds are compared against lexicographically. The two
    triggers are the actual append-only guarantee, enforced by SQLite rather
    than by the convention that no helper updates or deletes a row. `IF NOT
    EXISTS` on every object keeps a re-applied 006 harmless, like 004 and 005.
    """
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id            VARCHAR NOT NULL PRIMARY KEY,
            created_at    VARCHAR NOT NULL,
            actor         VARCHAR NOT NULL,
            actor_user_id VARCHAR,
            actor_role    VARCHAR NOT NULL,
            actor_kind    VARCHAR NOT NULL,
            action        VARCHAR NOT NULL,
            target        VARCHAR NOT NULL,
            detail_json   TEXT,
            request_id    VARCHAR NOT NULL,
            method        VARCHAR NOT NULL,
            path          VARCHAR NOT NULL
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at DESC)"
    )
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events(actor)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events(action)")
    conn.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS audit_events_no_update
        BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
        BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END
        """
    )


def _migration_007_projects(conn: Connection) -> None:
    """Add projects and their asset memberships (append-only, DB-only).

    No file is created, moved, renamed or deleted. `created_at`/`updated_at`/
    `added_at` are ISO-8601 UTC text written by Python via
    `datetime.now(timezone.utc).isoformat(timespec="microseconds")`: one
    canonical format keeps ordering lexicographic, exactly like `audit_events`.
    The `origin` and `role` CHECK lists are closed on purpose - adding a value
    later means a new migration. `idx_project_name_unique` is case-insensitive,
    so `PLA` and `pla` are the same project and no second non-unique NOCASE
    index is needed. `owner_id` is declared now, NULL until Mf-19is fills it, so
    that ticket does not have to rebuild the table; `ON DELETE SET NULL` matches
    the rule that project rows survive their owner's deletion.

    The orphan sweep exists because 007 is the migration that turns on
    `PRAGMA foreign_keys` in the API engine: `assetfile` rows whose asset is
    already gone were tolerated by the old connection default and would fail
    every later `asset` delete. It is a plain DELETE, so it behaves identically
    with the pragma on or off. `IF NOT EXISTS` on every object keeps a re-applied
    007 harmless, like 004-006.
    """
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS project (
            id VARCHAR NOT NULL PRIMARY KEY,
            name VARCHAR NOT NULL,
            description TEXT,
            creator VARCHAR,
            source_url VARCHAR,
            licence VARCHAR,
            licence_url VARCHAR,
            origin VARCHAR NOT NULL DEFAULT 'own' CHECK (origin IN ('own', 'imported')),
            cover_asset_id VARCHAR REFERENCES asset(id) ON DELETE SET NULL,
            owner_id VARCHAR REFERENCES users(id) ON DELETE SET NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at VARCHAR NOT NULL,
            updated_at VARCHAR NOT NULL
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_project_name_unique ON project(name COLLATE NOCASE)"
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS project_asset (
            project_id VARCHAR NOT NULL REFERENCES project(id) ON DELETE CASCADE,
            asset_id VARCHAR NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
            role VARCHAR NOT NULL DEFAULT 'member'
                CHECK (role IN ('member', 'primary', 'preview', 'supporting')),
            position INTEGER NOT NULL DEFAULT 0,
            added_at VARCHAR NOT NULL,
            PRIMARY KEY (project_id, asset_id)
        )
        """
    )
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_project_asset_asset_id ON project_asset(asset_id)")
    result = conn.exec_driver_sql("DELETE FROM assetfile WHERE asset_id NOT IN (SELECT id FROM asset)")
    print(f"[migration-007] removed {result.rowcount} orphaned assetfile row(s)")


def _migration_008_import_run_history(conn: Connection) -> None:
    """Add the mount-import run history table (new table, no backfill).

    One row per attempted mount import, bounded to the newest 50 by the service
    that writes it. `status` is a closed vocabulary; `skipped` is a deliberate
    non-alarm outcome with a mandatory `reason`, and `running` rows older than a
    process start are turned into `interrupted` at boot. `mode` is NULL only for
    a run that never got as far as reading the copy/reference setting. The
    counters are raw scan counters; the API derives `discovered` and `skipped`
    for presentation. `IF NOT EXISTS` on every object keeps a re-applied 008
    harmless, like 004-007.
    """
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS import_run (
            id VARCHAR NOT NULL PRIMARY KEY,
            kind VARCHAR NOT NULL DEFAULT 'mount' CHECK (kind IN ('mount')),
            status VARCHAR NOT NULL CHECK (
                status IN ('running', 'succeeded', 'failed', 'interrupted', 'skipped')
            ),
            mode VARCHAR CHECK (mode IN ('copy', 'reference')),
            root TEXT,
            started_at REAL NOT NULL,
            finished_at REAL,
            registered INTEGER NOT NULL DEFAULT 0,
            known INTEGER NOT NULL DEFAULT 0,
            ignored INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            rejected INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            errors_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_import_run_started_at ON import_run(started_at DESC)"
    )


def _migration_009_asset_file_order(conn: Connection) -> None:
    """Give supporting files an explicit, user-visible order (append-only).

    `position` is the only thing a reorder changes: a file's bytes, its
    `storage_path` and its role never move, so reordering is metadata. The
    backfill runs only when the column is newly added - a re-applied 009 must
    never reset an order the user chose - and it assigns 0..n-1 per asset from
    (filename, id), which is the order every earlier build displayed, so no
    existing library changes shape because of this migration. Non-supporting
    (prepared) rows keep 0: they are not listed and never reordered. `IF NOT
    EXISTS` on the index keeps a re-applied 009 harmless, like 004-008.
    """
    had_column = "position" in _columns(conn, "assetfile")
    _add_column(conn, "assetfile", "position", "INTEGER NOT NULL DEFAULT 0")
    if not had_column:
        conn.exec_driver_sql(
            "UPDATE assetfile SET position = ("
            "SELECT COUNT(*) FROM assetfile AS earlier "
            "WHERE earlier.asset_id = assetfile.asset_id "
            "AND earlier.role = 'supporting' "
            "AND (earlier.filename < assetfile.filename "
            "OR (earlier.filename = assetfile.filename AND earlier.id < assetfile.id))"
            ") "
            "WHERE assetfile.role = 'supporting'"
        )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_assetfile_asset_position ON assetfile(asset_id, position)"
    )


def _migration_010_oidc_identities(conn: Connection) -> None:
    """Bind an external identity to a local account (Mf-4c24).

    `(issuer, subject)` is the only binding key, and it is unique: the pair is
    the provider's immutable principal id, so two rows for one principal would
    let the same person accumulate accounts, and matching on username or email
    instead would let a claim claim an existing local account. `user_id` is a
    plain foreign key with no cascade, matching `sessions` in migration 005: an
    account that still has an identity must not be silently deletable.

    Pure `CREATE ... IF NOT EXISTS`, so re-applying 010 is harmless, like
    004-009.
    """
    conn.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS oidc_identities (
            id VARCHAR NOT NULL PRIMARY KEY,
            issuer VARCHAR NOT NULL,
            subject VARCHAR NOT NULL,
            user_id VARCHAR NOT NULL,
            created_at VARCHAR NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id))"""
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_oidc_identities_issuer_subject_unique "
        "ON oidc_identities(issuer, subject)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS idx_oidc_identities_user_id ON oidc_identities(user_id)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "initial_schema", _migration_001_initial_schema),
    Migration(2, "nested_folders_and_mount_sources", _migration_002_nested_folders_and_mount_sources),
    Migration(3, "asset_metadata_and_bundles", _migration_003_asset_metadata_and_bundles),
    Migration(4, "folder_identity_and_reference_flags", _migration_004_folder_identity_and_reference_flags),
    Migration(5, "users_and_sessions", _migration_005_users_and_sessions),
    Migration(6, "audit_log", _migration_006_audit_log),
    Migration(7, "projects", _migration_007_projects),
    Migration(8, "import_run_history", _migration_008_import_run_history),
    Migration(9, "asset_file_order", _migration_009_asset_file_order),
    Migration(10, "oidc_identities", _migration_010_oidc_identities),
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
