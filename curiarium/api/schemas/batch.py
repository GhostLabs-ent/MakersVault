"""The batch endpoints' request/response contracts (Mf-avo9 split)."""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from metadata_validation import normalise_creator, normalise_notes

from .assets import AssetOut, SnapshotNoticeOut

__all__ = [
  "AssetDeletePreviewOut",
  "BatchDeleteOut",
  "BatchDeleteRequest",
  "BatchFailure",
  "BatchFolderOut",
  "BatchFolderRequest",
  "BatchMetaOut",
  "BatchMetaRequest",
  "BatchTagsOut",
  "BatchTagsRequest",
]


class AssetDeletePreviewOut(BaseModel):
  """What a bulk delete would remove, and what it would do about a snapshot."""

  assets: int
  files: int
  bytes: int
  snapshot: Optional[SnapshotNoticeOut] = None


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


class BatchMetaRequest(BaseModel):
  """A batch creator/notes edit (Mf-pnc2).

  Only the two audit-exempt metadata fields are here. `title`/`name` are
  deliberately absent: title is a rename alias, so a batch payload carrying it
  would mass-rename files on disk. An absent field is unchanged, an explicit
  ``null`` or a blank string clears, which diverges from the single endpoint's
  "null is unchanged" only because a batch has no meaningful "typed nothing".
  Values are validated once for the whole request, like `BatchFolderRequest`'s
  `folder_id`; a bad value fails the request, not one item per asset.
  """

  model_config = ConfigDict(extra="forbid")
  asset_ids: List[str] = []
  creator: Optional[str] = None
  notes: Optional[str] = None

  @field_validator("creator", mode="before")
  @classmethod
  def validate_creator(cls, value: object) -> Optional[str]:
    return normalise_creator(value)

  @field_validator("notes", mode="before")
  @classmethod
  def validate_notes(cls, value: object) -> Optional[str]:
    return normalise_notes(value)


class BatchMetaOut(BaseModel):
  updated: List[AssetOut] = []
  failed: List[BatchFailure] = []


class BatchDeleteRequest(BaseModel):
  asset_ids: List[str] = []
  # Optional so a missing confirmation is a hand-rolled 400 in the route, not a
  # FastAPI 422; the client sends the number of rows it displayed.
  confirm_count: Optional[int] = None


class BatchDeleteOut(BaseModel):
  deleted: List[str] = []
  failed: List[BatchFailure] = []
