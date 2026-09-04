import uuid
from typing import Optional
from sqlalchemy import CheckConstraint, UniqueConstraint
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
  prepared_machine_id: Optional[str] = Field(
    default=None, foreign_key="machineprofile.id", index=True
  )
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


class Project(SQLModel, table=True):
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  name: str
  notes: Optional[str] = None
  creator: Optional[str] = None
  source_url: Optional[str] = None
  license: Optional[str] = None
  tags_json: str = Field(default="[]")
  created_at: str
  updated_at: str
  deleted_at: Optional[str] = Field(default=None, index=True)


class ProjectMembership(SQLModel, table=True):
  project_id: str = Field(foreign_key="project.id", primary_key=True)
  asset_id: str = Field(foreign_key="asset.id", primary_key=True)
  created_at: str


class ProjectRelationship(SQLModel, table=True):
  __table_args__ = (
    UniqueConstraint(
      "project_id",
      "source_asset_id",
      "target_asset_id",
      "kind",
      name="idx_projectrelationship_canonical_unique",
    ),
    CheckConstraint(
      "kind IN ('derived_from', 'documentation_for', 'component_of')",
      name="ck_projectrelationship_kind",
    ),
    CheckConstraint(
      "source_asset_id <> target_asset_id",
      name="ck_projectrelationship_distinct_endpoints",
    ),
  )
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  project_id: str = Field(foreign_key="project.id", index=True)
  source_asset_id: str = Field(foreign_key="asset.id", index=True)
  target_asset_id: str = Field(foreign_key="asset.id", index=True)
  kind: str
  created_at: str


class MachineProfile(SQLModel, table=True):
  __table_args__ = (
    CheckConstraint(
      "category IN ('fdm_printer', 'resin_printer', 'laser', 'cnc', 'pcb', 'other')",
      name="ck_machineprofile_category",
    ),
  )
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  name: str
  category: str = Field(index=True)
  manufacturer: Optional[str] = None
  model: Optional[str] = None
  location: Optional[str] = None
  notes: Optional[str] = None
  created_at: str
  updated_at: str = Field(index=True)
  archived_at: Optional[str] = Field(default=None, index=True)


class ArtifactMachine(SQLModel, table=True):
  asset_id: str = Field(foreign_key="asset.id", primary_key=True)
  machine_id: str = Field(foreign_key="machineprofile.id", primary_key=True)
  created_at: str


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
  prepared_machine_id: Optional[str] = Field(
    default=None, foreign_key="machineprofile.id", index=True
  )
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


class UserAccount(SQLModel, table=True):
  __tablename__ = "useraccount"
  __table_args__ = (
    UniqueConstraint(
      "username_normalized",
      name="idx_useraccount_username_normalized_unique",
    ),
    CheckConstraint("enabled IN (0, 1)", name="ck_useraccount_enabled"),
    CheckConstraint(
      "password_change_required IN (0, 1)",
      name="ck_useraccount_password_change_required",
    ),
    CheckConstraint(
      "password_policy_version >= 1",
      name="ck_useraccount_password_policy_version",
    ),
    CheckConstraint(
      "role IN ('administrator', 'member', 'viewer')",
      name="ck_useraccount_role",
    ),
    CheckConstraint("mfa_enabled IN (0, 1)", name="ck_useraccount_mfa_enabled"),
  )
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  username: str
  username_normalized: str = Field(index=True)
  display_name: str
  password_hash: str
  enabled: bool = Field(default=True, index=True)
  password_policy_version: int = Field(default=1)
  password_change_required: bool = Field(default=False)
  role: str = Field(default="viewer", index=True)
  mfa_enabled: bool = Field(default=False, index=True)
  created_at: str
  updated_at: str
  last_login_at: Optional[str] = None


class BrowserSession(SQLModel, table=True):
  __tablename__ = "browsersession"
  __table_args__ = (
    UniqueConstraint(
      "secret_digest",
      name="idx_browsersession_secret_digest_unique",
    ),
  )
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  user_id: str = Field(foreign_key="useraccount.id", index=True)
  secret_digest: str
  created_at: int
  last_seen_at: int
  idle_expires_at: int = Field(index=True)
  absolute_expires_at: int = Field(index=True)
  idle_ttl_seconds: int
  reauthenticated_at: int = Field(default=0, index=True)
  revoked_at: Optional[int] = Field(default=None, index=True)
  client_address: Optional[str] = None
  user_agent: Optional[str] = None


