"""Mounted-import run summaries, details and listings (Mf-avo9 split)."""

from typing import List, Optional

from pydantic import BaseModel

__all__ = [
  "ImportRunDetailOut",
  "ImportRunListOut",
  "ImportRunSummaryOut",
]


class ImportRunSummaryOut(BaseModel):
  """One mounted-import run; counters are the raw persisted scan counters.

  `discovered` is their sum and `skipped` is `known + ignored`; `rejected` is
  the oversize subset of `ignored`, surfaced separately. The summary omits
  per-file errors, which only the detail response carries.
  """

  id: str
  status: str
  mode: Optional[str]
  root: Optional[str]
  reason: Optional[str]
  started_at: float
  finished_at: Optional[float]
  registered: int
  known: int
  ignored: int
  failed: int
  rejected: int
  discovered: int
  skipped: int


class ImportRunDetailOut(ImportRunSummaryOut):
  errors: List[str] = []


class ImportRunListOut(BaseModel):
  runs: List[ImportRunSummaryOut]
  total: int
  limit: int
  offset: int
