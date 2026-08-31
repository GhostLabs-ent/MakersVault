"""Independent, standard-library verifier for MakersVault portable vault v1.

This module deliberately has no imports from the MakersVault application.  It may
be copied next to an archive and run with the Python standard library alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import posixpath
import re
import sqlite3
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable, Iterator


FORMAT = "makersvault-portable-vault"
FORMAT_VERSION = 1
HEADER_PATH = "mvault/header.json"
MANIFEST_PATH = "mvault/manifest.json"
CHECKSUMS_PATH = "mvault/checksums.sha256"
REQUIRED_FEATURES = ("canonical-jsonl", "sha256-inventory")
KNOWN_OPTIONAL_FEATURES = ("derived-thumbnails",)
CATALOGS = (
  "folders",
  "machines",
  "artifacts",
  "revisions",
  "files",
  "projects",
  "project-memberships",
  "project-relationships",
  "artifact-machines",
  "settings",
)
CATALOG_PATHS = tuple(f"mvault/catalogs/{name}.jsonl" for name in CATALOGS)

MAX_HEADER_BYTES = 1 * 1024 * 1024
MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_CHECKSUM_LINE_BYTES = 4096
MAX_JSONL_LINE_BYTES = 4 * 1024 * 1024
MAX_PAX_HEADER_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_MEMBERS = 1_000_000
DEFAULT_MAX_RECORDS = 5_000_000
DEFAULT_MAX_EXPANDED_BYTES = 16 * 1024**4

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_RE = re.compile(
  r"^mvault/content/(?P<kind>revisions|files)/(?P<id>[A-Za-z0-9][A-Za-z0-9._:-]{0,254})/(?P<leaf>primary|payload)$"
)
_DERIVED_RE = re.compile(
  r"^mvault/derived/thumbnails/revisions/(?P<id>[A-Za-z0-9][A-Za-z0-9._:-]{0,254})$"
)


class MvaultVerificationError(ValueError):
  """The archive is not a valid MakersVault portable vault v1."""


class _BoundedTarInfo(tarfile.TarInfo):
  """Bound stdlib tar extension records before tarfile buffers them."""

  @staticmethod
  def _charge_extension(archive: tarfile.TarFile, size: int) -> None:
    extension_members = getattr(archive, "_mvault_extension_members", 0) + 1
    extension_bytes = getattr(archive, "_mvault_extension_bytes", 0) + size
    if extension_members + getattr(archive, "_mvault_semantic_members", 0) > getattr(archive, "_mvault_max_members", DEFAULT_MAX_MEMBERS):
      _fail("archive exceeds the configured member limit")
    if extension_bytes + getattr(archive, "_mvault_semantic_bytes", 0) > getattr(archive, "_mvault_max_expanded_bytes", DEFAULT_MAX_EXPANDED_BYTES):
      _fail("archive exceeds the configured expanded-byte limit")
    archive._mvault_extension_members = extension_members
    archive._mvault_extension_bytes = extension_bytes

  def _proc_pax(self, archive: tarfile.TarFile) -> tarfile.TarInfo:
    if self.size > MAX_PAX_HEADER_BYTES:
      _fail(f"PAX extension header exceeds {MAX_PAX_HEADER_BYTES} bytes")
    self._charge_extension(archive, self.size)
    return super()._proc_pax(archive)

  def _proc_gnulong(self, archive: tarfile.TarFile) -> tarfile.TarInfo:
    _fail("GNU long-name/link extensions are not permitted; use POSIX PAX")


@dataclass(frozen=True)
class VerificationLimits:
  max_members: int = DEFAULT_MAX_MEMBERS
  max_records: int = DEFAULT_MAX_RECORDS
  max_expanded_bytes: int = DEFAULT_MAX_EXPANDED_BYTES

  def validate(self) -> None:
    if self.max_members < 1 or self.max_records < 1 or self.max_expanded_bytes < 1:
      raise ValueError("verification limits must be positive integers")


def _fail(message: str) -> None:
  raise MvaultVerificationError(message)


def _pairs_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
  result: dict[str, object] = {}
  for key, value in pairs:
    if key in result:
      _fail(f"duplicate JSON key: {key!r}")
    result[key] = value
  return result


def _reject_constant(value: str) -> object:
  _fail(f"non-finite JSON value is forbidden: {value}")


def _json_loads(data: bytes, context: str) -> object:
  try:
    value = json.loads(
      data.decode("utf-8"),
      object_pairs_hook=_pairs_no_duplicates,
      parse_constant=_reject_constant,
    )
  except MvaultVerificationError:
    raise
  except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
    _fail(f"{context} is not valid UTF-8 JSON: {exc}")
  def finite(item: object) -> bool:
    if isinstance(item, float):
      return math.isfinite(item)
    if isinstance(item, dict):
      return all(finite(child) for child in item.values())
    if isinstance(item, list):
      return all(finite(child) for child in item)
    return True
  if not finite(value):
    _fail(f"{context} contains a non-finite number")
  return value


def _canonical_json(value: object) -> bytes:
  try:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
  except (TypeError, ValueError, RecursionError) as exc:
    _fail(f"JSON value cannot be canonically encoded: {exc}")


def _expect_canonical(data: bytes, value: object, context: str) -> None:
  if data != _canonical_json(value):
    _fail(f"{context} is not canonical JSON")


def _object(value: object, context: str) -> dict[str, object]:
  if not isinstance(value, dict):
    _fail(f"{context} must be a JSON object")
  return value


def _exact_keys(value: dict[str, object], required: set[str], optional: set[str], context: str) -> None:
  missing = required - value.keys()
  unknown = value.keys() - required - optional
  if missing:
    _fail(f"{context} is missing fields: {', '.join(sorted(missing))}")
  if unknown:
    _fail(f"{context} has unknown fields: {', '.join(sorted(unknown))}")


def _string(value: object, context: str, *, empty: bool = True) -> str:
  if not isinstance(value, str) or (not empty and not value):
    _fail(f"{context} must be a string" + ("" if empty else " and may not be empty"))
  return value


def _nullable_string(value: object, context: str) -> str | None:
  if value is None:
    return None
  return _string(value, context)


def _integer(value: object, context: str, *, minimum: int = 0) -> int:
  if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
    _fail(f"{context} must be an integer >= {minimum}")
  return value


def _boolean(value: object, context: str) -> bool:
  if not isinstance(value, bool):
    _fail(f"{context} must be a boolean")
  return value


def _identifier(value: object, context: str) -> str:
  result = _string(value, context, empty=False)
  if not _ID_RE.fullmatch(result):
    _fail(f"{context} is not a portable identifier")
  return result


def _nullable_identifier(value: object, context: str) -> str | None:
  if value is None:
    return None
  return _identifier(value, context)


def _sha256(value: object, context: str) -> str:
  result = _string(value, context)
  if not _SHA256_RE.fullmatch(result):
    _fail(f"{context} must be a lowercase SHA-256 digest")
  return result


def _timestamp(value: object, context: str) -> str:
  result = _string(value, context, empty=False)
  if not result.endswith("Z"):
    _fail(f"{context} must be a UTC timestamp ending in Z")
  try:
    datetime.fromisoformat(result[:-1] + "+00:00")
  except ValueError:
    _fail(f"{context} must be an ISO-8601 UTC timestamp")
  return result


def _nullable_timestamp(value: object, context: str) -> str | None:
  if value is None:
    return None
  return _timestamp(value, context)


def _string_array(value: object, context: str) -> list[str]:
  if not isinstance(value, list):
    _fail(f"{context} must be an array")
  result = [_string(item, f"{context}[{index}]") for index, item in enumerate(value)]
  if result != sorted(set(result)):
    _fail(f"{context} must be sorted and contain no duplicates")
  return result


def _metadata(value: object, context: str) -> object:
  if value is not None and not isinstance(value, (dict, list, str, int, float, bool)):
    _fail(f"{context} must be JSON or null")
  return value


def _member_name(name: str) -> None:
  if not name or "\\" in name or name.startswith("/") or "\x00" in name:
    _fail(f"unsafe member path: {name!r}")
  if posixpath.normpath(name) != name or any(part in ("", ".", "..") for part in name.split("/")):
    _fail(f"non-canonical member path: {name!r}")
  if not name.startswith("mvault/"):
    _fail(f"member is outside mvault/: {name!r}")


def _read_bounded(fileobj: BinaryIO, size: int, limit: int, context: str) -> bytes:
  if size > limit:
    _fail(f"{context} exceeds its {limit}-byte limit")
  data = fileobj.read(size + 1)
  if len(data) != size:
    _fail(f"{context} ended before its declared size")
  return data


def _iter_lines(fileobj: BinaryIO, size: int, limit: int, context: str) -> Iterator[bytes]:
  remaining = size
  buffer = b""
  while remaining:
    chunk = fileobj.read(min(64 * 1024, remaining))
    if not chunk:
      _fail(f"{context} ended before its declared size")
    remaining -= len(chunk)
    buffer += chunk
    while b"\n" in buffer:
      line, buffer = buffer.split(b"\n", 1)
      if len(line) + 1 > limit:
        _fail(f"{context} contains a line larger than {limit} bytes")
      yield line + b"\n"
    if len(buffer) > limit:
      _fail(f"{context} contains a line larger than {limit} bytes")
  if buffer:
    _fail(f"{context} must end with a newline")


def _stream_hash(fileobj: BinaryIO, size: int, context: str) -> str:
  digest = hashlib.sha256()
  remaining = size
  while remaining:
    chunk = fileobj.read(min(1024 * 1024, remaining))
    if not chunk:
      _fail(f"{context} ended before its declared size")
    remaining -= len(chunk)
    digest.update(chunk)
  return digest.hexdigest()


def _validate_header(value: object) -> dict[str, object]:
  header = _object(value, "header")
  _exact_keys(
    header,
    {"catalogs", "created_at", "format", "format_version", "optional_features", "required_features", "source"},
    set(),
    "header",
  )
  version = _integer(header["format_version"], "header.format_version", minimum=1)
  if header["format"] != FORMAT or version != FORMAT_VERSION:
    _fail("unsupported format name or major version")
  _timestamp(header["created_at"], "header.created_at")
  required = _string_array(header["required_features"], "header.required_features")
  if tuple(required) != REQUIRED_FEATURES:
    unknown = sorted(set(required) - set(REQUIRED_FEATURES))
    if unknown:
      _fail(f"unknown required feature(s): {', '.join(unknown)}")
    _fail("header.required_features does not declare the v1 required feature set")
  optional = _string_array(header["optional_features"], "header.optional_features")
  unknown_optional = sorted(set(optional) - set(KNOWN_OPTIONAL_FEATURES))
  if unknown_optional:
    _fail(f"unknown optional feature(s): {', '.join(unknown_optional)}")
  if header["catalogs"] != list(CATALOGS):
    _fail("header.catalogs must contain the complete v1 catalog order")
  source = _object(header["source"], "header.source")
  _exact_keys(source, {"makersvault_version", "schema_version"}, set(), "header.source")
  _string(source["makersvault_version"], "header.source.makersvault_version", empty=False)
  _integer(source["schema_version"], "header.source.schema_version", minimum=1)
  return header


def _preview(value: object, context: str) -> None:
  preview = _object(value, context)
  _exact_keys(preview, {"policy_version", "reason", "source", "status"}, set(), context)
  _integer(preview["policy_version"], f"{context}.policy_version", minimum=1)
  _nullable_string(preview["reason"], f"{context}.reason")
  _nullable_string(preview["source"], f"{context}.source")
  if _string(preview["status"], f"{context}.status") not in {
    "pending", "ready", "failed", "skipped_policy", "retry_requested"
  }:
    _fail(f"{context}.status is not recognized")


def _record_keys(record: dict[str, object], required: set[str], optional: set[str], context: str) -> None:
  _exact_keys(record, required, optional, context)


def _validate_record(catalog: str, value: object, context: str) -> dict[str, object]:
  record = _object(value, context)
  if catalog == "folders":
    _record_keys(record, {"id", "name", "parent_id", "tags"}, set(), context)
    _identifier(record["id"], f"{context}.id")
    _string(record["name"], f"{context}.name", empty=False)
    _nullable_identifier(record["parent_id"], f"{context}.parent_id")
    _string_array(record["tags"], f"{context}.tags")
  elif catalog == "machines":
    fields = {"archived_at", "category", "created_at", "id", "location", "manufacturer", "model", "name", "notes", "updated_at"}
    _record_keys(record, fields, set(), context)
    _identifier(record["id"], f"{context}.id")
    _string(record["name"], f"{context}.name", empty=False)
    if _string(record["category"], f"{context}.category") not in {"fdm_printer", "resin_printer", "laser", "cnc", "pcb", "other"}:
      _fail(f"{context}.category is not recognized")
    for key in ("location", "manufacturer", "model", "notes"):
      _nullable_string(record[key], f"{context}.{key}")
    _timestamp(record["created_at"], f"{context}.created_at")
    _timestamp(record["updated_at"], f"{context}.updated_at")
    _nullable_timestamp(record["archived_at"], f"{context}.archived_at")
  elif catalog == "artifacts":
    fields = {"collection", "creator", "current_revision_id", "deleted_at", "filename", "folder_id", "id", "mime", "name", "notes", "prepared_file_id", "prepared_machine_id", "prepared_metadata", "preview", "size", "supporting_file_count", "tags", "title", "trash_original_folder_id", "trash_original_folder_name"}
    _record_keys(record, fields, set(), context)
    _identifier(record["id"], f"{context}.id")
    for key in ("filename", "mime", "name"):
      _string(record[key], f"{context}.{key}")
    _integer(record["size"], f"{context}.size")
    _integer(record["supporting_file_count"], f"{context}.supporting_file_count")
    _string_array(record["tags"], f"{context}.tags")
    for key in ("collection", "creator", "notes", "title", "trash_original_folder_name"):
      _nullable_string(record[key], f"{context}.{key}")
    for key in ("current_revision_id", "folder_id", "prepared_file_id", "prepared_machine_id", "trash_original_folder_id"):
      _nullable_identifier(record[key], f"{context}.{key}")
    _nullable_timestamp(record["deleted_at"], f"{context}.deleted_at")
    _metadata(record["prepared_metadata"], f"{context}.prepared_metadata")
    _preview(record["preview"], f"{context}.preview")
  elif catalog == "revisions":
    fields = {"asset_id", "change_note", "content", "created_at", "derived_thumbnail_member", "filename", "id", "mime", "origin_revision_id", "prepared_file_id", "prepared_machine_id", "prepared_metadata", "preview", "revision_number", "sha256", "size"}
    _record_keys(record, fields, set(), context)
    for key in ("id", "asset_id"):
      _identifier(record[key], f"{context}.{key}")
    for key in ("origin_revision_id", "prepared_file_id", "prepared_machine_id"):
      _nullable_identifier(record[key], f"{context}.{key}")
    _integer(record["revision_number"], f"{context}.revision_number", minimum=1)
    _timestamp(record["created_at"], f"{context}.created_at")
    _string(record["filename"], f"{context}.filename")
    _string(record["mime"], f"{context}.mime")
    _integer(record["size"], f"{context}.size")
    if record["sha256"] is not None:
      _sha256(record["sha256"], f"{context}.sha256")
    _nullable_string(record["change_note"], f"{context}.change_note")
    _metadata(record["prepared_metadata"], f"{context}.prepared_metadata")
    _preview(record["preview"], f"{context}.preview")
    _nullable_string(record["derived_thumbnail_member"], f"{context}.derived_thumbnail_member")
    content = _object(record["content"], f"{context}.content")
    _record_keys(content, {"member", "ownership", "source_path", "state"}, set(), f"{context}.content")
    ownership = _string(content["ownership"], f"{context}.content.ownership")
    state = _string(content["state"], f"{context}.content.state")
    member = _nullable_string(content["member"], f"{context}.content.member")
    source_path = _nullable_string(content["source_path"], f"{context}.content.source_path")
    if ownership == "managed":
      if state != "ready" or member is None or source_path is not None or record["sha256"] is None:
        _fail(f"{context}.content has an invalid managed-content declaration")
    elif ownership == "external":
      if state not in {"ready", "unavailable", "changed", "pending", "failed"} or member is not None or not source_path:
        _fail(f"{context}.content has an invalid external-content declaration")
    else:
      _fail(f"{context}.content.ownership is not recognized")
  elif catalog == "files":
    fields = {"asset_id", "filename", "id", "member", "metadata", "mime", "revision_id", "role", "sha256", "size"}
    _record_keys(record, fields, set(), context)
    for key in ("id", "asset_id"):
      _identifier(record[key], f"{context}.{key}")
    _nullable_identifier(record["revision_id"], f"{context}.revision_id")
    for key in ("filename", "mime", "role", "member"):
      _string(record[key], f"{context}.{key}", empty=False)
    if record["role"] not in {"supporting", "prepared"}:
      _fail(f"{context}.role is not recognized")
    _integer(record["size"], f"{context}.size")
    _sha256(record["sha256"], f"{context}.sha256")
    _metadata(record["metadata"], f"{context}.metadata")
  elif catalog == "projects":
    fields = {"created_at", "creator", "deleted_at", "id", "license", "name", "notes", "source_url", "tags", "updated_at"}
    _record_keys(record, fields, set(), context)
    _identifier(record["id"], f"{context}.id")
    _string(record["name"], f"{context}.name", empty=False)
    for key in ("creator", "license", "notes", "source_url"):
      _nullable_string(record[key], f"{context}.{key}")
    _string_array(record["tags"], f"{context}.tags")
    _timestamp(record["created_at"], f"{context}.created_at")
    _timestamp(record["updated_at"], f"{context}.updated_at")
    _nullable_timestamp(record["deleted_at"], f"{context}.deleted_at")
  elif catalog == "project-memberships":
    _record_keys(record, {"asset_id", "created_at", "project_id"}, set(), context)
    _identifier(record["asset_id"], f"{context}.asset_id")
    _identifier(record["project_id"], f"{context}.project_id")
    _timestamp(record["created_at"], f"{context}.created_at")
  elif catalog == "project-relationships":
    _record_keys(record, {"created_at", "id", "kind", "project_id", "source_asset_id", "target_asset_id"}, set(), context)
    for key in ("id", "project_id", "source_asset_id", "target_asset_id"):
      _identifier(record[key], f"{context}.{key}")
    if record["source_asset_id"] == record["target_asset_id"]:
      _fail(f"{context} endpoints must be distinct")
    if _string(record["kind"], f"{context}.kind") not in {"derived_from", "documentation_for", "component_of"}:
      _fail(f"{context}.kind is not recognized")
    _timestamp(record["created_at"], f"{context}.created_at")
  elif catalog == "artifact-machines":
    _record_keys(record, {"asset_id", "created_at", "machine_id"}, set(), context)
    _identifier(record["asset_id"], f"{context}.asset_id")
    _identifier(record["machine_id"], f"{context}.machine_id")
    _timestamp(record["created_at"], f"{context}.created_at")
  elif catalog == "settings":
    _record_keys(record, {"key", "value"}, set(), context)
    if _string(record["key"], f"{context}.key") not in {"storage_path_template", "trash_retention"}:
      _fail(f"{context}.key is not a portable v1 setting")
    _metadata(record["value"], f"{context}.value")
  else:
    _fail(f"unknown catalog: {catalog}")
  return record


def _primary_key(catalog: str, record: dict[str, object]) -> str:
  if catalog in {"folders", "machines", "artifacts", "revisions", "files", "projects", "project-relationships"}:
    return str(record["id"])
  if catalog == "project-memberships":
    return f"{record['project_id']}\x1f{record['asset_id']}"
  if catalog == "artifact-machines":
    return f"{record['asset_id']}\x1f{record['machine_id']}"
  return str(record["key"])


def _store_record(db: sqlite3.Connection, catalog: str, record: dict[str, object], context: str) -> None:
  key = _primary_key(catalog, record)
  try:
    db.execute("INSERT INTO records(catalog, record_key, data) VALUES (?, ?, ?)", (catalog, key, _canonical_json(record)))
  except sqlite3.IntegrityError:
    _fail(f"{context} duplicates record key {key!r}")
  if catalog == "files":
    db.execute(
      "INSERT INTO file_index(id, asset_id, revision_id, role) VALUES (?, ?, ?, ?)",
      (record["id"], record["asset_id"], record["revision_id"], record["role"]),
    )


def _exists(db: sqlite3.Connection, catalog: str, key: object) -> bool:
  if key is None:
    return True
  return db.execute("SELECT 1 FROM records WHERE catalog=? AND record_key=?", (catalog, str(key))).fetchone() is not None


def _get_record(db: sqlite3.Connection, catalog: str, key: object) -> dict[str, object] | None:
  if key is None:
    return None
  row = db.execute("SELECT data FROM records WHERE catalog=? AND record_key=?", (catalog, str(key))).fetchone()
  return json.loads(row[0]) if row else None


def _validate_references(db: sqlite3.Connection) -> None:
  for catalog, key, raw in db.execute("SELECT catalog, record_key, data FROM records ORDER BY catalog, record_key"):
    record = json.loads(raw)
    refs: list[tuple[str, object, str]] = []
    if catalog == "folders": refs.append(("folders", record["parent_id"], "parent_id"))
    elif catalog == "artifacts":
      refs.extend((
        ("folders", record["folder_id"], "folder_id"),
        ("folders", record["trash_original_folder_id"], "trash_original_folder_id"),
        ("revisions", record["current_revision_id"], "current_revision_id"),
        ("files", record["prepared_file_id"], "prepared_file_id"),
        ("machines", record["prepared_machine_id"], "prepared_machine_id"),
      ))
    elif catalog == "revisions":
      refs.extend((
        ("artifacts", record["asset_id"], "asset_id"),
        ("revisions", record["origin_revision_id"], "origin_revision_id"),
        ("files", record["prepared_file_id"], "prepared_file_id"),
        ("machines", record["prepared_machine_id"], "prepared_machine_id"),
      ))
    elif catalog == "files":
      refs.extend((("artifacts", record["asset_id"], "asset_id"), ("revisions", record["revision_id"], "revision_id")))
    elif catalog == "project-memberships":
      refs.extend((("projects", record["project_id"], "project_id"), ("artifacts", record["asset_id"], "asset_id")))
    elif catalog == "project-relationships":
      refs.extend((("projects", record["project_id"], "project_id"), ("artifacts", record["source_asset_id"], "source_asset_id"), ("artifacts", record["target_asset_id"], "target_asset_id")))
    elif catalog == "artifact-machines":
      refs.extend((("artifacts", record["asset_id"], "asset_id"), ("machines", record["machine_id"], "machine_id")))
    for target, value, field in refs:
      if not _exists(db, target, value):
        _fail(f"{catalog} record {key!r} has dangling {field} reference {value!r}")

    if catalog == "artifacts":
      current = _get_record(db, "revisions", record["current_revision_id"])
      prepared = _get_record(db, "files", record["prepared_file_id"])
      if current and current["asset_id"] != key:
        _fail(f"artifact {key!r} current revision belongs to another artifact")
      if prepared and (prepared["asset_id"] != key or prepared["role"] != "prepared"):
        _fail(f"artifact {key!r} prepared file has the wrong owner or role")
      supporting = db.execute(
        "SELECT COUNT(*) FROM file_index WHERE asset_id=? AND role='supporting'", (key,)
      ).fetchone()[0]
      if supporting != record["supporting_file_count"]:
        _fail(f"artifact {key!r} supporting_file_count does not match its files")
    elif catalog == "revisions":
      origin = _get_record(db, "revisions", record["origin_revision_id"])
      prepared = _get_record(db, "files", record["prepared_file_id"])
      if origin and origin["asset_id"] != record["asset_id"]:
        _fail(f"revision {key!r} origin belongs to another artifact")
      if prepared and (prepared["asset_id"] != record["asset_id"] or prepared["role"] != "prepared"):
        _fail(f"revision {key!r} prepared file has the wrong owner or role")
    elif catalog == "files":
      revision = _get_record(db, "revisions", record["revision_id"])
      if revision and revision["asset_id"] != record["asset_id"]:
        _fail(f"file {key!r} revision belongs to another artifact")
    elif catalog == "project-relationships":
      for endpoint in (record["source_asset_id"], record["target_asset_id"]):
        membership_key = f"{record['project_id']}\x1f{endpoint}"
        if not _exists(db, "project-memberships", membership_key):
          _fail(f"project relationship {key!r} endpoint {endpoint!r} is not a project member")

  for _, key, raw in db.execute("SELECT catalog, record_key, data FROM records WHERE catalog IN ('revisions','files')"):
    record = json.loads(raw)
    derived = record.get("derived_thumbnail_member")
    if derived is not None:
      expected_derived = f"mvault/derived/thumbnails/revisions/{key}"
      if derived != expected_derived or db.execute("SELECT 1 FROM members WHERE name=?", (derived,)).fetchone() is None:
        _fail(f"revision {key!r} references an invalid derived thumbnail")
      db.execute("UPDATE members SET claimed=1 WHERE name=?", (derived,))
    if "content" in record:
      member = record["content"]["member"]
      digest = record["sha256"]
      size = record["size"]
      if member is None:
        continue
      expected = f"mvault/content/revisions/{key}/primary"
    else:
      member = record["member"]
      digest = record["sha256"]
      size = record["size"]
      expected = f"mvault/content/files/{key}/payload"
    if member != expected:
      _fail(f"content record {key!r} uses non-canonical member {member!r}")
    observed = db.execute("SELECT size, sha256, claimed FROM members WHERE name=?", (member,)).fetchone()
    if observed is None:
      _fail(f"content record {key!r} references missing member {member!r}")
    if observed[0] != size or observed[1] != digest:
      _fail(f"content member {member!r} does not match its record size/digest")
    db.execute("UPDATE members SET claimed=1 WHERE name=?", (member,))

  unclaimed = db.execute("SELECT name FROM members WHERE class IN ('content','derived') AND claimed=0 ORDER BY name LIMIT 1").fetchone()
  if unclaimed:
    _fail(f"archive contains unclaimed payload member {unclaimed[0]!r}")


def _validate_manifest(value: object, db: sqlite3.Connection, record_counts: dict[str, int]) -> dict[str, object]:
  manifest = _object(value, "manifest")
  _exact_keys(manifest, {"catalog_records", "content", "external", "format", "format_version"}, set(), "manifest")
  version = _integer(manifest["format_version"], "manifest.format_version", minimum=1)
  if manifest["format"] != FORMAT or version != FORMAT_VERSION:
    _fail("manifest format/version does not match v1")
  catalog_records = _object(manifest["catalog_records"], "manifest.catalog_records")
  if set(catalog_records) != set(CATALOGS):
    _fail("manifest.catalog_records must cover every v1 catalog")
  for name in CATALOGS:
    if _integer(catalog_records[name], f"manifest.catalog_records.{name}") != record_counts[name]:
      _fail(f"manifest count for {name} does not match the catalog")
  content = _object(manifest["content"], "manifest.content")
  _exact_keys(content, {"authoritative_bytes", "authoritative_files", "complete_managed_content", "derived_bytes", "derived_files"}, set(), "manifest.content")
  _boolean(content["complete_managed_content"], "manifest.content.complete_managed_content")
  if content["complete_managed_content"] is not True:
    _fail("v1 archive must declare complete managed content")
  observed_content = db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM members WHERE class='content'").fetchone()
  observed_derived = db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM members WHERE class='derived'").fetchone()
  for key, observed in (("authoritative_files", observed_content[0]), ("authoritative_bytes", observed_content[1]), ("derived_files", observed_derived[0]), ("derived_bytes", observed_derived[1])):
    if _integer(content[key], f"manifest.content.{key}") != observed:
      _fail(f"manifest.content.{key} does not match archive members")
  external = _object(manifest["external"], "manifest.external")
  _exact_keys(external, {"available", "changed", "failed", "pending", "records", "unavailable"}, set(), "manifest.external")
  actual = {"available": 0, "changed": 0, "failed": 0, "pending": 0, "records": 0, "unavailable": 0}
  for (raw,) in db.execute("SELECT data FROM records WHERE catalog='revisions'"):
    record = json.loads(raw)
    if record["content"]["ownership"] == "external":
      actual["records"] += 1
      state = record["content"]["state"]
      actual["available" if state == "ready" else state] += 1
  for key, observed in actual.items():
    if _integer(external[key], f"manifest.external.{key}") != observed:
      _fail(f"manifest.external.{key} does not match revision records")
  return manifest


def _database(path: str) -> sqlite3.Connection:
  db = sqlite3.connect(path)
  db.execute("PRAGMA journal_mode=OFF")
  db.execute("PRAGMA synchronous=OFF")
  db.execute("CREATE TABLE members(seq INTEGER PRIMARY KEY, name TEXT UNIQUE, size INTEGER, sha256 TEXT, class TEXT, claimed INTEGER DEFAULT 0)")
  db.execute("CREATE TABLE records(catalog TEXT, record_key TEXT, data BLOB, PRIMARY KEY(catalog, record_key))")
  db.execute("CREATE TABLE file_index(id TEXT PRIMARY KEY, asset_id TEXT, revision_id TEXT, role TEXT)")
  db.execute("CREATE INDEX file_index_asset_role ON file_index(asset_id, role)")
  return db


def verify_archive(archive: str | os.PathLike[str], limits: VerificationLimits | None = None) -> dict[str, object]:
  """Stream and verify one .mvault archive, returning a stable success report."""
  limits = limits or VerificationLimits()
  limits.validate()
  archive_path = Path(archive)
  try:
    source = archive_path.open("rb")
  except OSError as exc:
    _fail(f"cannot open archive: {exc}")
  if source.read(2) != b"\x1f\x8b":
    source.close()
    _fail("archive is not gzip-compressed")
  source.seek(0)

  with tempfile.TemporaryDirectory(prefix="mvault-verify-") as temp_dir:
    db = _database(str(Path(temp_dir) / "index.sqlite3"))
    member_count = 0
    expanded_bytes = 0
    record_count = 0
    record_counts = {name: 0 for name in CATALOGS}
    last_payload = ""
    stage = "header"
    header: dict[str, object] | None = None
    manifest: dict[str, object] | None = None
    checksums_seen = False
    try:
      try:
        archive_file = tarfile.open(fileobj=source, mode="r|gz", tarinfo=_BoundedTarInfo)
      except (OSError, tarfile.TarError) as exc:
        _fail(f"cannot read gzip/PAX tar: {exc}")
      with archive_file:
        archive_file._mvault_max_members = limits.max_members
        archive_file._mvault_max_expanded_bytes = limits.max_expanded_bytes
        for member in archive_file:
          member_count += 1
          archive_file._mvault_semantic_members = member_count
          if member_count + getattr(archive_file, "_mvault_extension_members", 0) > limits.max_members:
            _fail("archive exceeds the configured member limit")
          _member_name(member.name)
          if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE):
            _fail(f"only regular-file members are permitted: {member.name!r}")
          if db.execute("SELECT 1 FROM members WHERE name=?", (member.name,)).fetchone() is not None:
            _fail(f"duplicate archive member: {member.name!r}")
          expanded_bytes += member.size
          archive_file._mvault_semantic_bytes = expanded_bytes
          if expanded_bytes + getattr(archive_file, "_mvault_extension_bytes", 0) > limits.max_expanded_bytes:
            _fail("archive exceeds the configured expanded-byte limit")
          fileobj = archive_file.extractfile(member)
          if fileobj is None:
            _fail(f"could not stream member {member.name!r}")

          if member_count == 1:
            if member.name != HEADER_PATH:
              _fail(f"first member must be {HEADER_PATH}")
            raw = _read_bounded(fileobj, member.size, MAX_HEADER_BYTES, "header")
            header = _validate_header(_json_loads(raw, "header"))
            _expect_canonical(raw, header, "header")
            digest = hashlib.sha256(raw).hexdigest()
            member_class = "metadata"
            stage = "payload"
          elif member.name == CHECKSUMS_PATH:
            if stage != "checksums" or manifest is None:
              _fail("checksums.sha256 must be the final member after manifest.json")
            expected_seq = 1
            for line in _iter_lines(fileobj, member.size, MAX_CHECKSUM_LINE_BYTES, "checksums.sha256"):
              try:
                decoded = line[:-1].decode("utf-8")
              except UnicodeDecodeError:
                _fail("checksums.sha256 is not UTF-8")
              if len(decoded) < 67 or decoded[64:66] != "  ":
                _fail("checksums.sha256 contains a malformed line")
              digest_text, name = decoded[:64], decoded[66:]
              _sha256(digest_text, "checksums.sha256 digest")
              row = db.execute("SELECT name, sha256 FROM members WHERE seq=?", (expected_seq,)).fetchone()
              if row is None or row[0] != name or row[1] != digest_text:
                _fail(f"checksum inventory mismatch at entry {expected_seq}")
              expected_seq += 1
            if expected_seq != member_count:
              _fail("checksums.sha256 does not cover every prior member")
            checksums_seen = True
            stage = "done"
            continue
          elif member.name == MANIFEST_PATH:
            completed = db.execute("SELECT COUNT(*) FROM members WHERE class='catalog'").fetchone()[0]
            if stage != "catalog" or completed != len(CATALOGS):
              _fail("manifest.json appears before the complete catalog set")
            raw = _read_bounded(fileobj, member.size, MAX_MANIFEST_BYTES, "manifest")
            manifest_value = _json_loads(raw, "manifest")
            _expect_canonical(raw, manifest_value, "manifest")
            _validate_references(db)
            manifest = _validate_manifest(manifest_value, db, record_counts)
            digest = hashlib.sha256(raw).hexdigest()
            member_class = "metadata"
            stage = "checksums"
          elif member.name in CATALOG_PATHS:
            # Catalog order derives from the number already stored, not record counts.
            completed = db.execute("SELECT COUNT(*) FROM members WHERE class='catalog'").fetchone()[0]
            expected = CATALOG_PATHS[completed] if completed < len(CATALOG_PATHS) else None
            if stage not in {"payload", "catalog"} or member.name != expected:
              _fail(f"catalog member is out of order: {member.name!r}")
            catalog = CATALOGS[completed]
            digest_state = hashlib.sha256()
            previous_key: str | None = None
            for line_number, raw_line in enumerate(_iter_lines(fileobj, member.size, MAX_JSONL_LINE_BYTES, member.name), 1):
              digest_state.update(raw_line)
              value = _json_loads(raw_line, f"{member.name}:{line_number}")
              _expect_canonical(raw_line, value, f"{member.name}:{line_number}")
              record = _validate_record(catalog, value, f"{member.name}:{line_number}")
              key = _primary_key(catalog, record)
              if previous_key is not None and key <= previous_key:
                _fail(f"{member.name} records must be sorted by portable key")
              previous_key = key
              _store_record(db, catalog, record, f"{member.name}:{line_number}")
              record_counts[catalog] += 1
              record_count += 1
              if record_count > limits.max_records:
                _fail("archive exceeds the configured catalog-record limit")
            digest = digest_state.hexdigest()
            member_class = "catalog"
            stage = "catalog"
          else:
            if stage != "payload":
              _fail(f"payload member appears after catalogs: {member.name!r}")
            content_match = _CONTENT_RE.fullmatch(member.name)
            derived_match = _DERIVED_RE.fullmatch(member.name)
            if not content_match and not derived_match:
              _fail(f"member path is not declared by portable vault v1: {member.name!r}")
            if member.name <= last_payload:
              _fail("payload members must be sorted by member path")
            last_payload = member.name
            digest = _stream_hash(fileobj, member.size, member.name)
            member_class = "content" if content_match else "derived"

          try:
            db.execute(
              "INSERT INTO members(seq, name, size, sha256, class) VALUES (?, ?, ?, ?, ?)",
              (member_count, member.name, member.size, digest, member_class),
            )
          except sqlite3.IntegrityError:
            _fail(f"duplicate archive member: {member.name!r}")
        if not checksums_seen or stage != "done":
          _fail("archive ended before the final checksum inventory")
      if header is None or manifest is None:
        _fail("archive is missing required metadata")
      derived_count = db.execute("SELECT COUNT(*) FROM members WHERE class='derived'").fetchone()[0]
      if derived_count and "derived-thumbnails" not in header["optional_features"]:
        _fail("derived thumbnail members require the derived-thumbnails optional feature")
      return {
        "catalog_records": record_counts,
        "expanded_bytes": expanded_bytes,
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "members": member_count,
        "valid": True,
      }
    except (OSError, tarfile.TarError) as exc:
      _fail(f"archive stream is malformed: {exc}")
    finally:
      db.close()
      source.close()


def _positive(value: str) -> int:
  try:
    parsed = int(value)
  except ValueError as exc:
    raise argparse.ArgumentTypeError("must be an integer") from exc
  if parsed < 1:
    raise argparse.ArgumentTypeError("must be positive")
  return parsed


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Verify a MakersVault portable .mvault v1 archive")
  parser.add_argument("archive", help="path to the .mvault archive")
  parser.add_argument("--max-members", type=_positive, default=DEFAULT_MAX_MEMBERS)
  parser.add_argument("--max-records", type=_positive, default=DEFAULT_MAX_RECORDS)
  parser.add_argument("--max-expanded-bytes", type=_positive, default=DEFAULT_MAX_EXPANDED_BYTES)
  args = parser.parse_args(argv)
  limits = VerificationLimits(args.max_members, args.max_records, args.max_expanded_bytes)
  try:
    report = verify_archive(args.archive, limits)
  except MvaultVerificationError as exc:
    print(f"mvault: invalid: {exc}", file=sys.stderr)
    return 2
  print(json.dumps(report, sort_keys=True, separators=(",", ":")))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
