"""Web imports, zip inspection/entry selection and project imports (Mf-avo9 split)."""

from typing import List, Optional

from pydantic import BaseModel

from .assets import AssetOut
from .projects import ProjectOut

__all__ = [
  "ImportInspectOut",
  "ImportProjectOut",
  "ImportProjectRequest",
  "ImportRequest",
  "ImportZipEntriesOut",
  "ImportZipEntriesRequest",
  "ImportZipExtractRequest",
  "ImportZipResult",
  "ZipEntryOut",
]


class ImportRequest(BaseModel):
  url: str
  title: Optional[str] = None
  notes: Optional[str] = None
  tags: List[str] = []
  folder_id: Optional[str] = None
  filename: Optional[str] = None
  makerworld_cookie: Optional[str] = None
  thingiverse_cookie: Optional[str] = None


class ImportInspectOut(BaseModel):
  filename: str
  mime: str
  is_zip: bool


class ZipEntryOut(BaseModel):
  path: str
  size: int


class ImportZipEntriesRequest(ImportRequest):
  pass


class ImportZipEntriesOut(BaseModel):
  filename: str
  entries: List[ZipEntryOut]


class ImportZipExtractRequest(ImportRequest):
  entries: List[str]


class ImportProjectRequest(ImportRequest):
  """A website import that lands in a project (Mf-56z9).

  `entries=None` means "do not unzip": the whole file (or a whole zip) becomes
  one asset. A list - even an empty one - means "extract these entries", exactly
  like `/import/zip`. `project_id` targets an existing project; without it the
  import finds the project for this model page or creates one.
  """

  project_id: Optional[str] = None
  project_name: Optional[str] = None
  entries: Optional[List[str]] = None


class ImportZipResult(BaseModel):
  assets: List[AssetOut]
  failed: List[str] = []


class ImportProjectOut(BaseModel):
  """An import into a project: the project, what changed and why it may be empty.

  `assets` are the assets the import itself produced (already serialized), and
  `added`/`skipped` are their member ids. `failed` lists zip entry paths that
  could not be extracted, never member-id failures. `gated` is true when the
  site refused the files and only the page details were stored; `message` then
  explains how to attach them.
  """

  project: ProjectOut
  created: bool
  assets: List[AssetOut] = []
  added: List[str] = []
  skipped: List[str] = []
  failed: List[str] = []
  gated: bool = False
  message: str = ""
