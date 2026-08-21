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


class AssetFile(SQLModel, table=True):
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  asset_id: str = Field(foreign_key="asset.id", index=True)
  filename: str
  mime: str
  size: int = Field(default=0)
  role: str = Field(default="supporting", index=True)
  storage_path: str
  metadata_json: Optional[str] = None


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
