import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from mvault_verify import (
  CATALOGS,
  CHECKSUMS_PATH,
  HEADER_PATH,
  MANIFEST_PATH,
  MAX_HEADER_BYTES,
  MvaultVerificationError,
  VerificationLimits,
  verify_archive,
)


NOW = "2026-08-31T12:00:00Z"


def canonical(value):
  return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sample_records():
  preview = {"policy_version": 1, "reason": None, "source": "primary", "status": "ready"}
  return {
    "folders": [{"id": "folder-1", "name": "Fixtures", "parent_id": None, "tags": ["golden"]}],
    "machines": [{
      "archived_at": None, "category": "fdm_printer", "created_at": NOW, "id": "machine-1",
      "location": "Lab", "manufacturer": "Bambu Lab", "model": "P1S", "name": "P1S",
      "notes": None, "updated_at": NOW,
    }],
    "artifacts": [{
      "collection": "Calibration", "creator": "MakersVault", "current_revision_id": "rev-2",
      "deleted_at": None, "filename": "cube.3mf", "folder_id": "folder-1", "id": "asset-1",
      "mime": "model/3mf", "name": "Calibration Cube", "notes": "Golden fixture",
      "prepared_file_id": "file-1", "prepared_machine_id": "machine-1",
      "prepared_metadata": {"filament": "PLA", "nozzle_mm": 0.4, "print_time_seconds": 11520},
      "preview": preview, "size": 5, "supporting_file_count": 0, "tags": ["calibration", "cube"],
      "title": "Calibration Cube", "trash_original_folder_id": None, "trash_original_folder_name": None,
    }],
    "revisions": [
      {
        "asset_id": "asset-1", "change_note": "Initial", "content": {
          "member": "mvault/content/revisions/rev-1/primary", "ownership": "managed",
          "source_path": None, "state": "ready",
        }, "created_at": NOW, "derived_thumbnail_member": "mvault/derived/thumbnails/revisions/rev-1",
        "filename": "cube.stl", "id": "rev-1", "mime": "model/stl", "origin_revision_id": None,
        "prepared_file_id": "file-1", "prepared_machine_id": "machine-1", "prepared_metadata": {"format": "gcode"},
        "preview": preview, "revision_number": 1, "sha256": hashlib.sha256(b"solid").hexdigest(), "size": 5,
      },
      {
        "asset_id": "asset-1", "change_note": "External layout", "content": {
          "member": None, "ownership": "external", "source_path": "/media/models/cube.3mf", "state": "unavailable",
        }, "created_at": NOW, "derived_thumbnail_member": None, "filename": "cube.3mf", "id": "rev-2",
        "mime": "model/3mf", "origin_revision_id": "rev-1", "prepared_file_id": None,
        "prepared_machine_id": "machine-1", "prepared_metadata": {"plates": 2}, "preview": preview,
        "revision_number": 2, "sha256": None, "size": 1234,
      },
    ],
    "files": [{
      "asset_id": "asset-1", "filename": "print.gcode", "id": "file-1",
      "member": "mvault/content/files/file-1/payload", "metadata": {"format": "gcode"},
      "mime": "text/x.gcode", "revision_id": "rev-1", "role": "prepared",
      "sha256": hashlib.sha256(b"notes").hexdigest(), "size": 5,
    }],
    "projects": [{
      "created_at": NOW, "creator": "MakersVault", "deleted_at": None, "id": "project-1",
      "license": None, "name": "Fixture Project", "notes": None, "source_url": None,
      "tags": ["test"], "updated_at": NOW,
    }],
    "project-memberships": [{"asset_id": "asset-1", "created_at": NOW, "project_id": "project-1"}],
    "project-relationships": [],
    "artifact-machines": [{"asset_id": "asset-1", "created_at": NOW, "machine_id": "machine-1"}],
    "settings": [
      {"key": "storage_path_template", "value": "{folder}/{name}/{filename}"},
      {"key": "trash_retention", "value": "until_space_needed"},
    ],
  }


