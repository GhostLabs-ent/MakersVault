"""MakersVault backup manifest, integrity, and recovery helpers.

This module intentionally uses only the Python standard library so operators can
verify a backup without starting the MakersVault application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Optional


BACKUP_FORMAT = "makersvault-backup"
BACKUP_FORMAT_VERSION = 1
COMPONENT_NAMES = ("database.tar", "storage.tar")
OPTIONAL_NAMES = ("config.env",)
METADATA_NAMES = ("manifest.json", "checksums.sha256")


class RecoveryError(RuntimeError):
    pass


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_member_name(raw: str) -> str:
    if "\\" in raw:
        raise RecoveryError(f"Archive member uses a platform separator: {raw}")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise RecoveryError(f"Archive member escapes its root: {raw}")
    parts = [part for part in path.parts if part not in {"", "."}]
    return "/".join(parts)


def validate_component_tar(path: Path) -> list[dict]:
    if not path.is_file():
        raise RecoveryError(f"Backup component is missing: {path}")
    files: list[dict] = []
    seen: set[str] = set()
    try:
        archive = tarfile.open(path, "r:*")
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise RecoveryError(f"Backup component is not a readable tar archive: {path.name}") from exc
    try:
        with archive:
            for member in archive.getmembers():
                name = normalized_member_name(member.name)
                if not name:
                    continue
                if name in seen:
                    raise RecoveryError(f"Backup component contains a duplicate path: {name}")
                seen.add(name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise RecoveryError(f"Backup component contains a non-regular entry: {name}")
                source = archive.extractfile(member)
                if source is None:
                    raise RecoveryError(f"Backup component member is unreadable: {name}")
                digest = hashlib.sha256()
                with source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                files.append({
                    "path": name,
                    "size": int(member.size),
                    "sha256": digest.hexdigest(),
                })
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise RecoveryError(f"Backup component is unreadable: {path.name}") from exc
    files.sort(key=lambda item: item["path"])
    return files


def extract_regular_member(archive: tarfile.TarFile, member: tarfile.TarInfo, destination: Path) -> None:
    name = normalized_member_name(member.name)
    if not name or not member.isfile():
        return
    target = destination / Path(*PurePosixPath(name).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    source = archive.extractfile(member)
    if source is None:
        raise RecoveryError(f"Could not read archive member: {name}")
    with source, target.open("wb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)


def extract_database_component(path: Path, destination: Path) -> Path:
    members = validate_component_tar(path)
    app_db = [item for item in members if item["path"] == "app.db"]
    if len(app_db) != 1:
        raise RecoveryError("Database component must contain app.db at its root")
    with tarfile.open(path, "r:*") as archive:
        for member in archive.getmembers():
            extract_regular_member(archive, member, destination)
    return destination / "app.db"


def table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def database_summary(database: Path) -> dict:
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise RecoveryError("SQLite database could not be opened read-only") from exc
    try:
        quick_check_rows = connection.execute("PRAGMA quick_check").fetchall()
        quick_check = [str(row[0]) for row in quick_check_rows]
        tables = table_names(connection)
        schema_version = 0
        if "schema_migration" in tables:
            row = connection.execute("SELECT MAX(version) FROM schema_migration").fetchone()
            schema_version = int(row[0] or 0)
        counts = {}
        for table in ("folder", "asset", "assetfile", "appconfig", "mountscan"):
            counts[table] = (
                int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                if table in tables
                else 0
            )
        return {
            "quick_check": quick_check,
            "schema_version": schema_version,
            "tables": sorted(tables),
            "row_counts": counts,
        }
    except sqlite3.Error as exc:
        raise RecoveryError("SQLite integrity inspection failed") from exc
    finally:
        connection.close()


def _select_assets(connection: sqlite3.Connection) -> list[dict]:
    tables = table_names(connection)
    if "asset" not in tables:
        return []
    columns = table_columns(connection, "asset")
    wanted = [
        "id",
        "filename",
        "source_path",
        "storage_path",
        "prepared_file_id",
        "supporting_file_count",
    ]
    selected = [name for name in wanted if name in columns]
    rows = connection.execute(f"SELECT {', '.join(selected)} FROM asset").fetchall()
    return [dict(zip(selected, row)) for row in rows]


def _select_asset_files(connection: sqlite3.Connection) -> list[dict]:
    tables = table_names(connection)
    if "assetfile" not in tables:
        return []
    columns = table_columns(connection, "assetfile")
    wanted = ["id", "asset_id", "role", "storage_path"]
    selected = [name for name in wanted if name in columns]
    rows = connection.execute(f"SELECT {', '.join(selected)} FROM assetfile").fetchall()
    return [dict(zip(selected, row)) for row in rows]


def _external_state(
    source_path: str,
    container_root: Optional[Path],
    host_root: Optional[Path],
) -> str:
    if not container_root or not host_root:
        return "unknown"
    source = PurePosixPath(source_path)
    root = PurePosixPath(container_root.as_posix())
    try:
        relative = source.relative_to(root)
    except ValueError:
        return "outside_mapping"
    return "available" if (host_root / Path(*relative.parts)).is_file() else "unavailable"


def consistency_audit(
    database: Path,
    storage_files: Iterable[str],
    external_container_root: Optional[Path] = None,
    external_host_root: Optional[Path] = None,
) -> dict:
    storage: set[str] = set()
    for name in storage_files:
        normalized = normalized_member_name(name)
        if normalized:
            storage.add(normalized)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        assets = _select_assets(connection)
        asset_files = _select_asset_files(connection)
    finally:
        connection.close()

    referenced: set[str] = set()
    managed_present = 0
    missing_managed: list[str] = []
    external: list[dict[str, str]] = []
    for asset in assets:
        asset_id = str(asset.get("id") or "")
        filename = str(asset.get("filename") or "")
        managed = str(asset.get("storage_path") or f"{asset_id}/{filename}")
        managed = normalized_member_name(managed)
        if managed in storage:
            referenced.add(managed)
            managed_present += 1
        elif asset.get("source_path"):
            source_path = str(asset["source_path"])
            external.append({
                "asset_id": asset_id,
                "source_path": source_path,
                "state": _external_state(
                    source_path,
                    external_container_root,
                    external_host_root,
                ),
            })
        else:
            missing_managed.append(asset_id)

    related_ids = {str(row.get("id") or "") for row in asset_files}
    related_missing: list[str] = []
    for row in asset_files:
        storage_path = normalized_member_name(str(row.get("storage_path") or ""))
        if storage_path in storage:
            referenced.add(storage_path)
        else:
            related_missing.append(str(row.get("id") or ""))

    prepared_pointer_missing = [
        str(asset.get("id") or "")
        for asset in assets
        if asset.get("prepared_file_id") and str(asset["prepared_file_id"]) not in related_ids
    ]
    external_counts = {
        state: sum(1 for item in external if item["state"] == state)
        for state in ("available", "unavailable", "unknown", "outside_mapping")
    }
    orphans = sorted(
        name
        for name in storage
        if name not in referenced and not name.startswith("thumbs/")
    )
    critical_count = len(missing_managed) + len(related_missing) + len(prepared_pointer_missing)
    return {
        "status": "ok" if critical_count == 0 else "inconsistent",
        "managed_primary_present": managed_present,
        "missing_managed_asset_ids": sorted(missing_managed),
        "external_primary_records": sorted(external, key=lambda item: item["asset_id"]),
        "external_state_counts": external_counts,
        "related_file_present": len(asset_files) - len(related_missing),
        "missing_related_file_ids": sorted(related_missing),
        "missing_prepared_pointer_asset_ids": sorted(prepared_pointer_missing),
        "unreferenced_storage_files": orphans,
        "derived_thumbnail_files": sum(1 for name in storage if name.startswith("thumbs/")),
    }


def _component_metadata(path: Path, members: list[dict]) -> dict:
    return {
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "file_count": len(members),
        "expanded_bytes": sum(int(item["size"]) for item in members),
        "files": members,
    }


def add_path_to_tar(archive: tarfile.TarFile, source: Path, name: str, mode: int = 0o600) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = source.stat().st_size
    info.mode = mode
    info.mtime = int(datetime.now(timezone.utc).timestamp())
    with source.open("rb") as handle:
        archive.addfile(info, handle)


def add_bytes_to_tar(archive: tarfile.TarFile, data: bytes, name: str, mode: int = 0o600) -> None:
    import io

    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mode = mode
    info.mtime = int(datetime.now(timezone.utc).timestamp())
    archive.addfile(info, io.BytesIO(data))


def create_backup(
    database_tar: Path,
    storage_tar: Path,
    output: Path,
    release: str,
    source_revision: str,
    config_env: Optional[Path] = None,
    overwrite: bool = False,
) -> dict:
    if output.exists() and not overwrite:
        raise RecoveryError(f"Backup already exists: {output}")
    database_members = validate_component_tar(database_tar)
    storage_members = validate_component_tar(storage_tar)
    with tempfile.TemporaryDirectory(prefix="makersvault-backup-") as temporary:
        database = extract_database_component(database_tar, Path(temporary) / "database")
        summary = database_summary(database)
        if summary["quick_check"] != ["ok"]:
            raise RecoveryError("SQLite quick_check did not return ok")
        audit = consistency_audit(
            database,
            [item["path"] for item in storage_members],
        )
        components = {
            "database.tar": _component_metadata(database_tar, database_members),
            "storage.tar": _component_metadata(storage_tar, storage_members),
        }
        checksum_lines = [
            f"{components[name]['sha256']}  {name}"
            for name in COMPONENT_NAMES
        ]
        if config_env:
            if not config_env.is_file():
                raise RecoveryError(f"Configuration file does not exist: {config_env}")
            components["config.env"] = {
                "sha256": sha256_file(config_env),
                "bytes": config_env.stat().st_size,
            }
            checksum_lines.append(f"{components['config.env']['sha256']}  config.env")
        manifest = {
            "format": BACKUP_FORMAT,
            "format_version": BACKUP_FORMAT_VERSION,
            "created_at": utc_timestamp(),
            "release": release,
            "source_revision": source_revision,
            "components": components,
            "database": summary,
            "consistency": audit,
            "external_content_included": False,
        }
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        checksum_lines.append(
            f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json"
        )
        checksums_bytes = ("\n".join(checksum_lines) + "\n").encode()
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
        os.close(fd)
        temporary_output = Path(temporary_name)
        try:
            with tarfile.open(temporary_output, "w:gz") as archive:
                add_bytes_to_tar(archive, manifest_bytes, "manifest.json", 0o600)
                add_bytes_to_tar(archive, checksums_bytes, "checksums.sha256", 0o600)
                add_path_to_tar(archive, database_tar, "database.tar", 0o600)
                add_path_to_tar(archive, storage_tar, "storage.tar", 0o600)
                if config_env:
                    add_path_to_tar(archive, config_env, "config.env", 0o600)
            os.chmod(temporary_output, stat.S_IRUSR | stat.S_IWUSR)
            temporary_output.replace(output)
        finally:
            temporary_output.unlink(missing_ok=True)
    return manifest


def extract_outer_archive(archive_path: Path, destination: Path) -> set[str]:
    destination.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    try:
        archive = tarfile.open(archive_path, "r:gz")
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise RecoveryError("Backup is not a readable gzip tar archive") from exc
    try:
        with archive:
            for member in archive.getmembers():
                name = normalized_member_name(member.name)
                if not name or name in seen:
                    raise RecoveryError("Backup contains an empty or duplicate member")
                if "/" in name or not member.isfile():
                    raise RecoveryError(f"Backup contains an unexpected member: {name}")
                if name not in set(COMPONENT_NAMES + OPTIONAL_NAMES + METADATA_NAMES):
                    raise RecoveryError(f"Backup contains an unknown member: {name}")
                seen.add(name)
                extract_regular_member(archive, member, destination)
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise RecoveryError("Backup archive is unreadable") from exc
    required = set(COMPONENT_NAMES + METADATA_NAMES)
    if not required.issubset(seen):
        raise RecoveryError("Backup is missing one or more required members")
    return seen


def parse_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RecoveryError("Backup checksum inventory is malformed")
        if name in checksums:
            raise RecoveryError("Backup checksum inventory contains a duplicate")
        checksums[name] = digest
    return checksums


def verify_extracted_backup(directory: Path, seen: set[str]) -> dict:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryError("Backup manifest is not valid JSON") from exc
    if manifest.get("format") != BACKUP_FORMAT or manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise RecoveryError("Backup format or version is unsupported")
    checksums = parse_checksums(directory / "checksums.sha256")
    expected_components = set(COMPONENT_NAMES)
    if "config.env" in seen:
        expected_components.add("config.env")
    expected_checksums = expected_components | {"manifest.json"}
    if set(checksums) != expected_checksums:
        raise RecoveryError("Backup checksum inventory does not match its components")
    if checksums["manifest.json"] != sha256_file(directory / "manifest.json"):
        raise RecoveryError("Backup manifest checksum failed")
    manifest_components = manifest.get("components")
    if not isinstance(manifest_components, dict) or set(manifest_components) != expected_components:
        raise RecoveryError("Backup manifest component inventory does not match its archive")
    for name in sorted(expected_components):
        actual = sha256_file(directory / name)
        if checksums[name] != actual or manifest_components[name].get("sha256") != actual:
            raise RecoveryError(f"Backup component checksum failed: {name}")
    database_members = validate_component_tar(directory / "database.tar")
    storage_members = validate_component_tar(directory / "storage.tar")
    with tempfile.TemporaryDirectory(prefix="makersvault-verify-") as temporary:
        database = extract_database_component(directory / "database.tar", Path(temporary) / "database")
        summary = database_summary(database)
        audit = consistency_audit(database, [item["path"] for item in storage_members])
    if summary["quick_check"] != ["ok"]:
        raise RecoveryError("Restored SQLite quick_check did not return ok")
    if manifest.get("database") != summary:
        raise RecoveryError("Backup database summary does not match its manifest")
    if manifest.get("consistency") != audit:
        raise RecoveryError("Backup consistency report does not match its contents")
    if manifest_components["database.tar"].get("file_count") != len(database_members):
        raise RecoveryError("Database component file count does not match its manifest")
    if manifest_components["storage.tar"].get("file_count") != len(storage_members):
        raise RecoveryError("Storage component file count does not match its manifest")
    if manifest_components["database.tar"].get("files") != database_members:
        raise RecoveryError("Database file inventory does not match its manifest")
    if manifest_components["storage.tar"].get("files") != storage_members:
        raise RecoveryError("Storage file inventory does not match its manifest")
    return manifest


def verify_backup(archive_path: Path) -> dict:
    if not archive_path.is_file():
        raise RecoveryError(f"Backup does not exist: {archive_path}")
    with tempfile.TemporaryDirectory(prefix="makersvault-verify-") as temporary:
        directory = Path(temporary)
        seen = extract_outer_archive(archive_path, directory)
        return verify_extracted_backup(directory, seen)


def extract_backup(archive_path: Path, output_dir: Path) -> dict:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RecoveryError("Backup extraction target must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    seen = extract_outer_archive(archive_path, output_dir)
    try:
        return verify_extracted_backup(output_dir, seen)
    except Exception:
        for child in output_dir.iterdir():
            child.unlink(missing_ok=True)
        raise


def storage_files_from_directory(storage_dir: Path) -> list[str]:
    files: list[str] = []
    for path in storage_dir.rglob("*"):
        if path.is_symlink():
            raise RecoveryError(f"Storage contains a symbolic link: {path}")
        if path.is_file():
            files.append(path.relative_to(storage_dir).as_posix())
    return sorted(files)


def audit_live_paths(
    database: Path,
    storage_dir: Path,
    external_container_root: Optional[Path] = None,
    external_host_root: Optional[Path] = None,
) -> dict:
    summary = database_summary(database)
    audit = consistency_audit(
        database,
        storage_files_from_directory(storage_dir),
        external_container_root,
        external_host_root,
    )
    return {"database": summary, "consistency": audit}


def audit_component_tars(database_tar: Path, storage_tar: Path) -> dict:
    """Audit a matched database/storage snapshot without running an app image."""
    storage_members = validate_component_tar(storage_tar)
    with tempfile.TemporaryDirectory(prefix="makersvault-audit-") as temporary:
        database = extract_database_component(database_tar, Path(temporary) / "database")
        summary = database_summary(database)
        audit = consistency_audit(database, [item["path"] for item in storage_members])
    return {"database": summary, "consistency": audit}


def verify_restored_components(
    archive_path: Path,
    database_tar: Path,
    storage_tar: Path,
) -> dict:
    """Prove a live post-restore snapshot matches every archived file byte."""
    manifest = verify_backup(archive_path)
    live_members = {
        "database.tar": validate_component_tar(database_tar),
        "storage.tar": validate_component_tar(storage_tar),
    }
    for name, members in live_members.items():
        if manifest["components"][name].get("files") != members:
            raise RecoveryError(f"Restored {name} content does not match the backup")
    result = audit_component_tars(database_tar, storage_tar)
    return {"matches_backup": True, **result}


def print_json(value: dict) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create, verify, extract, or audit a MakersVault backup")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--database-tar", type=Path, required=True)
    create.add_argument("--storage-tar", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--release", required=True)
    create.add_argument("--source-revision", required=True)
    create.add_argument("--config-env", type=Path)
    create.add_argument("--overwrite", action="store_true")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)

    extract = subparsers.add_parser("extract")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--database", type=Path, required=True)
    audit.add_argument("--storage-dir", type=Path, required=True)
    audit.add_argument("--external-container-root", type=Path)
    audit.add_argument("--external-host-root", type=Path)

    audit_components = subparsers.add_parser("audit-components")
    audit_components.add_argument("--database-tar", type=Path, required=True)
    audit_components.add_argument("--storage-tar", type=Path, required=True)

    verify_restored = subparsers.add_parser("verify-restored")
    verify_restored.add_argument("--archive", type=Path, required=True)
    verify_restored.add_argument("--database-tar", type=Path, required=True)
    verify_restored.add_argument("--storage-tar", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "create":
            result = create_backup(
                args.database_tar,
                args.storage_tar,
                args.output,
                args.release,
                args.source_revision,
                args.config_env,
                args.overwrite,
            )
        elif args.command == "verify":
            result = verify_backup(args.archive)
        elif args.command == "extract":
            result = extract_backup(args.archive, args.output_dir)
        elif args.command == "audit":
            result = audit_live_paths(
                args.database,
                args.storage_dir,
                args.external_container_root,
                args.external_host_root,
            )
        elif args.command == "audit-components":
            result = audit_component_tars(args.database_tar, args.storage_tar)
        else:
            result = verify_restored_components(
                args.archive,
                args.database_tar,
                args.storage_tar,
            )
        print_json(result)
        if args.command in {"audit", "audit-components", "verify-restored"} and (
            result["database"]["quick_check"] != ["ok"]
            or result["consistency"]["status"] != "ok"
        ):
            return 3
        return 0
    except RecoveryError as exc:
        print(f"Recovery error: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
