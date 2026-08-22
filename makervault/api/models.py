import uuid
from typing import Optional
from sqlmodel import Field, SQLModel


class Folder(SQLModel, table=True):
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  name: str
  tags_json: str = Field(default="[]")
  parent_id: Optional[str] = Field(default=None, foreign_key="folder.id")


class Asset(SQLModel, table=True):
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  name: str = Field(default="")
  filename: str
  mime: str
  size: int
  tags_json: str = Field(default="[]")
  title: Optional[str] = None
  notes: Optional[str] = None
  creator: Optional[str] = None
  collection: Optional[str] = None
  folder_id: Optional[str] = None
  source_path: Optional[str] = None
  storage_path: Optional[str] = None
  supporting_file_count: int = Field(default=0)
  prepared_file_id: Optional[str] = None
  prepared_metadata_json: Optional[str] = None
  preview_status: str = Field(default="pending", index=True)
  preview_reason: Optional[str] = None
  preview_attempts: int = Field(default=0)
  preview_policy_version: int = Field(default=1)
  preview_updated_at: Optional[str] = None
  preview_source: Optional[str] = None
  current_revision_id: Optional[str] = Field(default=None, index=True)
  current_thumb_path: Optional[str] = None
  deleted_at: Optional[str] = Field(default=None, index=True)
  trash_original_folder_id: Optional[str] = None
  trash_original_folder_name: Optional[str] = None


class ArtifactRevision(SQLModel, table=True):
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  asset_id: str = Field(foreign_key="asset.id", index=True)
  revision_number: int
  created_at: str
  origin_revision_id: Optional[str] = Field(default=None, foreign_key="artifactrevision.id")
  filename: str
  mime: str
  size: int = Field(default=0)
  sha256: Optional[str] = Field(default=None, index=True)
  observed_sha256: Optional[str] = None
  content_state: str = Field(default="pending", index=True)
  content_reason: Optional[str] = None
  content_checked_at: Optional[str] = None
  storage_path: Optional[str] = None
  source_path: Optional[str] = None
  change_note: Optional[str] = None
  prepared_file_id: Optional[str] = None
  prepared_metadata_json: Optional[str] = None
  preview_status: str = Field(default="pending", index=True)
  preview_reason: Optional[str] = None
  preview_attempts: int = Field(default=0)
  preview_policy_version: int = Field(default=1)
  preview_updated_at: Optional[str] = None
  preview_source: Optional[str] = None
  preview_thumb_path: Optional[str] = None


class AssetFile(SQLModel, table=True):
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  asset_id: str = Field(foreign_key="asset.id", index=True)
  filename: str
  mime: str
  size: int = Field(default=0)
  role: str = Field(default="supporting", index=True)
  storage_path: str
  metadata_json: Optional[str] = None
  revision_id: Optional[str] = Field(default=None, foreign_key="artifactrevision.id", index=True)


class AppConfig(SQLModel, table=True):
  key: str = Field(primary_key=True)
  value: str


class MountScan(SQLModel, table=True):
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  trigger: str = Field(index=True)
  status: str = Field(index=True)
  mode: str
  root_path: str
  started_at: str
  finished_at: Optional[str] = None
  imported: int = Field(default=0)
  skipped: int = Field(default=0)
  failed: int = Field(default=0)
  failure_details_json: str = Field(default="[]")
  failure_details_omitted: int = Field(default=0)


class ContentHashJob(SQLModel, table=True):
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  trigger: str = Field(index=True)
  status: str = Field(index=True)
  started_at: str
  finished_at: Optional[str] = None
  total: int = Field(default=0)
  processed: int = Field(default=0)
  ready: int = Field(default=0)
  unavailable: int = Field(default=0)
  changed: int = Field(default=0)
  failed: int = Field(default=0)
  failure_details_json: str = Field(default="[]")
  failure_details_omitted: int = Field(default=0)


class ContentHashJobItem(SQLModel, table=True):
  job_id: str = Field(foreign_key="contenthashjob.id", primary_key=True)
  revision_id: str = Field(foreign_key="artifactrevision.id", primary_key=True)
  status: str = Field(default="pending", index=True)
  reason: Optional[str] = None


class TrashPurgeOperation(SQLModel, table=True):
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  trigger: str = Field(index=True)
  status: str = Field(index=True)
  created_at: str
  completed_at: Optional[str] = None
  asset_ids_json: str = Field(default="[]")
  paths_json: str = Field(default="[]")
  results_json: str = Field(default="[]")
  quarantine_path: Optional[str] = None
  requested_bytes: int = Field(default=0)
  managed_bytes: int = Field(default=0)
  error: Optional[str] = None