class WebAuthnCredential(SQLModel, table=True):
  __tablename__ = "webauthncredential"
  __table_args__ = (
    UniqueConstraint(
      "credential_id",
      name="idx_webauthncredential_credential_id_unique",
    ),
    CheckConstraint("sign_count >= 0", name="ck_webauthncredential_sign_count"),
    CheckConstraint(
      "device_type IN ('single_device', 'multi_device')",
      name="ck_webauthncredential_device_type",
    ),
    CheckConstraint("backed_up IN (0, 1)", name="ck_webauthncredential_backed_up"),
  )
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  user_id: str = Field(foreign_key="useraccount.id", index=True)
  credential_id: str
  public_key: str
  sign_count: int = Field(default=0)
  transports_json: str = Field(default="[]")
  device_type: str
  backed_up: bool = Field(default=False)
  label: str
  created_at: str = Field(index=True)
  last_used_at: Optional[str] = Field(default=None, index=True)


class WebAuthnChallenge(SQLModel, table=True):
  __tablename__ = "webauthnchallenge"
  __table_args__ = (
    UniqueConstraint(
      "challenge_digest",
      name="idx_webauthnchallenge_challenge_digest_unique",
    ),
    UniqueConstraint(
      "transaction_digest",
      name="idx_webauthnchallenge_transaction_digest_unique",
    ),
    CheckConstraint(
      "purpose IN ('registration', 'authentication', 'reauthentication')",
      name="ck_webauthnchallenge_purpose",
    ),
    CheckConstraint(
      "attempt_count BETWEEN 0 AND 5",
      name="ck_webauthnchallenge_attempt_count",
    ),
  )
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  user_id: str = Field(foreign_key="useraccount.id", index=True)
  purpose: str = Field(index=True)
  challenge_digest: str
  session_id: Optional[str] = Field(default=None, foreign_key="browsersession.id", index=True)
  transaction_digest: Optional[str] = None
  rp_id: str
  origin: str
  created_at: int
  expires_at: int = Field(index=True)
  consumed_at: Optional[int] = Field(default=None, index=True)
  attempt_count: int = Field(default=0)


class AuthenticatorPolicy(SQLModel, table=True):
  __tablename__ = "authenticatorpolicy"
  __table_args__ = (
    CheckConstraint("id = 'global'", name="ck_authenticatorpolicy_singleton"),
    CheckConstraint(
      "mode IN ('optional', 'require_administrators', 'require_all')",
      name="ck_authenticatorpolicy_mode",
    ),
  )
  id: str = Field(default="global", primary_key=True)
  mode: str = Field(default="optional")
  updated_at: str
  updated_by_user_id: Optional[str] = Field(default=None, foreign_key="useraccount.id")


class AuditEvent(SQLModel, table=True):
  __tablename__ = "auditevent"
  __table_args__ = (
    CheckConstraint(
      "result IN ('success', 'denied', 'failure')",
      name="ck_auditevent_result",
    ),
  )
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  occurred_at: str = Field(index=True)
  correlation_id: str = Field(index=True)
  actor_user_id: Optional[str] = Field(default=None, index=True)
  actor_username: Optional[str] = None
  actor_role: Optional[str] = None
  action: str = Field(index=True)
  result: str = Field(index=True)
  object_type: Optional[str] = None
  object_id: Optional[str] = None
  method: Optional[str] = None
  route: Optional[str] = None
  permission: Optional[str] = None
  status_code: Optional[int] = None
  source_address: Optional[str] = None
  details_json: str = Field(default="{}")


class RecoveryMarker(SQLModel, table=True):
  __tablename__ = "recoverymarker"
  id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
  kind: str = Field(index=True)
  created_at: str = Field(index=True)
  details_json: str = Field(default="{}")
  processed_at: Optional[str] = Field(default=None, index=True)


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
