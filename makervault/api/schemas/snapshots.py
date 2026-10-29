"""Snapshot browsing, restore and retention (Mf-avo9 split)."""

from typing import List, Optional

from pydantic import BaseModel, Field

__all__ = [
  "SnapshotBrowseOut",
  "SnapshotCreatedOut",
  "SnapshotDeleteOut",
  "SnapshotEntryOut",
  "SnapshotListOut",
  "SnapshotOut",
  "SnapshotPruneOut",
  "SnapshotRestoreOut",
  "SnapshotRestoreRequest",
  "SnapshotRetentionIn",
  "SnapshotRetentionOut",
]


class SnapshotOut(BaseModel):
  name: str
  # ISO-8601, aware UTC, as a string: a `datetime` field would move the pinned
  # OpenAPI document.
  created_at: str
  # Floored at 0, so a clock skew that puts a snapshot in the future reads as new.
  age_seconds: int
  reason: str


class SnapshotListOut(BaseModel):
  # Oldest first, the order the provider lists and retention prunes in.
  snapshots: List[SnapshotOut]
  method: str
  supports_browse: bool
  supports_restore: bool


class SnapshotPruneOut(BaseModel):
  pruned: int
  kept: int
  names: List[str]


class SnapshotCreatedOut(BaseModel):
  snapshot: SnapshotOut
  prune: SnapshotPruneOut


class SnapshotDeleteOut(BaseModel):
  ok: bool
  name: str


class SnapshotEntryOut(BaseModel):
  name: str
  # Snapshot-relative, POSIX: always `/`-separated, whatever the host separator is.
  path: str
  is_dir: bool
  # None for a directory, or when the entry's metadata could not be read.
  size: Optional[int] = None
  modified_at: Optional[str] = None


class SnapshotBrowseOut(BaseModel):
  snapshot: str
  path: str
  entries: List[SnapshotEntryOut]


class SnapshotRestoreRequest(BaseModel):
  # The snapshot-relative path to restore; "" restores the whole snapshot.
  path: str = ""


class SnapshotRestoreOut(BaseModel):
  snapshot: str
  path: str
  # LIBRARY-relative: "recovered/<name>[/<path>]".
  destination: str
  files: int
  bytes: int
  # False when a scan was already running; the bytes were copied either way.
  scan_started: bool


class SnapshotRetentionOut(BaseModel):
  keep_last_n: int
  keep_daily: int
  max_age_days: int
  hard_cap: int


class SnapshotRetentionIn(BaseModel):
  keep_last_n: int = Field(ge=1)
  keep_daily: int = Field(ge=0)
  max_age_days: int = Field(ge=1)
  hard_cap: int = Field(ge=1)
