"""Login, refresh and account administration contracts (Mf-avo9 split)."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

__all__ = [
  "LoginRequest",
  "LoginResponse",
  "MeOut",
  "RefreshRequest",
  "UserCreate",
  "UserOut",
  "UserUpdate",
]


class LoginRequest(BaseModel):
  username: str
  password: str


class LoginResponse(BaseModel):
  token: str
  expires_in: int
  refresh_token: str
  token_type: str = "bearer"


class RefreshRequest(BaseModel):
  refresh_token: Optional[str] = None


class UserCreate(BaseModel):
  username: str
  password: str
  email: Optional[str] = None
  role: str = "viewer"


class UserUpdate(BaseModel):
  """Fields an administrator may change on an account (Mf-2nbc).

  Both are optional so `{"disabled": true}` keeps working, and an empty patch
  is rejected instead of silently changing nothing.
  """

  model_config = ConfigDict(extra="forbid")
  disabled: Optional[bool] = None
  role: Optional[str] = None

  @model_validator(mode="after")
  def require_a_change(self) -> "UserUpdate":
    if self.disabled is None and self.role is None:
      raise ValueError("provide disabled and/or role")
    return self


class UserOut(BaseModel):
  id: str
  username: str
  email: Optional[str]
  role: str
  disabled: bool
  created_at: str
  updated_at: str


class MeOut(BaseModel):
  id: Optional[str]
  username: str
  email: Optional[str]
  role: str
  disabled: bool
  kind: str
