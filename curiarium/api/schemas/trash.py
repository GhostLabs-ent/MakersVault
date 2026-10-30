"""Trash listing and purge results (Mf-avo9 split)."""

from typing import List, Optional

from pydantic import BaseModel

from .assets import SnapshotNoticeOut

__all__ = [
  "TrashEntryOut",
  "TrashListOut",
  "TrashPurgeOut",
]


class TrashEntryOut(BaseModel):
  path: str
  name: str
  size: int
  mtime: str


class TrashListOut(BaseModel):
  entries: List[TrashEntryOut]
  total_size: int
  snapshot: Optional[SnapshotNoticeOut] = None


class TrashPurgeOut(BaseModel):
  purged: int
  bytes: int
  failed: List[str] = []
