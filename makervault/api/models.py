import uuid
from typing import Optional

from sqlmodel import Field, SQLModel


class Folder(SQLModel, table=True):
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  name: str
  tags_json: str = Field(default="[]")
  parent_id: Optional[str] = Field(default=None, foreign_key="folder.id")
  storage_path: Optional[str] = None


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
  missing_since: Optional[str] = None
  disk_mtime: Optional[int] = None
  is_reference: int = 0


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


# users and sessions are created by migration 005; these classes only describe
# them for typed queries and must never create tables themselves.
class User(SQLModel, table=True):
  __tablename__ = "users"
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  username: str
  email: Optional[str] = None
  password_hash: Optional[str] = None
  role: str = Field(default="viewer")
  disabled: int = Field(default=0)
  created_at: str
  updated_at: str


class UserSession(SQLModel, table=True):
  __tablename__ = "sessions"
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  user_id: Optional[str] = Field(default=None, foreign_key="users.id")
  username: str
  kind: str = Field(default="password")
  refresh_token_hash: str
  device: Optional[str] = None
  user_agent: Optional[str] = None
  client_ip: Optional[str] = None
  created_at: int
  last_used_at: int
  access_expires_at: int
  refresh_expires_at: int
  revoked_at: Optional[int] = None


# audit_events is created by migration 006; this class only describes it for
# typed queries and must never create the table itself (nothing in this app
# calls create_all). The append-only guarantee lives in the table's triggers.
class AuditEvent(SQLModel, table=True):
  __tablename__ = "audit_events"
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  created_at: str
  actor: str
  actor_user_id: Optional[str] = None
  actor_role: str
  actor_kind: str
  action: str
  target: str
  detail_json: Optional[str] = None
  request_id: str
  method: str
  path: str