def archive_members(records=None, *, required_features=None):
  records = records or sample_records()
  header = {
    "catalogs": list(CATALOGS), "created_at": NOW, "format": "makersvault-portable-vault",
    "format_version": 1, "optional_features": ["derived-thumbnails"],
    "required_features": required_features or ["canonical-jsonl", "sha256-inventory"],
    "source": {"makersvault_version": "5.1.0", "schema_version": 12},
  }
  file_record = records["files"][0]
  managed_revision = next(record for record in records["revisions"] if record["content"]["ownership"] == "managed")
  members = [
    [HEADER_PATH, canonical(header), tarfile.REGTYPE],
    [file_record["member"], b"notes", tarfile.REGTYPE],
    [managed_revision["content"]["member"], b"solid", tarfile.REGTYPE],
    [managed_revision["derived_thumbnail_member"], b"png", tarfile.REGTYPE],
  ]
  for catalog in CATALOGS:
    def portable_key(record):
      if catalog == "project-memberships":
        return f"{record['project_id']}\x1f{record['asset_id']}"
      if catalog == "artifact-machines":
        return f"{record['asset_id']}\x1f{record['machine_id']}"
      return record.get("id", record.get("key"))
    body = b"".join(canonical(record) for record in sorted(records[catalog], key=portable_key))
    members.append([f"mvault/catalogs/{catalog}.jsonl", body, tarfile.REGTYPE])
  manifest = {
    "catalog_records": {name: len(records[name]) for name in CATALOGS},
    "content": {"authoritative_bytes": 10, "authoritative_files": 2, "complete_managed_content": True, "derived_bytes": 3, "derived_files": 1},
    "external": {"available": 0, "changed": 0, "failed": 0, "pending": 0, "records": 1, "unavailable": 1},
    "format": "makersvault-portable-vault", "format_version": 1,
  }
  members.append([MANIFEST_PATH, canonical(manifest), tarfile.REGTYPE])
  inventory = b"".join(f"{hashlib.sha256(body).hexdigest()}  {name}\n".encode() for name, body, _ in members)
  members.append([CHECKSUMS_PATH, inventory, tarfile.REGTYPE])
  return members


def write_archive(path, members):
  with path.open("wb") as output:
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
      with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
        for name, body, member_type in members:
          info = tarfile.TarInfo(name)
          info.size = len(body)
          info.type = member_type
          info.mtime = 0
          info.uid = info.gid = 0
          info.uname = info.gname = ""
          archive.addfile(info, io.BytesIO(body))
  return path


def test_golden_archive_is_deterministic_and_verifies(tmp_path):
  first = write_archive(tmp_path / "first.mvault", archive_members())
  second = write_archive(tmp_path / "second.mvault", archive_members())

  assert first.read_bytes() == second.read_bytes()
  assert hashlib.sha256(first.read_bytes()).hexdigest() == "1c2edb89454fd141237c36c649cd78362523dff0c6c52b851ab0eec327318d04"
  assert verify_archive(first) == {
    "catalog_records": {
      "artifact-machines": 1, "artifacts": 1, "files": 1, "folders": 1, "machines": 1,
      "project-memberships": 1, "project-relationships": 0, "projects": 1, "revisions": 2, "settings": 2,
    },
    "expanded_bytes": 5248,
    "format": "makersvault-portable-vault", "format_version": 1, "members": 16, "valid": True,
  }


def test_cli_emits_stable_report(tmp_path):
  archive = write_archive(tmp_path / "golden.mvault", archive_members())
  result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "mvault_verify.py"), str(archive)], capture_output=True, text=True)
  assert result.returncode == 0
  assert json.loads(result.stdout)["valid"] is True
  assert result.stderr == ""


def test_rejects_unknown_required_feature(tmp_path):
  archive = write_archive(tmp_path / "feature.mvault", archive_members(required_features=["canonical-jsonl", "future-feature", "sha256-inventory"]))
  with pytest.raises(MvaultVerificationError, match="unknown required feature"):
    verify_archive(archive)


def test_rejects_path_traversal(tmp_path):
  members = archive_members()
  members.insert(1, ["mvault/../escape", b"bad", tarfile.REGTYPE])
  archive = write_archive(tmp_path / "traversal.mvault", members)
  with pytest.raises(MvaultVerificationError, match="non-canonical member path"):
    verify_archive(archive)


