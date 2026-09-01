"""Disposable Gate 10E scale/semantic drill; never operates on a user vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import resource
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path


API_ROOT = Path(__file__).parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

NOW = "2026-08-31T12:00:00Z"
CHUNK_BYTES = 1024 * 1024


def _peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _worker(args: argparse.Namespace) -> int:
    started = time.monotonic()
    if args.worker == "export":
        from mvault_export import export_archive

        result = export_archive(
            args.database,
            args.storage,
            args.archive,
            makersvault_version="5.1.0-gate10e",
            batch_size=args.batch_size,
        )
    elif args.worker == "verify":
        from mvault_verify import verify_archive

        result = verify_archive(args.archive)
    elif args.worker == "import":
        from mvault_import import import_archive

        result = import_archive(
            args.archive,
            args.database,
            args.storage,
            batch_size=args.batch_size,
        )
    else:
        raise ValueError(f"unsupported worker {args.worker!r}")
    print(json.dumps({
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "peak_rss_bytes": _peak_rss_bytes(),
        "result": result,
    }, sort_keys=True, separators=(",", ":")))
    return 0


def _write(path: Path, data: bytes) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data), hashlib.sha256(data).hexdigest()


def _large_payload(path: Path, mebibytes: int) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    rng = random.Random(510)
    remaining = mebibytes * CHUNK_BYTES
    with path.open("wb") as output:
        while remaining:
            block = rng.randbytes(min(CHUNK_BYTES, remaining))
            output.write(block)
            digest.update(block)
            remaining -= len(block)
    return mebibytes * CHUNK_BYTES, digest.hexdigest()


def _expand_fixture(database: Path, storage: Path, artifact_count: int, large_mib: int) -> None:
    from test_mvault_export import fixture_database

    created_database, created_storage = fixture_database(database.parent)
    assert created_database == database and created_storage == storage
    connection = sqlite3.connect(database)
    prepared_metadata = json.dumps({"filament": "PLA", "nozzle_mm": 0.4}, sort_keys=True, separators=(",", ":"))
    try:
        large_size, large_digest = _large_payload(storage / "revisions/a1/r1/model.stl", large_mib)
        connection.execute(
            "UPDATE artifactrevision SET size=?,sha256=? WHERE id='r1'",
            (large_size, large_digest),
        )

        folders = (artifact_count + 24) // 25
        for number in range(1, folders + 1):
            connection.execute(
                "INSERT INTO folder(id,name,tags_json,parent_id) VALUES (?,?,?,?)",
                (f"sf{number:04d}", f"Scale Folder {number:04d}", '["scale"]', "f1"),
            )
        projects = (artifact_count + 39) // 40
        for number in range(2, projects + 1):
            connection.execute(
                """INSERT INTO project(id,name,notes,creator,source_url,license,tags_json,created_at,updated_at,deleted_at)
                   VALUES (?,?,?,?,?,?,?,?,?,NULL)""",
                (f"p{number}", f"Scale Project {number:04d}", None, "Gate 10E", None, None, '["scale"]', NOW, NOW),
            )

        previous_by_project: dict[str, str] = {"p1": "a1"}
        for number in range(2, artifact_count + 1):
            token = f"{number:06d}"
            asset_id = f"sa{token}"
            revision_one = f"sr{token}a"
            revision_two = f"sr{token}b"
            file_id = f"sf{token}p"
            folder_number = ((number - 1) // 25) + 1
            folder_id = f"sf{folder_number:04d}"
            folder_name = f"Scale Folder {folder_number:04d}"
            project_id = f"p{((number - 1) // 40) + 1}"
            is_external = number % 10 == 0
            is_trashed = number % 20 == 0

            r1_key = f"revisions/{asset_id}/{revision_one}/model.stl"
            r1_size, r1_digest = _write(storage / r1_key, f"solid historical {asset_id}\n".encode())
            r2_key = None if is_external else f"revisions/{asset_id}/{revision_two}/model.3mf"
            if r2_key is None:
                r2_size, r2_digest = 4096 + number, None
                source_path = f"/offline/scale/{asset_id}.3mf"
            else:
                r2_size, r2_digest = _write(storage / r2_key, f"3MF current {asset_id}\n".encode())
                source_path = None
            file_key = f"bundles/{asset_id}/{file_id}/print.gcode"
            file_size, _ = _write(storage / file_key, f"; prepared {asset_id}\n".encode())
            thumb_key = None
            if number % 4 == 0:
                thumb_key = f"thumbs/revisions/{revision_one}.jpg"
                _write(storage / thumb_key, f"jpeg-{asset_id}".encode())

            connection.execute(
                """INSERT INTO asset(
                  id,name,filename,mime,size,tags_json,title,notes,creator,collection,folder_id,
                  source_path,storage_path,supporting_file_count,prepared_file_id,prepared_metadata_json,
                  prepared_machine_id,preview_status,preview_reason,preview_attempts,preview_policy_version,
                  preview_updated_at,preview_source,current_revision_id,current_thumb_path,deleted_at,
                  trash_original_folder_id,trash_original_folder_name
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    asset_id, f"Scale Model {token}", f"model-{token}.3mf", "model/3mf", r2_size,
                    '["mixed","scale"]', f"Scale Model {token}", "Gate 10E mixed fixture", "Gate 10E",
                    "Scale", None if is_trashed else folder_id, source_path, r2_key, 0, file_id,
                    prepared_metadata, "m1", "ready", None, 0, 1, NOW, "primary", revision_two, None,
                    NOW if is_trashed else None, folder_id if is_trashed else None,
                    folder_name if is_trashed else None,
                ),
            )
            connection.execute(
                """INSERT INTO artifactrevision(
                  id,asset_id,revision_number,created_at,origin_revision_id,filename,mime,size,sha256,
                  observed_sha256,content_state,content_reason,content_checked_at,storage_path,source_path,
                  change_note,prepared_file_id,prepared_metadata_json,prepared_machine_id,preview_status,
                  preview_reason,preview_attempts,preview_policy_version,preview_updated_at,preview_source,
                  preview_thumb_path
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    revision_one, asset_id, 1, NOW, None, f"model-{token}.stl", "model/stl", r1_size,
                    r1_digest, r1_digest, "ready", None, NOW, r1_key, None, "Initial", None, None, None,
                    "ready", None, 0, 1, NOW, "primary", thumb_key,
                ),
            )
            connection.execute(
                """INSERT INTO artifactrevision(
                  id,asset_id,revision_number,created_at,origin_revision_id,filename,mime,size,sha256,
                  observed_sha256,content_state,content_reason,content_checked_at,storage_path,source_path,
                  change_note,prepared_file_id,prepared_metadata_json,prepared_machine_id,preview_status,
                  preview_reason,preview_attempts,preview_policy_version,preview_updated_at,preview_source,
                  preview_thumb_path
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    revision_two, asset_id, 2, NOW, revision_one, f"model-{token}.3mf", "model/3mf", r2_size,
                    r2_digest, r2_digest, "ready" if not is_external else "unavailable",
                    None if not is_external else "fixture_offline", NOW, r2_key, source_path, "Current",
                    file_id, prepared_metadata, "m1", "ready", None, 0, 1, NOW, "primary",
                ),
            )
            connection.execute(
                """INSERT INTO assetfile(id,asset_id,filename,mime,size,role,storage_path,metadata_json,revision_id)
                   VALUES (?,?,?,?,?,'prepared',?,?,?)""",
                (file_id, asset_id, f"print-{token}.gcode", "text/x.gcode", file_size, file_key, '{"format":"gcode"}', revision_two),
            )
            connection.execute(
                "INSERT INTO projectmembership(project_id,asset_id,created_at) VALUES (?,?,?)",
                (project_id, asset_id, NOW),
            )
            previous = previous_by_project.get(project_id)
            if previous is not None:
                connection.execute(
                    """INSERT INTO projectrelationship(id,project_id,source_asset_id,target_asset_id,kind,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (f"rel-{asset_id}", project_id, previous, asset_id, "component_of", NOW),
                )
            previous_by_project[project_id] = asset_id
            connection.execute(
                "INSERT INTO artifactmachine(asset_id,machine_id,created_at) VALUES (?, 'm1', ?)",
                (asset_id, NOW),
            )
        connection.commit()
    finally:
        connection.close()


def _run_worker(phase: str, *, archive: Path, database: Path, storage: Path, batch_size: int) -> dict[str, object]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker", phase,
        "--archive", str(archive),
        "--database", str(database),
        "--storage", str(storage),
        "--batch-size", str(batch_size),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{phase} worker failed: {result.stderr or result.stdout}")
    return json.loads(result.stdout)


def _portable_digests(archive_path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with tarfile.open(archive_path, "r|gz") as archive:
        for member in archive:
            if not (
                member.name.startswith("mvault/catalogs/")
                or member.name.startswith("mvault/content/")
                or member.name.startswith("mvault/derived/")
            ):
                continue
            source = archive.extractfile(member)
            assert source is not None
            digest = hashlib.sha256()
            while True:
                chunk = source.read(CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
            result[member.name] = digest.hexdigest()
    return result


def _drill(args: argparse.Namespace) -> int:
    if args.artifacts < 2 or args.large_payload_mib < 1 or args.max_rss_mib < 1:
        raise ValueError("artifacts must be >=2 and size/memory limits must be positive")
    with tempfile.TemporaryDirectory(prefix="mvault-gate10e-") as temporary:
        root = Path(temporary)
        source = root / "source"
        source.mkdir()
        database = source / "app.db"
        storage = source / "storage"
        _expand_fixture(database, storage, args.artifacts, args.large_payload_mib)

        archive = root / "source.mvault"
        export = _run_worker("export", archive=archive, database=database, storage=storage, batch_size=args.batch_size)
        verify = _run_worker("verify", archive=archive, database=database, storage=storage, batch_size=args.batch_size)

        restored = root / "restored"
        restored_database = restored / "app.db"
        restored_storage = restored / "storage"
        imported = _run_worker(
            "import", archive=archive, database=restored_database,
            storage=restored_storage, batch_size=args.batch_size,
        )
        restored_archive = root / "restored.mvault"
        reexport = _run_worker(
            "export", archive=restored_archive, database=restored_database,
            storage=restored_storage, batch_size=args.batch_size,
        )

        source_digests = _portable_digests(archive)
        restored_digests = _portable_digests(restored_archive)
        if source_digests != restored_digests:
            missing = sorted(set(source_digests) ^ set(restored_digests))[:10]
            changed = sorted(
                name for name in set(source_digests) & set(restored_digests)
                if source_digests[name] != restored_digests[name]
            )[:10]
            raise RuntimeError(f"portable semantic/byte mismatch; missing={missing}, changed={changed}")

        phases = {"export": export, "verify": verify, "import": imported, "reexport": reexport}
        rss_limit = args.max_rss_mib * CHUNK_BYTES
        over_limit = {
            phase: value["peak_rss_bytes"]
            for phase, value in phases.items()
            if int(value["peak_rss_bytes"]) > rss_limit
        }
        if over_limit:
            raise RuntimeError(f"worker RSS exceeded {args.max_rss_mib} MiB: {over_limit}")

        verification = verify["result"]
        report = {
            "artifacts": args.artifacts,
            "batch_size": args.batch_size,
            "external_records": verification["external"]["records"],
            "large_payload_bytes": args.large_payload_mib * CHUNK_BYTES,
            "logical_catalog_records": sum(verification["catalog_records"].values()),
            "managed_bytes": verification["content"]["authoritative_bytes"],
            "managed_files": verification["content"]["authoritative_files"],
            "max_rss_bytes": rss_limit,
            "portable_members_compared": len(source_digests),
            "semantic_and_byte_equal": True,
            "workers": {
                phase: {
                    "elapsed_seconds": value["elapsed_seconds"],
                    "peak_rss_bytes": value["peak_rss_bytes"],
                }
                for phase, value in phases.items()
            },
        }
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the disposable Gate 10E portable-vault scale drill")
    parser.add_argument("--artifacts", type=int, default=1200)
    parser.add_argument("--large-payload-mib", type=int, default=64)
    parser.add_argument("--max-rss-mib", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=37)
    parser.add_argument("--worker", choices=("export", "verify", "import"))
    parser.add_argument("--archive")
    parser.add_argument("--database")
    parser.add_argument("--storage")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.worker:
        if not all((args.archive, args.database, args.storage)):
            raise ValueError("worker mode requires archive, database, and storage paths")
        args.archive = Path(args.archive)
        args.database = Path(args.database)
        args.storage = Path(args.storage)
        return _worker(args)
    return _drill(args)


if __name__ == "__main__":
    raise SystemExit(main())
