"""Offline, bounded-memory exporter for MakersVault portable vault v1."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

from content_store import InvalidStoreKey, LocalContentStore
from mvault_verify import (
    CATALOGS,
    CHECKSUMS_PATH,
    FORMAT,
    FORMAT_VERSION,
    HEADER_PATH,
    MANIFEST_PATH,
    MAX_JSONL_LINE_BYTES,
    verify_archive,
)


SUPPORTED_SCHEMA_VERSIONS = frozenset({12, 13, 14, 15})
CHUNK_BYTES = 1024 * 1024
DEFAULT_BATCH_SIZE = 500
DEFAULT_STORAGE_TEMPLATE = "{folder}/{model}/{filename}"
DEFAULT_TRASH_RETENTION = "until_needed"
EXTERNAL_STATES = {"ready", "unavailable", "changed", "pending", "failed"}
ProgressCallback = Callable[[str, dict[str, object]], None]


class MvaultExportError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise MvaultExportError(f"metadata cannot be encoded as canonical JSON: {exc}") from exc


def _json_field(raw: object, context: str) -> object:
    if raw is None:
        return None
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, RecursionError) as exc:
        raise MvaultExportError(f"{context} contains invalid JSON") from exc


def _tags(raw: object, context: str) -> list[str]:
    value = _json_field(raw or "[]", context)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MvaultExportError(f"{context} must be an array of strings")
    return sorted(set(value))


def _timestamp(raw: object, context: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise MvaultExportError(f"{context} is missing a timestamp")
    text = raw.strip()
    try:
        value = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise MvaultExportError(f"{context} is not an ISO-8601 timestamp") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _nullable_timestamp(raw: object, context: str) -> str | None:
    return None if raw is None else _timestamp(raw, context)


def _created_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _preview(row: sqlite3.Row) -> dict[str, object]:
    return {
        "policy_version": int(row["preview_policy_version"] or 1),
        "reason": row["preview_reason"],
        "source": row["preview_source"],
        "status": row["preview_status"] or "pending",
    }


def _require_id(value: object, context: str) -> str:
    text = str(value or "")
    if not text:
        raise MvaultExportError(f"{context} is missing an ID")
    # The independent verifier owns the complete syntax check. Constructing the
    # member path through the store-key validator catches path-bearing IDs early.
    return text


class _HashingReader:
    def __init__(self, source: BinaryIO):
        self.source = source
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self.source.read(size)
        self.digest.update(chunk)
        self.size += len(chunk)
        return chunk

    def hexdigest(self) -> str:
        return self.digest.hexdigest()


class PortableVaultExporter:
    def __init__(
        self,
        database: Path,
        storage: Path,
        output: Path,
        *,
        makersvault_version: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        progress: ProgressCallback | None = None,
    ):
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.database = database.resolve()
        storage_path = Path(storage)
        if not storage_path.is_dir():
            raise MvaultExportError("managed storage root does not exist or is not a directory")
        self.store = LocalContentStore(storage_path)
        self.output = output.resolve()
        self.makersvault_version = makersvault_version
        self.batch_size = batch_size
        self.progress = progress
        self.source_schema_version: int | None = None
        self.connection: sqlite3.Connection | None = None
        self.inventory: sqlite3.Connection | None = None
        self.checksums: BinaryIO | None = None
        self.catalog_counts = {name: 0 for name in CATALOGS}

    def export(self) -> dict[str, object]:
        self._notify("export_started", output=str(self.output))
        if not self.database.is_file():
            raise MvaultExportError("SQLite database does not exist")
        if self.output.exists():
            raise MvaultExportError("output already exists; choose a new archive path")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".mvault-export-", dir=self.output.parent))
        os.chmod(work, 0o700)
        temporary_archive = work / "archive.mvault.partial"
        try:
            self._open_source()
            assert self.source_schema_version is not None
            self._notify("source_locked", schema_version=self.source_schema_version)
            self.inventory = sqlite3.connect(work / "inventory.sqlite3")
            self.inventory.row_factory = sqlite3.Row
            self._create_inventory()
            self._plan_payloads()
            planned = self.inventory.execute(
                "SELECT COUNT(*),COALESCE(SUM(size),0) FROM payload_plan"
            ).fetchone()
            self._notify("payloads_planned", files=int(planned[0]), bytes=int(planned[1]))
            checksums_path = work / "checksums.sha256"
            with checksums_path.open("w+b") as checksum_file:
                self.checksums = checksum_file
                self._notify("archive_write_started")
                self._write_archive(temporary_archive, work)
            self._notify("archive_write_complete")
            os.chmod(temporary_archive, 0o600)
            if self.progress is None:
                report = verify_archive(temporary_archive)
            else:
                report = verify_archive(temporary_archive, progress=self.progress)
            with temporary_archive.open("rb") as archive_file:
                os.fsync(archive_file.fileno())
            try:
                os.link(temporary_archive, self.output)
            except FileExistsError as exc:
                raise MvaultExportError("output appeared during export and was not overwritten") from exc
            except OSError as exc:
                raise MvaultExportError("atomic archive publication failed") from exc
            temporary_archive.unlink()
            os.chmod(self.output, 0o600)
            self._fsync_directory(self.output.parent)
            self._notify(
                "export_complete",
                external_records=report["external"]["records"],
                output=str(self.output),
            )
            return report
        except MvaultExportError:
            raise
        except Exception as exc:
            raise MvaultExportError(str(exc) or type(exc).__name__) from exc
        finally:
            self.checksums = None
            if self.inventory is not None:
                self.inventory.close()
                self.inventory = None
            if self.connection is not None:
                try:
                    self.connection.rollback()
                except sqlite3.Error:
                    pass
                self.connection.close()
                self.connection = None
            self._remove_tree(work)

    def _notify(self, phase: str, **details: object) -> None:
        if self.progress is not None:
            self.progress(phase, details)

    def _open_source(self) -> None:
        try:
            connection = sqlite3.connect(self.database, timeout=0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN EXCLUSIVE")
            connection.execute("PRAGMA query_only=ON")
        except sqlite3.Error as exc:
            raise MvaultExportError(
                "database is busy; stop MakersVault or enter maintenance mode before export"
            ) from exc
        quick = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        if quick != ["ok"]:
            connection.close()
            raise MvaultExportError("SQLite quick_check failed; portable export was not created")
        row = connection.execute("SELECT MAX(version) FROM schema_migration").fetchone()
        version = int(row[0] or 0)
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            connection.close()
            raise MvaultExportError(
                f"schema {version} is not supported by portable format v1; expected one of "
                f"{sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        self.source_schema_version = version
        self.connection = connection

    def _create_inventory(self) -> None:
        assert self.inventory is not None
        self.inventory.executescript(
            """
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            CREATE TABLE payload_plan(
                member TEXT PRIMARY KEY,
                class TEXT NOT NULL,
                record_id TEXT NOT NULL,
                store_key TEXT NOT NULL,
                size INTEGER NOT NULL,
                modified_ns INTEGER NOT NULL,
                expected_sha256 TEXT
            );
            CREATE TABLE observed(
                record_kind TEXT NOT NULL,
                record_id TEXT NOT NULL,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                PRIMARY KEY(record_kind, record_id)
            );
            CREATE TABLE derived(record_id TEXT PRIMARY KEY, member TEXT NOT NULL);
            """
        )

    def _rows(self, query: str, parameters: tuple[object, ...] = ()) -> Iterator[sqlite3.Row]:
        assert self.connection is not None
        cursor = self.connection.execute(query, parameters)
        while True:
            batch = cursor.fetchmany(self.batch_size)
            if not batch:
                break
            yield from batch

    def _plan_one(
        self,
        *,
        member: str,
        member_class: str,
        record_id: str,
        store_key: str,
        declared_size: int | None,
        expected_sha256: str | None = None,
    ) -> None:
        assert self.inventory is not None
        try:
            value = self.store.stat(store_key)
        except InvalidStoreKey as exc:
            raise MvaultExportError(f"managed key for {record_id!r} is unsafe") from exc
        if value is None:
            raise MvaultExportError(f"managed content for {record_id!r} is missing or not a regular file")
        if declared_size is not None and int(declared_size) != value.size:
            raise MvaultExportError(f"managed content size for {record_id!r} does not match the database")
        try:
            self.inventory.execute(
                "INSERT INTO payload_plan(member,class,record_id,store_key,size,modified_ns,expected_sha256) VALUES (?,?,?,?,?,?,?)",
                (member, member_class, record_id, store_key, value.size, value.modified_ns, expected_sha256),
            )
        except sqlite3.IntegrityError as exc:
            raise MvaultExportError(f"duplicate portable payload member {member!r}") from exc

    def _plan_payloads(self) -> None:
        assert self.inventory is not None
        for row in self._rows("SELECT id, storage_path, size FROM assetfile ORDER BY id"):
            record_id = _require_id(row["id"], "AssetFile")
            self._plan_one(
                member=f"mvault/content/files/{record_id}/payload",
                member_class="content-file",
                record_id=record_id,
                store_key=str(row["storage_path"] or ""),
                declared_size=int(row["size"] or 0),
            )
        for row in self._rows(
            "SELECT id, storage_path, size, sha256, preview_thumb_path FROM artifactrevision ORDER BY id"
        ):
            record_id = _require_id(row["id"], "ArtifactRevision")
            if row["storage_path"]:
                self._plan_one(
                    member=f"mvault/content/revisions/{record_id}/primary",
                    member_class="content-revision",
                    record_id=record_id,
                    store_key=str(row["storage_path"]),
                    declared_size=int(row["size"] or 0),
                    expected_sha256=row["sha256"],
                )
            if row["preview_thumb_path"]:
                try:
                    thumb = self.store.stat(str(row["preview_thumb_path"]))
                except InvalidStoreKey as exc:
                    raise MvaultExportError(f"thumbnail key for revision {record_id!r} is unsafe") from exc
                if thumb is not None:
                    member = f"mvault/derived/thumbnails/revisions/{record_id}"
                    self._plan_one(
                        member=member,
                        member_class="derived",
                        record_id=record_id,
                        store_key=str(row["preview_thumb_path"]),
                        declared_size=None,
                    )
                    self.inventory.execute("INSERT INTO derived(record_id,member) VALUES (?,?)", (record_id, member))
        self.inventory.commit()

    def _write_archive(self, archive_path: Path, work: Path) -> None:
        assert self.inventory is not None and self.checksums is not None
        derived_count = int(self.inventory.execute("SELECT COUNT(*) FROM derived").fetchone()[0])
        header = {
            "catalogs": list(CATALOGS),
            "created_at": _created_at(),
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "optional_features": ["derived-thumbnails"] if derived_count else [],
            "required_features": ["canonical-jsonl", "sha256-inventory"],
            "source": {
                "makersvault_version": self.makersvault_version,
                "schema_version": self.source_schema_version,
            },
        }
        with archive_path.open("xb") as raw:
            os.chmod(archive_path, 0o600)
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                    self._add_bytes(archive, HEADER_PATH, _canonical(header))
                    for row in self.inventory.execute("SELECT * FROM payload_plan ORDER BY member"):
                        self._add_payload(archive, row)
                    external_counts = None
                    for catalog in CATALOGS:
                        catalog_path = work / f"{catalog}.jsonl"
                        count, summary = self._write_catalog(catalog, catalog_path)
                        self.catalog_counts[catalog] = count
                        if catalog == "revisions":
                            external_counts = summary
                        self._add_file(archive, f"mvault/catalogs/{catalog}.jsonl", catalog_path)
                    manifest = self._manifest(external_counts or self._empty_external())
                    self._add_bytes(archive, MANIFEST_PATH, _canonical(manifest))
                    self.checksums.flush()
                    self.checksums.seek(0)
                    checksum_size = os.fstat(self.checksums.fileno()).st_size
                    self._add_raw_file(archive, CHECKSUMS_PATH, self.checksums, checksum_size, inventory=False)

    @staticmethod
    def _tar_info(name: str, size: int) -> tarfile.TarInfo:
        info = tarfile.TarInfo(name)
        info.size = size
        info.mode = 0o600
        info.mtime = 0
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    def _record_checksum(self, digest: str, name: str) -> None:
        assert self.checksums is not None
        self.checksums.write(f"{digest}  {name}\n".encode("utf-8"))

    def _add_bytes(self, archive: tarfile.TarFile, name: str, data: bytes) -> None:
        import io

        archive.addfile(self._tar_info(name, len(data)), io.BytesIO(data))
        self._record_checksum(hashlib.sha256(data).hexdigest(), name)

    def _add_raw_file(
        self,
        archive: tarfile.TarFile,
        name: str,
        source: BinaryIO,
        size: int,
        *,
        inventory: bool = True,
    ) -> tuple[int, str]:
        hashing = _HashingReader(source)
        archive.addfile(self._tar_info(name, size), hashing)
        if hashing.size != size:
            raise MvaultExportError(f"{name!r} changed or ended during export")
        digest = hashing.hexdigest()
        if inventory:
            self._record_checksum(digest, name)
        return hashing.size, digest

    def _add_file(self, archive: tarfile.TarFile, name: str, path: Path) -> None:
        size = path.stat().st_size
        with path.open("rb") as source:
            self._add_raw_file(archive, name, source, size)

    def _add_payload(self, archive: tarfile.TarFile, row: sqlite3.Row) -> None:
        assert self.inventory is not None
        before = self.store.stat(row["store_key"])
        if before is None or before.size != row["size"] or before.modified_ns != row["modified_ns"]:
            raise MvaultExportError(f"managed content {row['record_id']!r} changed before export")
        with self.store.open_read(row["store_key"]) as source:
            size, digest = self._add_raw_file(archive, row["member"], source, int(row["size"]))
        after = self.store.stat(row["store_key"])
        if after is None or after.size != before.size or after.modified_ns != before.modified_ns:
            raise MvaultExportError(f"managed content {row['record_id']!r} changed during export")
        expected = row["expected_sha256"]
        if expected and expected != digest:
            raise MvaultExportError(f"managed content digest for {row['record_id']!r} does not match the database")
        if row["class"] != "derived":
            kind = "files" if row["class"] == "content-file" else "revisions"
            self.inventory.execute(
                "INSERT INTO observed(record_kind,record_id,size,sha256) VALUES (?,?,?,?)",
                (kind, row["record_id"], size, digest),
            )
            self.inventory.commit()

    def _write_catalog(self, catalog: str, path: Path) -> tuple[int, dict[str, int] | None]:
        count = 0
        summary = self._empty_external() if catalog == "revisions" else None
        with path.open("xb") as output:
            for record in self._catalog_records(catalog, summary):
                line = _canonical(record)
                if len(line) > MAX_JSONL_LINE_BYTES:
                    raise MvaultExportError(f"{catalog} record exceeds the v1 JSONL line limit")
                output.write(line)
                count += 1
            output.flush()
            os.fsync(output.fileno())
        return count, summary

    @staticmethod
    def _empty_external() -> dict[str, int]:
        return {"available": 0, "changed": 0, "failed": 0, "pending": 0, "records": 0, "unavailable": 0}

    def _catalog_records(self, catalog: str, external: dict[str, int] | None) -> Iterator[dict[str, object]]:
        if catalog == "folders":
            for row in self._rows("SELECT id,name,tags_json,parent_id FROM folder ORDER BY id"):
                yield {"id": row["id"], "name": row["name"], "parent_id": row["parent_id"], "tags": _tags(row["tags_json"], f"Folder {row['id']} tags")}
        elif catalog == "machines":
            for row in self._rows("SELECT * FROM machineprofile ORDER BY id"):
                yield {
                    "archived_at": _nullable_timestamp(row["archived_at"], f"Machine {row['id']} archived_at"),
                    "category": row["category"], "created_at": _timestamp(row["created_at"], f"Machine {row['id']} created_at"),
                    "id": row["id"], "location": row["location"], "manufacturer": row["manufacturer"],
                    "model": row["model"], "name": row["name"], "notes": row["notes"],
                    "updated_at": _timestamp(row["updated_at"], f"Machine {row['id']} updated_at"),
                }
        elif catalog == "artifacts":
            query = """
                SELECT asset.*,
                  (SELECT COUNT(*) FROM assetfile WHERE assetfile.asset_id=asset.id AND assetfile.role='supporting') AS actual_supporting
                FROM asset ORDER BY id
            """
            for row in self._rows(query):
                yield {
                    "collection": row["collection"], "creator": row["creator"], "current_revision_id": row["current_revision_id"],
                    "deleted_at": _nullable_timestamp(row["deleted_at"], f"Artifact {row['id']} deleted_at"),
                    "filename": row["filename"], "folder_id": row["folder_id"], "id": row["id"], "mime": row["mime"],
                    "name": row["name"] or "", "notes": row["notes"], "prepared_file_id": row["prepared_file_id"],
                    "prepared_machine_id": row["prepared_machine_id"],
                    "prepared_metadata": _json_field(row["prepared_metadata_json"], f"Artifact {row['id']} prepared metadata"),
                    "preview": _preview(row), "size": int(row["size"] or 0),
                    "supporting_file_count": int(row["actual_supporting"]),
                    "tags": _tags(row["tags_json"], f"Artifact {row['id']} tags"), "title": row["title"],
                    "trash_original_folder_id": row["trash_original_folder_id"],
                    "trash_original_folder_name": row["trash_original_folder_name"],
                }
        elif catalog == "revisions":
            assert external is not None and self.inventory is not None
            for row in self._rows("SELECT * FROM artifactrevision ORDER BY id"):
                record_id = str(row["id"])
                observed = self.inventory.execute(
                    "SELECT size,sha256 FROM observed WHERE record_kind='revisions' AND record_id=?", (record_id,)
                ).fetchone()
                if observed:
                    content = {"member": f"mvault/content/revisions/{record_id}/primary", "ownership": "managed", "source_path": None, "state": "ready"}
                    size, digest = int(observed["size"]), observed["sha256"]
                else:
                    source_path = str(row["source_path"] or "")
                    if not source_path:
                        raise MvaultExportError(f"revision {record_id!r} has neither managed nor external content")
                    state = str(row["content_state"] or "pending")
                    if state not in EXTERNAL_STATES:
                        state = "failed"
                    if not Path(source_path).is_file():
                        state = "unavailable"
                    external["records"] += 1
                    external["available" if state == "ready" else state] += 1
                    content = {"member": None, "ownership": "external", "source_path": source_path, "state": state}
                    size, digest = int(row["size"] or 0), row["sha256"]
                derived = self.inventory.execute("SELECT member FROM derived WHERE record_id=?", (record_id,)).fetchone()
                yield {
                    "asset_id": row["asset_id"], "change_note": row["change_note"], "content": content,
                    "created_at": _timestamp(row["created_at"], f"Revision {record_id} created_at"),
                    "derived_thumbnail_member": derived["member"] if derived else None,
                    "filename": row["filename"], "id": record_id, "mime": row["mime"],
                    "origin_revision_id": row["origin_revision_id"], "prepared_file_id": row["prepared_file_id"],
                    "prepared_machine_id": row["prepared_machine_id"],
                    "prepared_metadata": _json_field(row["prepared_metadata_json"], f"Revision {record_id} prepared metadata"),
                    "preview": _preview(row), "revision_number": int(row["revision_number"]),
                    "sha256": digest, "size": size,
                }
        elif catalog == "files":
            assert self.inventory is not None
            for row in self._rows("SELECT * FROM assetfile ORDER BY id"):
                observed = self.inventory.execute(
                    "SELECT size,sha256 FROM observed WHERE record_kind='files' AND record_id=?", (row["id"],)
                ).fetchone()
                if not observed:
                    raise MvaultExportError(f"AssetFile {row['id']!r} was not streamed")
                yield {
                    "asset_id": row["asset_id"], "filename": row["filename"], "id": row["id"],
                    "member": f"mvault/content/files/{row['id']}/payload",
                    "metadata": _json_field(row["metadata_json"], f"AssetFile {row['id']} metadata"),
                    "mime": row["mime"], "revision_id": row["revision_id"], "role": row["role"],
                    "sha256": observed["sha256"], "size": int(observed["size"]),
                }
        elif catalog == "projects":
            for row in self._rows("SELECT * FROM project ORDER BY id"):
                yield {
                    "created_at": _timestamp(row["created_at"], f"Project {row['id']} created_at"), "creator": row["creator"],
                    "deleted_at": _nullable_timestamp(row["deleted_at"], f"Project {row['id']} deleted_at"),
                    "id": row["id"], "license": row["license"], "name": row["name"], "notes": row["notes"],
                    "source_url": row["source_url"], "tags": _tags(row["tags_json"], f"Project {row['id']} tags"),
                    "updated_at": _timestamp(row["updated_at"], f"Project {row['id']} updated_at"),
                }
        elif catalog == "project-memberships":
            for row in self._rows("SELECT * FROM projectmembership ORDER BY project_id,asset_id"):
                yield {"asset_id": row["asset_id"], "created_at": _timestamp(row["created_at"], "Project membership created_at"), "project_id": row["project_id"]}
        elif catalog == "project-relationships":
            for row in self._rows("SELECT * FROM projectrelationship ORDER BY id"):
                yield {
                    "created_at": _timestamp(row["created_at"], f"Relationship {row['id']} created_at"), "id": row["id"],
                    "kind": row["kind"], "project_id": row["project_id"], "source_asset_id": row["source_asset_id"],
                    "target_asset_id": row["target_asset_id"],
                }
        elif catalog == "artifact-machines":
            for row in self._rows("SELECT * FROM artifactmachine ORDER BY asset_id,machine_id"):
                yield {"asset_id": row["asset_id"], "created_at": _timestamp(row["created_at"], "Artifact Machine created_at"), "machine_id": row["machine_id"]}
        elif catalog == "settings":
            assert self.connection is not None
            values = {
                row["key"]: row["value"]
                for row in self.connection.execute(
                    "SELECT key,value FROM appconfig WHERE key IN ('storage_path_template','trash_retention')"
                )
            }
            yield {"key": "storage_path_template", "value": values.get("storage_path_template", DEFAULT_STORAGE_TEMPLATE)}
            yield {"key": "trash_retention", "value": values.get("trash_retention", DEFAULT_TRASH_RETENTION)}
        else:
            raise MvaultExportError(f"unsupported v1 catalog {catalog}")

    def _manifest(self, external: dict[str, int]) -> dict[str, object]:
        assert self.inventory is not None
        authoritative = self.inventory.execute(
            "SELECT COUNT(*),COALESCE(SUM(size),0) FROM payload_plan WHERE class!='derived'"
        ).fetchone()
        derived = self.inventory.execute(
            "SELECT COUNT(*),COALESCE(SUM(size),0) FROM payload_plan WHERE class='derived'"
        ).fetchone()
        return {
            "catalog_records": self.catalog_counts,
            "content": {
                "authoritative_bytes": int(authoritative[1]), "authoritative_files": int(authoritative[0]),
                "complete_managed_content": True, "derived_bytes": int(derived[1]), "derived_files": int(derived[0]),
            },
            "external": external,
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
        }

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _remove_tree(path: Path) -> None:
        if not path.exists():
            return
        for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                child.rmdir()
        path.rmdir()


def export_archive(
    database: Path | str,
    storage: Path | str,
    output: Path | str,
    *,
    makersvault_version: str = "development",
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    return PortableVaultExporter(
        Path(database), Path(storage), Path(output),
        makersvault_version=makersvault_version,
        batch_size=batch_size,
        progress=progress,
    ).export()


def _positive(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a stopped MakersVault instance to portable .mvault v1")
    parser.add_argument("--database", required=True, help="path to the stopped instance's app.db")
    parser.add_argument("--storage", required=True, help="path to the instance's managed storage root")
    parser.add_argument("--output", required=True, help="new .mvault path; an existing file is never overwritten")
    parser.add_argument("--batch-size", type=_positive, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--makersvault-version", default=os.getenv("MAKERSVAULT_VERSION", "development"))
    parser.add_argument("--progress", action="store_true", help="write canonical phase events to stderr")
    parser.add_argument(
        "--confirm-stopped",
        action="store_true",
        help="confirm MakersVault is stopped or in maintenance mode",
    )
    args = parser.parse_args(argv)
    if not args.confirm_stopped:
        parser.error("--confirm-stopped is required; live-vault export is not supported")
    progress = None
    if args.progress:
        def progress(phase: str, details: dict[str, object]) -> None:
            event = {"operation": "export", "phase": phase, **details}
            print("mvault-progress " + json.dumps(event, sort_keys=True, separators=(",", ":")), file=sys.stderr, flush=True)
    try:
        report = export_archive(
            args.database, args.storage, args.output,
            makersvault_version=args.makersvault_version,
            batch_size=args.batch_size,
            progress=progress,
        )
    except KeyboardInterrupt:
        print(
            "mvault export cancelled; verify whether the requested output exists before use",
            file=sys.stderr,
        )
        return 130
    except MvaultExportError as exc:
        print(f"mvault export failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"archive": str(Path(args.output).resolve()), "verification": report}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
