"""Two-factor enrolment and challenge contracts (Mf-lg02).

Every response that carries a secret, a one-time code or a recovery code is
served with `Cache-Control: no-store` by its handler; this module only states
the shape, so a field here is a deliberate part of the boundary. No model has a
field for a stored seed, a recovery-code hash, or a TOTP code after it was
consumed - the shapes themselves are the "plaintext appears once" rule.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

__all__ = [
  "MfaConfirmOut",
  "MfaConfirmRequest",
  "MfaEnrolOut",
  "MfaEnrolRequest",
  "MfaPasswordRequest",
  "MfaPolicyOut",
  "MfaPolicyUpdate",
  "MfaRecoveryCodesOut",
  "MfaStatusOut",
  "MfaStepUpOut",
  "MfaStepUpRequest",
  "MfaVerifyRequest",
]


class MfaStatusOut(BaseModel):
  """The caller's own second-factor state, plus the deployment policy.

  `can_enrol` is false for an enrolled account and for an SSO-only one (no
  local password to confirm): the client uses it to decide whether to offer the
  enrolment panel at all.
  """

  enrolled: bool
  enrolled_at: Optional[str]
  recovery_codes_remaining: int
  require_admin: bool
  can_enrol: bool


class MfaEnrolRequest(BaseModel):
  password: str


class MfaEnrolOut(BaseModel):
  secret: str
  otpauth_uri: str
  digits: int
  period: int
  algorithm: str


class MfaConfirmRequest(BaseModel):
  password: str
  secret: str
  code: str


class MfaConfirmOut(BaseModel):
  recovery_codes: List[str]


class MfaVerifyRequest(BaseModel):
  mfa_token: str
  code: str


class MfaStepUpRequest(BaseModel):
  code: str


class MfaStepUpOut(BaseModel):
  mfa_verified: bool


class MfaPasswordRequest(BaseModel):
  """The sudo gate every mutating self-service route requires."""

  password: str


class MfaRecoveryCodesOut(BaseModel):
  recovery_codes: List[str]


class MfaPolicyOut(BaseModel):
  require_admin: bool


class MfaPolicyUpdate(BaseModel):
  model_config = ConfigDict(extra="forbid")
  require_admin: bool
