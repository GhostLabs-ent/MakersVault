"""Mount-import and storage-template settings (Mf-avo9 split)."""

from typing import List, Optional

from pydantic import BaseModel

__all__ = [
  "MountImportSettings",
  "MountImportSettingsOut",
  "StorageCapabilitiesOut",
  "StorageSettings",
  "StorageSettingsOut",
  "StorageVolumeCapability",
]


class MountImportSettings(BaseModel):
  enabled: bool
  copy_files: bool


class MountImportSettingsOut(MountImportSettings):
  path: Optional[str] = None


class StorageSettings(BaseModel):
  template: str


class StorageVolumeCapability(BaseModel):
  roles: List[str]
  path: str
  fstype: str
  mount_point: str
  snapshot_method: str
  usable: bool
  reason: str


class StorageCapabilitiesOut(BaseModel):
  volumes: List[StorageVolumeCapability]


class StorageSettingsOut(BaseModel):
  template: str
  default_template: str
  allowed_tokens: List[str]
  sample_path: str
  moved: int = 0
  skipped: int = 0
