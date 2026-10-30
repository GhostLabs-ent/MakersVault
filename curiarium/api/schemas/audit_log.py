"""Audit trail events and their paged listing (Mf-avo9 split)."""

from typing import List, Optional

from pydantic import BaseModel

__all__ = [
  "AuditEventOut",
  "AuditListOut",
]


class AuditEventOut(BaseModel):
  """One audit row; `detail` is parsed from the stored JSON, never a secret."""

  id: str
  created_at: str
  actor: str
  actor_user_id: Optional[str]
  actor_role: str
  actor_kind: str
  action: str
  target: str
  detail: Optional[dict]
  request_id: str
  method: str
  path: str


class AuditListOut(BaseModel):
  events: List[AuditEventOut]
  total: int
  limit: int
  offset: int