def test_rejects_non_regular_member(tmp_path):
  members = archive_members()
  members[1][2] = tarfile.SYMTYPE
  archive = write_archive(tmp_path / "link.mvault", members)
  with pytest.raises(MvaultVerificationError, match="only regular-file"):
    verify_archive(archive)


def test_rejects_duplicate_member(tmp_path):
  members = archive_members()
  members.insert(2, list(members[1]))
  archive = write_archive(tmp_path / "duplicate.mvault", members)
  with pytest.raises(MvaultVerificationError, match="duplicate archive member"):
    verify_archive(archive)


def test_rejects_checksum_tampering(tmp_path):
  members = archive_members()
  members[-1][1] = b"0" * 64 + members[-1][1][64:]
  archive = write_archive(tmp_path / "checksum.mvault", members)
  with pytest.raises(MvaultVerificationError, match="checksum inventory mismatch"):
    verify_archive(archive)


def test_rejects_dangling_graph_reference(tmp_path):
  records = sample_records()
  records["project-memberships"][0]["asset_id"] = "missing-asset"
  archive = write_archive(tmp_path / "dangling.mvault", archive_members(records))
  with pytest.raises(MvaultVerificationError, match="dangling asset_id"):
    verify_archive(archive)


def test_rejects_unclaimed_payload(tmp_path):
  members = archive_members()
  members.insert(2, ["mvault/content/revisions/orphan/primary", b"orphan", tarfile.REGTYPE])
  archive = write_archive(tmp_path / "orphan.mvault", members)
  with pytest.raises(MvaultVerificationError, match="unclaimed payload"):
    verify_archive(archive)


def test_rejects_noncanonical_catalog_json(tmp_path):
  members = archive_members()
  catalog_index = next(index for index, member in enumerate(members) if member[0].endswith("folders.jsonl"))
  members[catalog_index][1] = b'{"name": "not canonical"}\n'
  archive = write_archive(tmp_path / "json.mvault", members)
  with pytest.raises(MvaultVerificationError, match="not canonical JSON"):
    verify_archive(archive)


def test_enforces_configured_resource_limits(tmp_path):
  archive = write_archive(tmp_path / "limited.mvault", archive_members())
  with pytest.raises(MvaultVerificationError, match="member limit"):
    verify_archive(archive, VerificationLimits(max_members=2, max_records=100, max_expanded_bytes=100_000))
  with pytest.raises(MvaultVerificationError, match="expanded-byte limit"):
    verify_archive(archive, VerificationLimits(max_members=100, max_records=100, max_expanded_bytes=10))
  with pytest.raises(MvaultVerificationError, match="catalog-record limit"):
    verify_archive(archive, VerificationLimits(max_members=100, max_records=1, max_expanded_bytes=100_000))


def test_rejects_truncated_archive(tmp_path):
  complete = write_archive(tmp_path / "complete.mvault", archive_members())
  truncated = tmp_path / "truncated.mvault"
  data = complete.read_bytes()
  truncated.write_bytes(data[: len(data) // 2])
  with pytest.raises(MvaultVerificationError, match="malformed|ended before|final checksum"):
    verify_archive(truncated)


def test_rejects_oversized_metadata_declaration(tmp_path):
  members = archive_members()
  members[0][1] = b" " * (MAX_HEADER_BYTES + 1)
  archive = write_archive(tmp_path / "oversized.mvault", members)
  with pytest.raises(MvaultVerificationError, match="header exceeds"):
    verify_archive(archive, VerificationLimits(max_expanded_bytes=10 * 1024 * 1024))


def test_accepts_bounded_pax_extension_for_long_stable_id(tmp_path):
  records = sample_records()
  long_id = "r" + "x" * 149
  records["revisions"][0]["id"] = long_id
  records["revisions"][0]["content"]["member"] = f"mvault/content/revisions/{long_id}/primary"
  records["revisions"][0]["derived_thumbnail_member"] = f"mvault/derived/thumbnails/revisions/{long_id}"
  records["revisions"][1]["origin_revision_id"] = long_id
  records["files"][0]["revision_id"] = long_id
  archive = write_archive(tmp_path / "pax.mvault", archive_members(records))
  assert verify_archive(archive)["valid"] is True
