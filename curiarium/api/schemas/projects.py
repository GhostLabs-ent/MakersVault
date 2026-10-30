"""Projects, their membership changes and removal results (Mf-avo9 split)."""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from .batch import BatchFailure

__all__ = [
  "ProjectAssetsRequest",
  "ProjectIn",
  "ProjectMembersOut",
  "ProjectOut",
  "ProjectRemovalOut",
  "ProjectUpdate",
]


class ProjectIn(BaseModel):
  """Every field a project can be created with; the rest stays read-only.

  An unknown field is a 422, matching `ProjectUpdate`: a silently ignored
  spelling mistake is a client bug the API should not hide.
  """

  model_config = ConfigDict(extra="forbid")
  name: str
  description: Optional[str] = None
  cover_asset_id: Optional[str] = None
  creator: Optional[str] = None
  source_url: Optional[str] = None
  licence: Optional[str] = None
  licence_url: Optional[str] = None
  # The DB CHECK in migration 007 already refuses any other value; this keeps the
  # 422 at the edge instead of letting an invalid insert reach the constraint.
  origin: Literal["own", "imported"] = "own"


class ProjectUpdate(BaseModel):
  """A partial project patch (Mf-bl86).

  Membership of `model_fields_set` decides what changed, not the values: an
  explicit `null` clears `description`, `cover_asset_id` or any provenance field,
  so `{"creator": null}` is a real edit while `{}` is rejected instead of
  silently doing nothing.
  """

  model_config = ConfigDict(extra="forbid")
  name: Optional[str] = None
  description: Optional[str] = None
  cover_asset_id: Optional[str] = None
  creator: Optional[str] = None
  source_url: Optional[str] = None
  licence: Optional[str] = None
  licence_url: Optional[str] = None

  @model_validator(mode="after")
  def require_a_change(self) -> "ProjectUpdate":
    if not self.model_fields_set:
      raise ValueError("provide at least one project field")
    return self


class ProjectOut(BaseModel):
  """One project as read back; `owner_id` and the raw `metadata_json` TEXT stay out.

  `metadata_json` is the parsed print-settings object (`{}` when the column is
  empty or malformed), and `total_size` is the summed size of the members, so a
  landing page renders both without a second request.
  """

  id: str
  name: str
  description: Optional[str]
  creator: Optional[str]
  source_url: Optional[str]
  licence: Optional[str]
  licence_url: Optional[str]
  origin: str
  cover_asset_id: Optional[str] = None
  cover_thumb_url: Optional[str] = None
  asset_count: int = 0
  total_size: int = 0
  metadata_json: dict = {}
  created_at: str
  updated_at: str


class ProjectAssetsRequest(BaseModel):
  asset_ids: List[str] = []


class ProjectMembersOut(BaseModel):
  added: List[str] = []
  skipped: List[str] = []
  failed: List[BatchFailure] = []


class ProjectRemovalOut(BaseModel):
  removed: List[str] = []
  skipped: List[str] = []
  failed: List[BatchFailure] = []
