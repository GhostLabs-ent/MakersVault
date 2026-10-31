"""Login, refresh and account administration contracts (Mf-avo9 split)."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, model_validator

__all__ = [
  "LoginRequest",
  "LoginResponse",
  "MeOut",
  "OidcExchangeRequest",
  "OidcStatusOut",
  "PasswordResetRequest",
  "RefreshRequest",
  "SessionOut",
  "UserCreate",
  "UserOut",
  "UserUpdate",
]


class LoginRequest(BaseModel):
  username: str
  password: str


class LoginResponse(BaseModel):
  """A completed login, or the one step of it that is still outstanding.

  Password-only and OIDC logins keep their existing body (`token`, `expires_in`,
  `refresh_token`, `token_type`) and report `mfa_required: false`. When the
  account has a second factor, the same shape is returned with only
  `mfa_required: true` and `mfa_token` set; the token fields are optional so
  that challenge validates. The client never has to guess which body it got.
  """

  token: Optional[str] = None
  expires_in: Optional[int] = None
  refresh_token: Optional[str] = None
  token_type: str = "bearer"
  mfa_required: bool = False
  mfa_token: Optional[str] = None


class RefreshRequest(BaseModel):
  refresh_token: Optional[str] = None


class SessionOut(BaseModel):
  """One active session, as the owner or an administrator may see it.

  Timestamps are epoch seconds because the client renders relative times
  ("last used 3 minutes ago"), which would need a second parse from an ISO
  string. Neither refresh hash is ever part of this contract: that is a
  security boundary, not an oversight, so the model has no field for either and
  the handler never passes one.
  """

  id: str
  username: str
  kind: str
  device: Optional[str]
  user_agent: Optional[str]
  client_ip: Optional[str]
  created_at: int
  last_used_at: int
  current: bool


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


class PasswordResetRequest(BaseModel):
  """An administrator replacing another account's password (Mf-bj51).

  Both flags open a door that was deliberately shut, so neither is the default.
  Set on the request rather than inferred from the target's state, because the
  audit row has to say which door was opened and an operator has to mean it.
  """

  model_config = ConfigDict(extra="forbid")
  password: str
  allow_disabled: bool = False
  allow_sso: bool = False


class UserOut(BaseModel):
  """One account as an administrator may see it; never a password hash.

  `auth_source` describes the *password credential*: `sso` is exactly
  `password_hash IS NULL` (the test `routers/mfa.py` already uses), so `local`
  means this account can sign in with a password. `oidc_issuer`/`oidc_subject`
  describe a different fact - the *binding* to a provider identity.

  They are not either/or. An `allow_sso` password reset gives an
  SSO-provisioned account a local password as well, which is the operator's
  escape hatch when the identity provider is down (that is why
  `accounts.create_sso_user` refuses to mint an admin); such an account is
  `auth_source: "local"` *and* carries a binding, and the client renders both.
  """

  id: str
  username: str
  email: Optional[str]
  role: str
  disabled: bool
  auth_source: Literal["local", "sso"] = "local"
  oidc_issuer: Optional[str] = None
  oidc_subject: Optional[str] = None
  created_at: str
  updated_at: str


class MeOut(BaseModel):
  id: Optional[str]
  username: str
  email: Optional[str]
  role: str
  disabled: bool
  kind: str


class OidcStatusOut(BaseModel):
  """Whether the client should offer the SSO button; nothing else.

  Deliberately carries no provider name, issuer or error text: this route is
  public, and the only decision the browser has to make is whether to draw a
  second button.
  """
  enabled: bool


class OidcExchangeRequest(BaseModel):
  """The single-use handoff code the callback parked, taken from the fragment."""
  model_config = ConfigDict(extra="forbid")
  code: str
