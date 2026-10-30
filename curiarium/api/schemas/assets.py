"""Assets, their metadata edits and the bulk download request (Mf-avo9 split)."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from metadata_validation import normalise_creator, normalise_name, normalise_notes

__all__ = [
  "AssetCreate",
  "AssetFolderUpdate",
  "AssetMetaUpdate",
  "AssetOut",
  "AssetRename",
  "DownloadRequest",
  "PreparedPrintOut",
  "SnapshotNoticeOut",
  "TagUpdate",
]


class AssetCreate(BaseModel):
  title: Optional[str] = None
  notes: Optional[str] = None
  tags: List[str] = []


class PreparedPrintOut(BaseModel):
  printer: Optional[str] = None
  material: Optional[str] = None
  nozzle_mm: Optional[float] = None
  layer_height_mm: Optional[float] = None
  estimated_seconds: Optional[int] = None
  slicer: str = "unknown"
  format: Optional[str] = None
  removable: bool = False


class SnapshotNoticeOut(BaseModel):
  """What a destructive operation will do about a pre-operation snapshot.

  Descriptive, never prose: the dialogs build the sentence. `pattern` is the only
  promise a preview can keep, because the exact name is minted at create time;
  `name` is filled in only on the response to the mutation itself.
  """

  reason: str                                      # predelete | prepurge | prebulk
  policy: Literal["warn", "strict"]
  capability: Literal["available", "unavailable"]
  action: Literal["snapshot", "proceed_without", "refuse"]
  pattern: str                                     # <YYYYmmddTHHMMSSZ>-<reason>-<6 hex>
  name: Optional[str] = None                       # exact name once taken
  detail: Optional[str] = None                     # why it is unavailable, when it is


class AssetOut(BaseModel):
  id: str
  name: str
  filename: str
  mime: str
  size: int
  title: Optional[str]
  notes: Optional[str]
  creator: Optional[str]
  collection: Optional[str] = Field(
    json_schema_extra={"deprecated": True},
    description="Legacy v5.1 metadata; inert since Mf-aoyv. Use Projects. Kept in responses for old clients.",
  )
  tags: List[str]
  url: str
  thumb_url: Optional[str]
  folder_id: Optional[str]
  storage_path: Optional[str]
  missing_since: Optional[str] = None
  supporting_file_count: int = 0
  # A mounted reference points at a file outside the storage root; deleting its
  # row never touches those bytes, so a delete confirmation has to say so.
  is_reference: bool = False
  prepared_print: Optional[PreparedPrintOut] = None
  slicer_url: Optional[str] = None
  slicer_filename: Optional[str] = None


class DownloadRequest(BaseModel):
  asset_ids: Optional[List[str]] = None
  tag: Optional[str] = None
  folder_id: Optional[str] = None
  project_id: Optional[str] = None
  filename: Optional[str] = None


class TagUpdate(BaseModel):
  tags: List[str]


class AssetMetaUpdate(BaseModel):
  """The single-asset metadata edit; validation happens before any rename.

  An absent field is unchanged, a blank string clears (the legacy
  ``strip() or None`` contract) and an explicit ``null`` is also unchanged:
  the before-validator drops null keys so only a provided value can edit a
  column. `collection` keeps that legacy behaviour and is not validated because
  ADR 0003 retires it.
  """

  name: Optional[str] = None
  title: Optional[str] = None
  notes: Optional[str] = None
  creator: Optional[str] = None
  collection: Optional[str] = Field(
    default=None,
    json_schema_extra={"deprecated": True},
    description="Legacy v5.1 metadata; inert since Mf-aoyv. Use Projects. Still accepted so old clients keep working.",
  )

  @model_validator(mode="before")
  @classmethod
  def ignore_explicit_nulls(cls, data):
    """Treat ``{"field": null}`` as absent; only a typed value is an edit."""
    if isinstance(data, dict):
      return {key: value for key, value in data.items() if value is not None}
    return data

  @field_validator("name", mode="before")
  @classmethod
  def validate_name(cls, value: object) -> Optional[str]:
    return normalise_name(value, "name")

  @field_validator("title", mode="before")
  @classmethod
  def validate_title(cls, value: object) -> Optional[str]:
    return normalise_name(value, "title")

  @field_validator("notes", mode="before")
  @classmethod
  def validate_notes(cls, value: object) -> Optional[str]:
    return normalise_notes(value)

  @field_validator("creator", mode="before")
  @classmethod
  def validate_creator(cls, value: object) -> Optional[str]:
    return normalise_creator(value)


class AssetRename(BaseModel):
  filename: str


class AssetFolderUpdate(BaseModel):
  folder_id: Optional[str] = None
