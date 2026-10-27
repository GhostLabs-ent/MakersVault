from typing import List, Optional

from pydantic import BaseModel


class AssetCreate(BaseModel):
  title: Optional[str] = None
  notes: Optional[str] = None
  tags: List[str] = []


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


class PreparedPrintOut(BaseModel):
  printer: Optional[str] = None
  material: Optional[str] = None
  nozzle_mm: Optional[float] = None
  layer_height_mm: Optional[float] = None
  estimated_seconds: Optional[int] = None
  format: Optional[str] = None
  removable: bool = False


class AssetFileOut(BaseModel):
  id: str
  filename: str
  mime: str
  size: int
  url: str


class AssetOut(BaseModel):
  id: str
  name: str
  filename: str
  mime: str
  size: int
  title: Optional[str]
  notes: Optional[str]
  creator: Optional[str]
  collection: Optional[str]
  tags: List[str]
  url: str
  thumb_url: Optional[str]
  folder_id: Optional[str]
  storage_path: Optional[str]
  missing_since: Optional[str] = None
  supporting_file_count: int = 0
  prepared_print: Optional[PreparedPrintOut] = None
  slicer_url: Optional[str] = None
  slicer_filename: Optional[str] = None


class ImportZipResult(BaseModel):
  assets: List[AssetOut]
  failed: List[str] = []


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


class FolderOut(BaseModel):
  id: str
  name: str
  tags: List[str]
  parent_id: Optional[str]
  storage_path: Optional[str] = None


class LoginRequest(BaseModel):
  username: str
  password: str


class LoginResponse(BaseModel):
  token: str
  expires_in: int


class DownloadRequest(BaseModel):
  asset_ids: Optional[List[str]] = None
  tag: Optional[str] = None
  folder_id: Optional[str] = None
  filename: Optional[str] = None


class TagUpdate(BaseModel):
  tags: List[str]


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


class AssetMetaUpdate(BaseModel):
  name: Optional[str] = None
  title: Optional[str] = None
  notes: Optional[str] = None
  creator: Optional[str] = None
  collection: Optional[str] = None


class AssetRename(BaseModel):
  filename: str


class AssetFolderUpdate(BaseModel):
  folder_id: Optional[str] = None


class MountImportSettings(BaseModel):
  enabled: bool
  copy_files: bool


class MountImportSettingsOut(MountImportSettings):
  path: Optional[str] = None


class StorageSettings(BaseModel):
  template: str


class StorageSettingsOut(BaseModel):
  template: str
  default_template: str
  allowed_tokens: List[str]
  sample_path: str
  moved: int = 0
  skipped: int = 0


class LibraryScanStatusOut(BaseModel):
  running: bool
  started_at: Optional[float] = None
  finished_at: Optional[float] = None
  registered: int = 0
  known: int = 0
  ignored: int = 0
  missing: int = 0
  failed: int = 0
  errors: List[str] = []


class BatchFailure(BaseModel):
  id: str
  code: str      # stable slug: not_found | conflict | invalid | error
  status: int    # mirrors the equivalent single-item HTTP status
  error: str     # human-readable detail


class BatchTagsRequest(BaseModel):
  asset_ids: List[str] = []
  add_tags: List[str] = []
  remove_tags: List[str] = []


class BatchTagsOut(BaseModel):
  updated: List[AssetOut] = []
  failed: List[BatchFailure] = []


class BatchFolderRequest(BaseModel):
  asset_ids: List[str] = []
  folder_id: Optional[str] = None


class BatchFolderOut(BaseModel):
  updated: List[AssetOut] = []
  failed: List[BatchFailure] = []


class BatchDeleteRequest(BaseModel):
  asset_ids: List[str] = []


class BatchDeleteOut(BaseModel):
  deleted: List[str] = []
  failed: List[BatchFailure] = []
