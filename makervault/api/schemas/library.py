"""Library scan status (Mf-avo9 split)."""

from typing import List, Optional

from pydantic import BaseModel

__all__ = [
  "LibraryScanStatusOut",
]


class LibraryScanStatusOut(BaseModel):
  running: bool
  started_at: Optional[float] = None
  finished_at: Optional[float] = None
  registered: int = 0
  known: int = 0
  ignored: int = 0
  missing: int = 0
  failed: int = 0
  errors: List[str] = []
