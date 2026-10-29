"""Trash listing and purge results (Mf-avo9 split)."""

from typing import List

from pydantic import BaseModel

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


class TrashPurgeOut(BaseModel):
  purged: int
  bytes: int
  failed: List[str] = []
