"""Clean-instance, staged importer for MakersVault portable vault v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

from content_store import LocalContentStore
from mvault_verify import CATALOGS, VerificationLimits, verify_archive


EXPECTED_SCHEMA_VERSION = 12
CHUNK_BYTES = 1024 * 1024
LOGICAL_TABLES = (
    "folder", "asset", "artifactrevision", "assetfile", "project",
    "projectmembership", "projectrelationship", "machineprofile", "artifactmachine",
)
OPERATIONAL_TABLES = (
    "mountscan", "contenthashjob", "contenthashjobitem", "trashpurgeoperation",
)
ProgressCallback = Callable[[str, dict[str, object]], None]
CONTENT_RE = re.compile(r"^mvault/content/(?P<kind>revisions|files)/(?P<id>[A-Za-z0-9][A-Za-z0-9._:-]{0,254})/(?P<leaf>primary|payload)$")
DERIVED_RE = re.compile(r"^mvault/derived/thumbnails/revisions/(?P<id>[A-Za-z0-9][A-Za-z0-9._:-]{0,254})$")
CATALOG_RE = re.compile(r"^mvault/catalogs/(?P<name>[a-z-]+)\.jsonl$")


class MvaultImportError(RuntimeError):
    pass


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_db(value: object) -> str | None:
    return None if value is None else _canonical(value)


def _provider_token(record_id: str) -> str:
    return hashlib.sha256(record_id.encode("utf-8")).hexdigest()


def _target_key(kind: str, record_id: str) -> str:
    token = _provider_token(record_id)
    if kind == "revisions":
        return f"revisions/{token}/primary"
    if kind == "files":
        return f"bundles/portable/{token}/payload"
    if kind == "derived":
        return f"thumbs/revisions/{token}.jpg"
    raise MvaultImportError(f"unknown payload kind {kind!r}")


def _stream_copy(source: BinaryIO, destination: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as output:
            os.chmod(destination, 0o600)
            while True:
                chunk = source.read(CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return size, digest.hexdigest()


def _hash_file(source: BinaryIO) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = source.read(CHUNK_BYTES)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


class PortableVaultImporter:
    def __init__(
        self,
        archive: Path,
        database: Path,
        storage: Path,
        *,
        limits: VerificationLimits | None = None,
        batch_size: int = 500,
        progress: ProgressCallback | None = None,
    ):
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.archive = archive.resolve()
        self.database = database.absolute()
        self.storage = storage.absolute()
        if (
            self.database == self.storage
            or self.storage in self.database.parents
            or self.database in self.storage.parents
        ):
            raise ValueError("database and storage targets must not overlap")
        self.limits = limits or VerificationLimits()
        self.batch_size = batch_size
        self.progress = progress
        self.operation_id = str(uuid.uuid4())
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.storage.parent.mkdir(parents=True, exist_ok=True)
        self.journal = self._journal_path()
        self.database_stage_root: Path | None = None
        self.storage_stage: Path | None = None
        self.staged_database: Path | None = None
        self.private_archive: Path | None = None
        self.inventory_path: Path | None = None
        self.inventory: sqlite3.Connection | None = None
        self.source_verification: dict[str, object] | None = None

    def restore(self) -> dict[str, object]:
        self._notify("import_started", archive=str(self.archive))
        self._recover_interrupted_publication()
        self._notify("target_check_started")
        self._require_empty_target()
        self._notify("target_empty")
        if not self.archive.is_file():
            raise MvaultImportError("portable archive does not exist")
        self.database_stage_root = Path(tempfile.mkdtemp(prefix=".mvault-import-db-", dir=self.database.parent))
        self.storage_stage = Path(tempfile.mkdtemp(prefix=".mvault-import-storage-", dir=self.storage.parent))
        os.chmod(self.database_stage_root, 0o700)
        os.chmod(self.storage_stage, 0o700)
        self.staged_database = self.database_stage_root / "app.db"
        self.private_archive = self.database_stage_root / "source.mvault"
        self.inventory_path = self.database_stage_root / "inventory.sqlite3"
        try:
            archive_sha256 = self._copy_and_verify_archive()
            self._notify("archive_verified", archive_sha256=archive_sha256)
            self._create_schema()
            self._notify("staging_schema_created", schema_version=EXPECTED_SCHEMA_VERSION)
            self.inventory = sqlite3.connect(self.inventory_path)
            self.inventory.row_factory = sqlite3.Row
            self._create_inventory()
            self._stage_archive()
            self._notify("archive_staged")
            self._validate_and_finalize_database()
            staged_report = self._audit_pair(self.staged_database, self.storage_stage)
            self._notify(
                "staged_pair_audited",
                managed_bytes=staged_report["managed_bytes"],
                managed_files=staged_report["managed_files"],
            )
            publication = self._publish(archive_sha256)
            assert self.source_verification is not None
            external_records = int(self.source_verification["external"]["records"])
            self._notify("import_complete", external_references=external_records)
            return {
                "archive_sha256": archive_sha256,
                "database": str(self.database),
                "external_references": {
                    "records": external_records,
                    "requires_remount": external_records,
                    "restored_unavailable": external_records,
                },
                "storage": str(self.storage),
                "source_verification": self.source_verification,
                "staged_audit": staged_report,
                "publication": publication,
            }
        except MvaultImportError:
            raise
        except Exception as exc:
            raise MvaultImportError(str(exc) or type(exc).__name__) from exc
        finally:
            if self.inventory is not None:
                self.inventory.close()
                self.inventory = None
            if not self.journal.exists():
                self._cleanup_staging()

    def _notify(self, phase: str, **details: object) -> None:
        if self.progress is not None:
            self.progress(phase, details)

    def _journal_path(self) -> Path:
        identity = hashlib.sha256(f"{self.database}\0{self.storage}".encode()).hexdigest()[:16]
        return self.database.parent / f".mvault-import-{identity}.json"

    def _require_empty_target(self) -> None:
        if self.storage.exists():
            if self.storage.is_symlink() or not self.storage.is_dir() or any(self.storage.iterdir()):
                raise MvaultImportError("target storage must be an empty directory or absent")
        if not self.database.exists():
            return
        if self.database.is_symlink() or not self.database.is_file():
            raise MvaultImportError("target database path is not a regular file")
        for suffix in ("-wal", "-shm", "-journal"):
            if Path(str(self.database) + suffix).exists():
                raise MvaultImportError("target database has active SQLite sidecar files; stop the instance")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.database, timeout=0, isolation_level=None)
            connection.execute("BEGIN EXCLUSIVE")
            if [str(row[0]) for row in connection.execute("PRAGMA quick_check")] != ["ok"]:
                raise MvaultImportError("target database failed quick_check")
            tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "schema_migration" not in tables:
                raise MvaultImportError("existing target database is not a compatible empty instance")
            version = int(connection.execute("SELECT COALESCE(MAX(version),0) FROM schema_migration").fetchone()[0])
            if version != EXPECTED_SCHEMA_VERSION:
                raise MvaultImportError(f"existing target schema is {version}; expected {EXPECTED_SCHEMA_VERSION}")
            for table in (*LOGICAL_TABLES, *OPERATIONAL_TABLES, "appconfig"):
                if table in tables and int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]):
                    raise MvaultImportError("target database is not empty; merge restore is not supported")
        except MvaultImportError:
            raise
        except sqlite3.Error as exc:
            raise MvaultImportError("target database is busy or incompatible; stop the instance") from exc
        finally:
            if connection is not None:
                try:
                    connection.rollback()
                finally:
                    connection.close()

    def _copy_and_verify_archive(self) -> str:
        assert self.private_archive is not None
        try:
            with self.archive.open("rb") as source:
                self._notify("archive_copy_started")
                _, digest = _stream_copy(source, self.private_archive)
            self._notify("archive_copy_complete")
            if self.progress is None:
                self.source_verification = verify_archive(self.private_archive, self.limits)
            else:
                self.source_verification = verify_archive(
                    self.private_archive, self.limits, progress=self.progress
                )
            return digest
        except Exception as exc:
            raise MvaultImportError(f"portable archive verification failed: {exc}") from exc

    def _create_schema(self) -> None:
        assert self.staged_database is not None and self.storage_stage is not None
        old_db = os.environ.get("DB_URL")
        old_storage = os.environ.get("FILE_STORAGE")
        os.environ["DB_URL"] = f"sqlite:///{self.staged_database}"
        os.environ["FILE_STORAGE"] = str(self.storage_stage)
        try:
            from sqlalchemy import create_engine
            from migrations import MIGRATIONS, run_migrations

            engine = create_engine(f"sqlite:///{self.staged_database}")
            try:
                version = run_migrations(engine, MIGRATIONS[:EXPECTED_SCHEMA_VERSION])
            finally:
                engine.dispose()
            if version != EXPECTED_SCHEMA_VERSION:
                raise MvaultImportError("could not create the current schema-12 staging database")
            os.chmod(self.staged_database, 0o600)
        finally:
            if old_db is None:
                os.environ.pop("DB_URL", None)
            else:
                os.environ["DB_URL"] = old_db
            if old_storage is None:
                os.environ.pop("FILE_STORAGE", None)
            else:
                os.environ["FILE_STORAGE"] = old_storage

    def _create_inventory(self) -> None:
        assert self.inventory is not None
        self.inventory.executescript(
            """
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            CREATE TABLE payload(
              member TEXT PRIMARY KEY, kind TEXT NOT NULL, record_id TEXT NOT NULL,
              target_key TEXT NOT NULL UNIQUE, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
              seen INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE catalog_record(
              catalog TEXT NOT NULL, record_key TEXT NOT NULL, data TEXT NOT NULL,
              PRIMARY KEY(catalog,record_key)
            );
            """
        )

    @staticmethod
    def _record_key(catalog: str, record: dict[str, object]) -> str:
        if catalog == "project-memberships":
            return f"{record['project_id']}\x1f{record['asset_id']}"
        if catalog == "artifact-machines":
            return f"{record['asset_id']}\x1f{record['machine_id']}"
        return str(record.get("id", record.get("key", "")))

    def _stage_archive(self) -> None:
        assert self.private_archive is not None and self.storage_stage is not None and self.inventory is not None
        store = LocalContentStore(self.storage_stage)
        database = sqlite3.connect(self.staged_database)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=OFF")
        try:
            with tarfile.open(self.private_archive, mode="r|gz") as archive:
                for member in archive:
                    content = CONTENT_RE.fullmatch(member.name)
                    derived = DERIVED_RE.fullmatch(member.name)
                    catalog_match = CATALOG_RE.fullmatch(member.name)
                    if content or derived:
                        source = archive.extractfile(member)
                        if source is None:
                            raise MvaultImportError(f"cannot read payload {member.name!r}")
                        if content:
                            kind, record_id = content.group("kind"), content.group("id")
                        else:
                            kind, record_id = "derived", derived.group("id")
                        target_key = _target_key(kind, record_id)
                        staged = store.staging_path(f"import-{self.operation_id}", _provider_token(member.name))
                        size, digest = _stream_copy(source, staged)
                        store.publish(staged, target_key)
                        self.inventory.execute(
                            "INSERT INTO payload(member,kind,record_id,target_key,size,sha256) VALUES (?,?,?,?,?,?)",
                            (member.name, kind, record_id, target_key, size, digest),
                        )
                    elif catalog_match:
                        catalog = catalog_match.group("name")
                        if catalog not in CATALOGS:
                            raise MvaultImportError(f"unknown catalog {catalog!r}")
                        source = archive.extractfile(member)
                        if source is None:
                            raise MvaultImportError(f"cannot read catalog {catalog!r}")
                        for line in source:
                            record = json.loads(line)
                            key = self._record_key(catalog, record)
                            self.inventory.execute(
                                "INSERT INTO catalog_record(catalog,record_key,data) VALUES (?,?,?)",
                                (catalog, key, _canonical(record)),
                            )
                            self._insert_record(database, catalog, record)
            self.inventory.commit()
            database.commit()
        except Exception:
            database.rollback()
            raise
        finally:
            database.close()

    def _insert_record(self, db: sqlite3.Connection, catalog: str, record: dict[str, object]) -> None:
        if catalog == "folders":
            db.execute("INSERT INTO folder(id,name,tags_json,parent_id) VALUES (?,?,?,?)", (record["id"], record["name"], _json_db(record["tags"]), record["parent_id"]))
        elif catalog == "machines":
            db.execute(
                "INSERT INTO machineprofile(id,name,category,manufacturer,model,location,notes,created_at,updated_at,archived_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                tuple(record[key] for key in ("id", "name", "category", "manufacturer", "model", "location", "notes", "created_at", "updated_at", "archived_at")),
            )
        elif catalog == "artifacts":
            preview = record["preview"]
            db.execute(
                """INSERT INTO asset(
                  id,name,filename,mime,size,tags_json,title,notes,creator,collection,folder_id,
                  source_path,storage_path,supporting_file_count,prepared_file_id,prepared_metadata_json,
                  prepared_machine_id,preview_status,preview_reason,preview_attempts,preview_policy_version,
                  preview_updated_at,preview_source,current_revision_id,current_thumb_path,deleted_at,
                  trash_original_folder_id,trash_original_folder_name
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record["id"], record["name"], record["filename"], record["mime"], record["size"],
                    _json_db(record["tags"]), record["title"], record["notes"], record["creator"], record["collection"],
                    record["folder_id"], None, None, record["supporting_file_count"], record["prepared_file_id"],
                    _json_db(record["prepared_metadata"]), record["prepared_machine_id"], preview["status"], preview["reason"],
                    0, preview["policy_version"], None, preview["source"], record["current_revision_id"], None,
                    record["deleted_at"], record["trash_original_folder_id"], record["trash_original_folder_name"],
                ),
            )
        elif catalog == "revisions":
            content, preview = record["content"], record["preview"]
            payload = self._payload(record["id"], "revisions") if content["ownership"] == "managed" else None
            derived = self._payload(record["id"], "derived", required=False)
            if payload:
                storage_path, source_path, state, reason, observed = payload["target_key"], None, "ready", None, payload["sha256"]
            else:
                storage_path, source_path = None, content["source_path"]
                state, reason, observed = "unavailable", "external_remount_required", None
            db.execute(
                """INSERT INTO artifactrevision(
                  id,asset_id,revision_number,created_at,origin_revision_id,filename,mime,size,sha256,
                  observed_sha256,content_state,content_reason,content_checked_at,storage_path,source_path,
                  change_note,prepared_file_id,prepared_metadata_json,prepared_machine_id,preview_status,
                  preview_reason,preview_attempts,preview_policy_version,preview_updated_at,preview_source,
                  preview_thumb_path
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record["id"], record["asset_id"], record["revision_number"], record["created_at"],
                    record["origin_revision_id"], record["filename"], record["mime"], record["size"], record["sha256"],
                    observed, state, reason, record["created_at"], storage_path, source_path, record["change_note"],
                    record["prepared_file_id"], _json_db(record["prepared_metadata"]), record["prepared_machine_id"],
                    preview["status"], preview["reason"], 0, preview["policy_version"], None, preview["source"],
                    derived["target_key"] if derived else None,
                ),
            )
        elif catalog == "files":
            payload = self._payload(record["id"], "files")
            db.execute(
                "INSERT INTO assetfile(id,asset_id,filename,mime,size,role,storage_path,metadata_json,revision_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (record["id"], record["asset_id"], record["filename"], record["mime"], record["size"], record["role"], payload["target_key"], _json_db(record["metadata"]), record["revision_id"]),
            )
        elif catalog == "projects":
            db.execute(
                "INSERT INTO project(id,name,notes,creator,source_url,license,tags_json,created_at,updated_at,deleted_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (record["id"], record["name"], record["notes"], record["creator"], record["source_url"], record["license"], _json_db(record["tags"]), record["created_at"], record["updated_at"], record["deleted_at"]),
            )
        elif catalog == "project-memberships":
            db.execute("INSERT INTO projectmembership(project_id,asset_id,created_at) VALUES (?,?,?)", (record["project_id"], record["asset_id"], record["created_at"]))
        elif catalog == "project-relationships":
            db.execute(
                "INSERT INTO projectrelationship(id,project_id,source_asset_id,target_asset_id,kind,created_at) VALUES (?,?,?,?,?,?)",
                (record["id"], record["project_id"], record["source_asset_id"], record["target_asset_id"], record["kind"], record["created_at"]),
            )
        elif catalog == "artifact-machines":
            db.execute("INSERT INTO artifactmachine(asset_id,machine_id,created_at) VALUES (?,?,?)", (record["asset_id"], record["machine_id"], record["created_at"]))
        elif catalog == "settings":
            value = record["value"] if isinstance(record["value"], str) else _canonical(record["value"])
            db.execute("INSERT INTO appconfig(key,value) VALUES (?,?)", (record["key"], value))

    def _payload(self, record_id: str, kind: str, *, required: bool = True) -> sqlite3.Row | None:
        assert self.inventory is not None
        row = self.inventory.execute("SELECT * FROM payload WHERE kind=? AND record_id=?", (kind, record_id)).fetchone()
        if required and row is None:
            raise MvaultImportError(f"{kind} record {record_id!r} is missing staged content")
        return row

    def _validate_and_finalize_database(self) -> None:
        assert self.staged_database is not None and self.inventory is not None
        db = sqlite3.connect(self.staged_database)
        db.row_factory = sqlite3.Row
        try:
            for row in db.execute("SELECT * FROM asset ORDER BY id"):
                current_id = row["current_revision_id"]
                if current_id is None:
                    raise MvaultImportError(f"artifact {row['id']!r} has no current revision")
                revision = db.execute("SELECT * FROM artifactrevision WHERE id=? AND asset_id=?", (current_id, row["id"])).fetchone()
                if revision is None:
                    raise MvaultImportError(f"artifact {row['id']!r} current revision is invalid")
                portable = self.inventory.execute("SELECT data FROM catalog_record WHERE catalog='artifacts' AND record_key=?", (row["id"],)).fetchone()
                portable_revision = self.inventory.execute("SELECT data FROM catalog_record WHERE catalog='revisions' AND record_key=?", (current_id,)).fetchone()
                artifact_record, revision_record = json.loads(portable[0]), json.loads(portable_revision[0])
                comparable = (
                    ("filename", artifact_record["filename"], revision_record["filename"]),
                    ("mime", artifact_record["mime"], revision_record["mime"]),
                    ("size", artifact_record["size"], revision_record["size"]),
                    ("prepared_file_id", artifact_record["prepared_file_id"], revision_record["prepared_file_id"]),
                    ("prepared_machine_id", artifact_record["prepared_machine_id"], revision_record["prepared_machine_id"]),
                    ("prepared_metadata", artifact_record["prepared_metadata"], revision_record["prepared_metadata"]),
                    ("preview", artifact_record["preview"], revision_record["preview"]),
                )
                for field, artifact_value, revision_value in comparable:
                    if artifact_value != revision_value:
                        raise MvaultImportError(f"artifact {row['id']!r} {field} does not match its current revision")
                db.execute(
                    """UPDATE asset SET storage_path=?,source_path=?,current_thumb_path=?,
                      preview_attempts=0,preview_updated_at=NULL WHERE id=?""",
                    (revision["storage_path"], revision["source_path"], revision["preview_thumb_path"], row["id"]),
                )
            db.commit()
            db.execute("PRAGMA foreign_keys=ON")
            foreign = list(db.execute("PRAGMA foreign_key_check"))
            if foreign:
                raise MvaultImportError(f"staged database has {len(foreign)} foreign-key violation(s)")
            self._reject_cycles(db)
        finally:
            db.close()

    @staticmethod
    def _reject_cycles(db: sqlite3.Connection) -> None:
        checks = (
            ("folder", "WITH RECURSIVE walk(root,node) AS (SELECT id,parent_id FROM folder WHERE parent_id IS NOT NULL UNION SELECT walk.root,folder.parent_id FROM walk JOIN folder ON folder.id=walk.node WHERE folder.parent_id IS NOT NULL) SELECT 1 FROM walk WHERE root=node LIMIT 1"),
            ("revision origin", "WITH RECURSIVE walk(root,node) AS (SELECT id,origin_revision_id FROM artifactrevision WHERE origin_revision_id IS NOT NULL UNION SELECT walk.root,artifactrevision.origin_revision_id FROM walk JOIN artifactrevision ON artifactrevision.id=walk.node WHERE artifactrevision.origin_revision_id IS NOT NULL) SELECT 1 FROM walk WHERE root=node LIMIT 1"),
            ("Project relationship", "WITH RECURSIVE walk(project_id,kind,root,node) AS (SELECT project_id,kind,source_asset_id,target_asset_id FROM projectrelationship WHERE kind IN ('derived_from','component_of') UNION SELECT walk.project_id,walk.kind,walk.root,r.target_asset_id FROM walk JOIN projectrelationship r ON r.project_id=walk.project_id AND r.kind=walk.kind AND r.source_asset_id=walk.node) SELECT 1 FROM walk WHERE root=node LIMIT 1"),
        )
        for label, query in checks:
            if db.execute(query).fetchone():
                raise MvaultImportError(f"staged {label} graph contains a cycle")

    def _audit_pair(self, database_path: Path, storage_path: Path) -> dict[str, object]:
        assert self.inventory is not None
        store = LocalContentStore(storage_path)
        db = sqlite3.connect(database_path)
        db.row_factory = sqlite3.Row
        try:
            if [str(row[0]) for row in db.execute("PRAGMA quick_check")] != ["ok"]:
                raise MvaultImportError("staged database failed quick_check")
            if list(db.execute("PRAGMA foreign_key_check")):
                raise MvaultImportError("staged database failed foreign_key_check")
            for table in OPERATIONAL_TABLES:
                if int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]):
                    raise MvaultImportError(f"operational table {table} must be empty after portable import")
            checked_files = 0
            checked_bytes = 0
            for payload in self.inventory.execute("SELECT * FROM payload ORDER BY target_key"):
                try:
                    with store.open_read(payload["target_key"]) as source:
                        size, digest = _hash_file(source)
                except Exception as exc:
                    raise MvaultImportError(f"staged payload {payload['record_id']!r} is unavailable") from exc
                if size != payload["size"] or digest != payload["sha256"]:
                    raise MvaultImportError(f"staged payload {payload['record_id']!r} failed size/digest audit")
                self.inventory.execute("UPDATE payload SET seen=1 WHERE member=?", (payload["member"],))
                checked_files += 1
                checked_bytes += size
            for batch in store.iter_key_batches(batch_size=self.batch_size):
                for key in batch:
                    if self.inventory.execute("SELECT 1 FROM payload WHERE target_key=?", (key,)).fetchone() is None:
                        raise MvaultImportError(f"staged storage contains orphan key {key!r}")
            if self.inventory.execute("SELECT 1 FROM payload WHERE seen=0 LIMIT 1").fetchone():
                raise MvaultImportError("staged storage is missing an expected payload")
            counts = {
                table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in LOGICAL_TABLES
            }
            self.inventory.commit()
            return {"logical_records": counts, "managed_bytes": checked_bytes, "managed_files": checked_files}
        finally:
            db.close()

    def _publish(self, archive_sha256: str) -> dict[str, object]:
        assert self.staged_database is not None and self.storage_stage is not None
        db_backup = self.database.parent / f".mvault-import-{self.operation_id}.db.empty"
        storage_backup = self.storage.parent / f".mvault-import-{self.operation_id}.storage.empty"
        journal = {
            "version": 1,
            "operation_id": self.operation_id,
            "archive_sha256": archive_sha256,
            "database": str(self.database),
            "storage": str(self.storage),
            "staged_database": str(self.staged_database),
            "staged_storage": str(self.storage_stage),
            "database_backup": str(db_backup),
            "storage_backup": str(storage_backup),
            "database_existed": self.database.exists(),
            "storage_existed": self.storage.exists(),
            "state": "prepared",
        }
        self._write_journal(journal)
        self._notify("publication_started")
        try:
            if self.storage.exists():
                os.replace(self.storage, storage_backup)
            os.replace(self.storage_stage, self.storage)
            self._fsync_directory(self.storage.parent)
            journal["state"] = "storage_published"
            self._write_journal(journal)
            self._notify("storage_published")
            self._after_storage_publish()
            if self.database.exists():
                os.replace(self.database, db_backup)
            os.replace(self.staged_database, self.database)
            self._fsync_directory(self.database.parent)
            journal["state"] = "database_published"
            self._write_journal(journal)
            self._notify("database_published")
            report = self._audit_pair(self.database, self.storage)
            self.journal.unlink()
            self._fsync_directory(self.journal.parent)
        except BaseException:
            self._rollback_journal(journal)
            raise
        self._remove_path(db_backup)
        self._remove_path(storage_backup)
        return {"state": "published", "audit": report}

    def _after_storage_publish(self) -> None:
        """Test hook at the only intentionally split publication boundary."""

    def _write_journal(self, value: dict[str, object]) -> None:
        temporary = self.journal.with_suffix(self.journal.suffix + ".tmp")
        data = (_canonical(value) + "\n").encode()
        if temporary.exists() or temporary.is_symlink():
            raise MvaultImportError(f"interrupted-import temporary journal already exists: {temporary}")
        with temporary.open("xb") as output:
            os.chmod(temporary, 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.journal)
        self._fsync_directory(self.journal.parent)

    def _recover_interrupted_publication(self) -> None:
        temporary = self.journal.with_suffix(self.journal.suffix + ".tmp")
        if not self.journal.exists():
            temporary.unlink(missing_ok=True)
            return
        if self.journal.is_symlink() or not self.journal.is_file():
            raise MvaultImportError(f"interrupted-import journal is not a regular file: {self.journal}")
        try:
            value = json.loads(self.journal.read_text())
        except Exception as exc:
            raise MvaultImportError(f"interrupted-import journal is unreadable: {self.journal}") from exc
        self._validate_journal(value)
        temporary.unlink(missing_ok=True)
        self._rollback_journal(value)

    def _validate_journal(self, value: object) -> None:
        required = {
            "version", "operation_id", "archive_sha256", "database", "storage",
            "staged_database", "staged_storage", "database_backup", "storage_backup",
            "database_existed", "storage_existed", "state",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise MvaultImportError("interrupted-import journal has an invalid structure")
        if value["version"] != 1 or value["state"] not in {"prepared", "storage_published", "database_published"}:
            raise MvaultImportError("interrupted-import journal has an unsupported version or state")
        if type(value["database_existed"]) is not bool or type(value["storage_existed"]) is not bool:
            raise MvaultImportError("interrupted-import journal has invalid existence flags")
        operation_id = str(value["operation_id"])
        try:
            if str(uuid.UUID(operation_id)) != operation_id:
                raise ValueError
        except ValueError as exc:
            raise MvaultImportError("interrupted-import journal has an invalid operation ID") from exc
        if not re.fullmatch(r"[0-9a-f]{64}", str(value["archive_sha256"])):
            raise MvaultImportError("interrupted-import journal has an invalid archive digest")
        if value["database"] != str(self.database) or value["storage"] != str(self.storage):
            raise MvaultImportError("interrupted-import journal target does not match this invocation")
        staged_database = Path(str(value["staged_database"]))
        staged_storage = Path(str(value["staged_storage"]))
        expected_database_backup = self.database.parent / f".mvault-import-{operation_id}.db.empty"
        expected_storage_backup = self.storage.parent / f".mvault-import-{operation_id}.storage.empty"
        safe_database_stage = (
            staged_database.name == "app.db"
            and staged_database.parent.parent == self.database.parent
            and staged_database.parent.name.startswith(".mvault-import-db-")
        )
        safe_storage_stage = (
            staged_storage.parent == self.storage.parent
            and staged_storage.name.startswith(".mvault-import-storage-")
        )
        if (
            not safe_database_stage
            or not safe_storage_stage
            or Path(str(value["database_backup"])) != expected_database_backup
            or Path(str(value["storage_backup"])) != expected_storage_backup
        ):
            raise MvaultImportError("interrupted-import journal contains unsafe recovery paths")

    def _rollback_journal(self, value: dict[str, object]) -> None:
        database_backup = Path(str(value["database_backup"]))
        storage_backup = Path(str(value["storage_backup"]))
        staged_database = Path(str(value["staged_database"]))
        staged_storage = Path(str(value["staged_storage"]))
        if value.get("state") in {"database_published"} or (not staged_database.exists() and self.database.exists()):
            self._remove_path(self.database)
        if database_backup.exists():
            os.replace(database_backup, self.database)
        if value.get("state") in {"storage_published", "database_published"} or (not staged_storage.exists() and self.storage.exists()):
            self._remove_path(self.storage)
        if storage_backup.exists():
            os.replace(storage_backup, self.storage)
        self._remove_path(staged_database.parent)
        self._remove_path(staged_storage)
        self.journal.unlink(missing_ok=True)
        self.journal.with_suffix(self.journal.suffix + ".tmp").unlink(missing_ok=True)
        self._fsync_directory(self.journal.parent)
        if self.storage.parent != self.journal.parent:
            self._fsync_directory(self.storage.parent)

    def _cleanup_staging(self) -> None:
        if self.database_stage_root is not None:
            self._remove_path(self.database_stage_root)
        if self.storage_stage is not None:
            self._remove_path(self.storage_stage)

    @staticmethod
    def _remove_path(path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def import_archive(
    archive: Path | str,
    database: Path | str,
    storage: Path | str,
    *,
    limits: VerificationLimits | None = None,
    batch_size: int = 500,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    return PortableVaultImporter(
        Path(archive), Path(database), Path(storage), limits=limits, batch_size=batch_size,
        progress=progress,
    ).restore()


def _positive(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore portable .mvault v1 into an empty stopped MakersVault instance")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--storage", required=True)
    parser.add_argument("--batch-size", type=_positive, default=500)
    parser.add_argument("--max-members", type=_positive)
    parser.add_argument("--max-records", type=_positive)
    parser.add_argument("--max-expanded-bytes", type=_positive)
    parser.add_argument("--confirm-stopped-empty", action="store_true")
    parser.add_argument("--progress", action="store_true", help="write canonical phase events to stderr")
    args = parser.parse_args(argv)
    if not args.confirm_stopped_empty:
        parser.error("--confirm-stopped-empty is required; live or merge restore is not supported")
    defaults = VerificationLimits()
    limits = VerificationLimits(
        args.max_members or defaults.max_members,
        args.max_records or defaults.max_records,
        args.max_expanded_bytes or defaults.max_expanded_bytes,
    )
    progress = None
    if args.progress:
        def progress(phase: str, details: dict[str, object]) -> None:
            event = {"operation": "import", "phase": phase, **details}
            print(
                "mvault-progress " + json.dumps(event, sort_keys=True, separators=(",", ":")),
                file=sys.stderr,
                flush=True,
            )
    try:
        report = import_archive(
            args.archive, args.database, args.storage, limits=limits,
            batch_size=args.batch_size, progress=progress,
        )
    except KeyboardInterrupt:
        print(
            "mvault import cancelled; keep MakersVault stopped and inspect the target before retrying",
            file=sys.stderr,
        )
        return 130
    except MvaultImportError as exc:
        print(f"mvault import failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
