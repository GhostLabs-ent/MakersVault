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
  position: int = Field(default=0)
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
  # Migration 012: the TOTP seed is AES-256-GCM ciphertext (base64), never a
  # digest, because HOTP must feed the raw seed to HMAC. `totp_last_step` is the
  # last matched TOTP counter burned, so one guarded UPDATE enforces single use.
  totp_secret: Optional[str] = None
  totp_enrolled_at: Optional[str] = None
  totp_last_step: Optional[int] = None
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
  # Migration 011 keeps exactly one superseded refresh hash so a tab can
  # survive one rotation; the column is not unique because it only ever holds
  # a hash that has already been replaced.
  previous_refresh_token_hash: Optional[str] = None
  rotated_at: Optional[int] = None
  # Migration 012: per-session, not per-user, so a password or OIDC login is
  # born without a second factor and step-up upgrades exactly this session.
  mfa_verified_at: Optional[int] = None


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


# mfa_recovery_codes is created by migration 012; this class only describes it
# for typed queries and must never create the table itself. One row per code is
# what makes "consume once" a single guarded UPDATE instead of a JSON rewrite.
class MfaRecoveryCode(SQLModel, table=True):
  __tablename__ = "mfa_recovery_codes"
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  user_id: str = Field(foreign_key="users.id", index=True)
  code_hmac: str
  created_at: str
  used_at: Optional[int] = None


# project and project_asset are created by migration 007; these classes only
# describe them for typed queries and must never create tables (nothing in this
# app calls create_all).
class Project(SQLModel, table=True):
  __tablename__ = "project"
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  name: str
  description: Optional[str] = None
  creator: Optional[str] = None
  source_url: Optional[str] = None
  licence: Optional[str] = None
  licence_url: Optional[str] = None
  origin: str = Field(default="own")
  cover_asset_id: Optional[str] = Field(default=None, foreign_key="asset.id")
  owner_id: Optional[str] = Field(default=None, foreign_key="users.id")
  metadata_json: str = Field(default="{}")
  created_at: str
  updated_at: str


class ProjectAsset(SQLModel, table=True):
  __tablename__ = "project_asset"
  project_id: str = Field(primary_key=True, foreign_key="project.id")
  asset_id: str = Field(primary_key=True, foreign_key="asset.id", index=True)
  role: str = Field(default="member")
  position: int = Field(default=0)
  added_at: str


# import_run is created by migration 008; this class only describes it for typed
# queries and must never create the table itself (nothing in this app calls
# create_all). Rows are written by `import_runs` outside the scan write lock.
class ImportRun(SQLModel, table=True):
  __tablename__ = "import_run"
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  kind: str = Field(default="mount")
  status: str
  mode: Optional[str] = None
  root: Optional[str] = None
  started_at: float
  finished_at: Optional[float] = None
  registered: int = Field(default=0)
  known: int = Field(default=0)
  ignored: int = Field(default=0)
  failed: int = Field(default=0)
  rejected: int = Field(default=0)
  reason: Optional[str] = None
  errors_json: str = Field(default="[]")


# oidc_identities is created by migration 010; this class only describes it for
# typed queries and must never create the table itself. The unique (issuer,
# subject) index is the only thing that binds a provider principal to an
# account: matching on username or email instead would be an account-takeover
# path, so there is deliberately no other lookup key.
class OidcIdentity(SQLModel, table=True):
  __tablename__ = "oidc_identities"
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  issuer: str
  subject: str
  user_id: str = Field(foreign_key="users.id", index=True)
  created_at: str
