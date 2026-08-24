from typing import List, Literal, Optional
from pydantic import AnyHttpUrl, BaseModel, Field


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
  project_id: Optional[str] = None
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
  revision_id: Optional[str] = None


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
  supporting_file_count: int = 0
  prepared_print: Optional[PreparedPrintOut] = None
  slicer_url: Optional[str] = None
  slicer_filename: Optional[str] = None
  preview_status: Literal["pending", "ready", "failed", "skipped_policy", "retry_requested"] = "pending"
  preview_reason: Optional[str] = None
  preview_attempts: int = 0
  preview_policy_version: int = 1
  preview_updated_at: Optional[str] = None
  preview_source: Optional[str] = None
  current_revision_id: Optional[str] = None


class ProjectCreate(BaseModel):
  name: str = Field(min_length=1, max_length=200)
  notes: Optional[str] = Field(default=None, max_length=10000)
  creator: Optional[str] = Field(default=None, max_length=500)
  source_url: Optional[AnyHttpUrl] = None
  license: Optional[str] = Field(default=None, max_length=500)
  tags: List[str] = Field(default_factory=list, max_length=100)


class ProjectUpdate(BaseModel):
  name: Optional[str] = Field(default=None, min_length=1, max_length=200)
  notes: Optional[str] = Field(default=None, max_length=10000)
  creator: Optional[str] = Field(default=None, max_length=500)
  source_url: Optional[AnyHttpUrl] = None
  license: Optional[str] = Field(default=None, max_length=500)
  tags: Optional[List[str]] = Field(default=None, max_length=100)


class ProjectOut(BaseModel):
  id: str
  name: str
  notes: Optional[str] = None
  creator: Optional[str] = None
  source_url: Optional[str] = None
  license: Optional[str] = None
  tags: List[str] = Field(default_factory=list)
  created_at: str
  updated_at: str
  deleted_at: Optional[str] = None
  member_count: int = 0


class ProjectMembershipOut(BaseModel):
  project_id: str
  asset_id: str
  created_at: str


class PreviewStateUpdate(BaseModel):
  status: Literal["pending", "failed", "skipped_policy"]
  reason: Optional[str] = Field(default=None, max_length=64)


class PreviewPolicyOut(BaseModel):
  version: int
  active_jobs: int
  queue_limit: int
  automatic_max_bytes: int
  automatic_max_triangles: int
  automatic_3mf_expanded_bytes: int
  automatic_3mf_entries: int
  automatic_memory_bytes: int
  automatic_timeout_seconds: int
  detail_max_bytes: int
  detail_max_triangles: int
  detail_3mf_expanded_bytes: int
  detail_3mf_entries: int
  detail_memory_bytes: int
  detail_timeout_seconds: int
  automatic_step_enabled: bool


class ImportZipResult(BaseModel):
  assets: List[AssetOut]
  failed: List[str] = []


class FolderIn(BaseModel):
  name: str
  tags: List[str] = []
  parent_id: Optional[str] = None


class FolderOut(BaseModel):
  id: str
  name: str
  tags: List[str]
  parent_id: Optional[str]


class LoginRequest(BaseModel):
  username: str = Field(min_length=1, max_length=256)
  password: str = Field(min_length=1, max_length=4096)


class LoginResponse(BaseModel):
  token: str
  expires_in: int


class HandoffGrantRequest(BaseModel):
  tool: Literal["slicer", "engraver"]


class HandoffGrantOut(BaseModel):
  redeem_url: str
  grant: str
  filename: str
  expires_in: int


class DownloadRequest(BaseModel):
  asset_ids: Optional[List[str]] = None
  tag: Optional[str] = None
  folder_id: Optional[str] = None
  filename: Optional[str] = None


class TagUpdate(BaseModel):
  tags: List[str]


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


class MountScanFailureOut(BaseModel):
  path: str
  reason: str


class MountScanOut(BaseModel):
  id: str
  trigger: Literal["startup", "manual"]
  status: Literal["running", "completed", "completed_with_failures", "failed", "interrupted"]
  mode: Literal["copy", "index_in_place"]
  root_path: str
  started_at: str
  finished_at: Optional[str] = None
  imported: int = 0
  skipped: int = 0
  failed: int = 0
  failure_details: List[MountScanFailureOut] = Field(default_factory=list)
  failure_details_omitted: int = 0


class MountImportSettingsOut(MountImportSettings):
  path: Optional[str] = None
  last_scan: Optional[MountScanOut] = None


class MountScanStartOut(BaseModel):
  scan: MountScanOut
  started: bool


class StorageSettings(BaseModel):
  template: str
  apply_existing: bool = False


class StorageSettingsOut(BaseModel):
  template: str
  default_template: str
  allowed_tokens: List[str]
  sample_path: str
  moved: int = 0
  skipped: int = 0


class ArtifactRevisionOut(BaseModel):
  id: str
  revision_number: int
  created_at: str
  origin_revision_id: Optional[str] = None
  filename: str
  mime: str
  size: int
  sha256: Optional[str] = None
  content_state: Literal["pending", "ready", "unavailable", "changed", "failed"]
  content_reason: Optional[str] = None
  content_checked_at: Optional[str] = None
  change_note: Optional[str] = None
  prepared_print: Optional[PreparedPrintOut] = None
  url: str
  thumb_url: Optional[str] = None
  is_current: bool


class RevisionCreateOut(BaseModel):
  asset: AssetOut
  revision: ArtifactRevisionOut
  created: bool


class RevisionRestoreRequest(BaseModel):
  change_note: Optional[str] = Field(default=None, max_length=500)


class TrashItemOut(BaseModel):
  id: str
  name: str
  filename: str
  deleted_at: str
  original_folder_id: Optional[str] = None
  original_folder_name: Optional[str] = None
  managed_bytes: int
  managed_file_count: int
  revision_count: int
  supporting_file_count: int
  external_source: bool


class TrashRestoreRequest(BaseModel):
  restore_unassigned: bool = False


class TrashPermanentDeleteRequest(BaseModel):
  asset_ids: List[str] = Field(default_factory=list, max_length=1000)
  confirmation: str = Field(max_length=64)


class TrashPurgeItemOut(BaseModel):
  asset_id: str
  name: str
  status: str
  managed_files: int
  managed_bytes: int
  external_source_preserved: bool


class TrashRetentionUpdate(BaseModel):
  policy: Literal["until_needed", "day", "week", "month", "never"]


class TrashSettingsOut(BaseModel):
  policy: Literal["until_needed", "day", "week", "month", "never"]
  choices: List[str]
  trash_count: int
  managed_bytes: int
  orphaned_quarantine: List[str]


class ContentHashFailureOut(BaseModel):
  revision_id: str
  reason: str


class ContentHashJobOut(BaseModel):
  id: str
  trigger: Literal["startup", "manual", "verify"]
  status: Literal[
    "running",
    "completed",
    "completed_with_findings",
    "interrupted",
  ]
  started_at: str
  finished_at: Optional[str] = None
  total: int = 0
  processed: int = 0
  ready: int = 0
  unavailable: int = 0
  changed: int = 0
  failed: int = 0
  failure_details: List[ContentHashFailureOut] = Field(default_factory=list)
  failure_details_omitted: int = 0


class ContentHashStartRequest(BaseModel):
  verify_all: bool = False


class ContentHashStartOut(BaseModel):
  job: Optional[ContentHashJobOut] = None
  started: bool
