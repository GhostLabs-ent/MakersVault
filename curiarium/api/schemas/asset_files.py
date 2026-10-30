"""Supporting files and signed file grants for one asset (Mf-avo9 split)."""

from typing import List

from pydantic import BaseModel

__all__ = [
  "AssetFileLimitsOut",
  "AssetFileOrderUpdate",
  "AssetFileOut",
  "AssetFileRename",
  "FileGrantListOut",
  "FileGrantOut",
  "FileGrantRequest",
]


class AssetFileOut(BaseModel):
  id: str
  filename: str
  mime: str
  size: int
  position: int = 0
  url: str


class AssetFileRename(BaseModel):
  filename: str


class AssetFileOrderUpdate(BaseModel):
  file_ids: List[str]


class AssetFileLimitsOut(BaseModel):
  count: int
  total_bytes: int
  max_count: int
  max_file_bytes: int
  max_total_bytes: int


class FileGrantRequest(BaseModel):
  """The file URLs to mint grants for; bounds are checked in the handler.

  The route validates emptiness and the maximum count so both are a readable
  400, not a 422 produced by the model layer.
  """

  paths: List[str] = []


class FileGrantOut(BaseModel):
  """One granted URL, relative to the API root (the client owns the public base).

  `path` echoes the requested string verbatim - query included - so a client can
  key its cache by the exact path it holds, and `url` is that same path plus
  `sig`.
  """

  path: str
  url: str
  expires_at: int


class FileGrantListOut(BaseModel):
  grants: List[FileGrantOut]
