"""Folder creation, read-back and delete preview (Mf-avo9 split)."""

from typing import List, Optional

from pydantic import BaseModel

from .assets import SnapshotNoticeOut

__all__ = [
  "FolderDeletePreviewOut",
  "FolderIn",
  "FolderOut",
]


class FolderIn(BaseModel):
  name: str
  tags: List[str] = []
  parent_id: Optional[str] = None


class FolderDeletePreviewOut(BaseModel):
  folders: int
  assets: int
  files: int
  bytes: int
  in_trash: bool
  snapshot: Optional[SnapshotNoticeOut] = None


class FolderOut(BaseModel):
  id: str
  name: str
  tags: List[str]
  parent_id: Optional[str]
  storage_path: Optional[str] = None
