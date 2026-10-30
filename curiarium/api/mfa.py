"""TOTP enrolments and one-time recovery codes (Mf-lg02).

Two-factor is only useful if the second factor is as hard to extract from a
database dump as the password hash, so both secrets here are treated that way:

* the TOTP seed is a *decryptable* blob, not a digest: HOTP has to feed the raw
  seed to HMAC, so it cannot be hashed. It is encrypted with AES-256-GCM under a
  subkey of `AUTH_SECRET`, so a copy of the database alone cannot mint codes.
* a recovery code is only ever stored as an HMAC keyed with a different subkey.
  A 50-bit code is short enough that a bare sha256 is offline-crackable from a
  dump; the pepper lives in `AUTH_SECRET`, never in the table.

Neither ciphertext nor HMAC is reversible into the plaintext, and nothing here
logs, returns or audits a secret, a code, or a digest of either.

Single use is enforced with guarded UPDATEs against the stored state
(`totp_last_step` and `mfa_recovery_codes.used_at`), never a read-modify-write,
so two concurrent requests presenting the same code cannot both win. For TOTP
the guarded column is the *matched* counter, so one code can be accepted at most
once in its whole ±1-step window. This module owns the transaction boundary for
callers: it adds and flushes, and the router commits, because the audit row must
land with the change it describes.
"""

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, func, or_, update
from sqlmodel import Session, select

import auth
from models import MfaRecoveryCode, User

TOTP_DIGITS = 6
TOTP_PERIOD = 30
TOTP_ALGORITHM = "SHA1"  # RFC 6238 default; every authenticator app supports it
TOTP_SKEW_STEPS = 1  # ±1 step = ±30 s
SECRET_BYTES = 20  # 160-bit seed, RFC 4226 §4 recommendation
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/L/O/0/1
RECOVERY_CODE_LENGTH = 10  # 50 bits ≈ 1.1e15; drawn from secrets.randbelow
RECOVERY_CODE_GROUPS = 2  # displayed as XXXXX-XXXXX
MFA_REQUIRE_ADMIN_KEY = "mfa_require_admin"
# Domain-separated subkeys, derived exactly like `auth.file_grant_key()`.
SEED_KEY_INFO = b"curiarium/mfa-seed/v1"
RECOVERY_KEY_INFO = b"curiarium/mfa-recovery/v1"


def _now() -> float:
  """The module's one clock seam, so a test can freeze it without sleeping."""
  return time.time()


def now_iso() -> str:
  """Epoch-seconds formatted like `accounts._now_iso`, for `totp_enrolled_at`."""
  return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seed_key() -> bytes:
  """Derive the seed-encryption subkey, domain-separated from every other use."""
  return hmac.new(auth.AUTH_SECRET.encode("utf-8"), SEED_KEY_INFO, hashlib.sha256).digest()


def recovery_key() -> bytes:
  """Derive the recovery-code pepper, distinct from the seed key."""
  return hmac.new(auth.AUTH_SECRET.encode("utf-8"), RECOVERY_KEY_INFO, hashlib.sha256).digest()


def encrypt_seed(secret: bytes) -> str:
  """AES-256-GCM the seed with a fresh nonce; base64url over nonce|ciphertext."""
  nonce = secrets.token_bytes(12)
  blob = AESGCM(seed_key()).encrypt(nonce, secret, None)
  return base64.urlsafe_b64encode(nonce + blob).decode("ascii")


def decrypt_seed(blob: str) -> Optional[bytes]:
  """Inverse of `encrypt_seed`; None means fail closed, never an exception.

  A rotated `AUTH_SECRET` makes every stored seed undecryptable. That is the
  same consequence as rotating it for sessions, and it must not surface as a
  500 through a login request, so a bad tag is reported as "no seed here".
  """
  try:
    raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    nonce, ciphertext = raw[:12], raw[12:]
    return AESGCM(seed_key()).decrypt(nonce, ciphertext, None)
  except (InvalidTag, ValueError, binascii.Error):
    return None


def new_secret() -> bytes:
  """A fresh 160-bit seed, from the OS CSPRNG."""
  return secrets.token_bytes(SECRET_BYTES)


def base32_secret(secret: bytes) -> str:
  """Unpadded uppercase base32, the spelling authenticator apps expect."""
  return base64.b32encode(secret).decode("ascii").rstrip("=")


def parse_secret(raw: str) -> Optional[bytes]:
  """Reverse of `base32_secret`; None on junk instead of raising."""
  cleaned = (raw or "").strip().upper().replace(" ", "")
  if not cleaned:
    return None
  try:
    padding = "=" * (-len(cleaned) % 8)
    return base64.b32decode(cleaned + padding)
  except (binascii.Error, ValueError):
    return None


def hotp(secret: bytes, counter: int) -> str:
  """RFC 4226 HOTP with SHA1 and dynamic truncation, zero-padded to 6 digits."""
  mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
  offset = mac[-1] & 0x0F
  truncated = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
  return str(truncated % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def totp_at(secret: bytes, step: int) -> str:
  """RFC 6238 TOTP for one time step."""
  return hotp(secret, step)


def current_step(now: Optional[float] = None) -> int:
  """The wall-clock time step, independent of which skew offset matched."""
  moment = _now() if now is None else now
  return int(moment // TOTP_PERIOD)


def matching_step(secret: bytes, code: str, *, now: Optional[float] = None) -> Optional[int]:
  """The counter a submitted code matches inside the ±1-step window, or None.

  Offsets are tried `-1, 0, +1` in that order and compared in constant time, so
  the first hit is the one a caller burns. The return value is always the code's
  own counter `C = step + offset`, never the wall-clock step: a code for counter
  `C` matches at wall steps `C-1`, `C` and `C+1` and yields `C` each time.
  Callers burn that value, so re-presenting the same code is refused in every
  bucket and the window is tolerance for clock error only - see
  `consume_totp_step`.
  """
  step = current_step(now)
  submitted = (code or "").strip()
  for offset in range(-TOTP_SKEW_STEPS, TOTP_SKEW_STEPS + 1):
    if hmac.compare_digest(hotp(secret, step + offset), submitted):
      return step + offset
  return None


def consume_totp_step(session: Session, user_id: str, step: int) -> bool:
  """Burn one time step for `user_id`; the ONE place `totp_last_step` is written.

  Callers pass the counter `matching_step` returned - the accepted code's own
  counter, never the wall-clock bucket. A code is accepted only if this guarded
  UPDATE affects exactly one row, so a second presentation of that code loses
  even under concurrency, in whichever bucket it arrives. The guard is
  `totp_last_step < step`, so the column is monotone: it can never be rolled
  back to an earlier counter by a later request.
  """
  result = session.execute(
    update(User)
    .where(
      User.id == user_id,
      or_(User.totp_last_step.is_(None), User.totp_last_step < step),
    )
    .values(totp_last_step=step)
    .execution_options(synchronize_session=False)
  )
  return result.rowcount == 1


def new_recovery_code() -> str:
  """One unformatted recovery code, drawn from the ambiguity-free alphabet."""
  return "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))


def format_recovery_code(raw: str) -> str:
  """Display form: split into `RECOVERY_CODE_GROUPS` dash-separated chunks."""
  size = max(1, len(raw) // RECOVERY_CODE_GROUPS)
  return "-".join(raw[index : index + size] for index in range(0, len(raw), size))


def normalize_recovery_code(raw: str) -> str:
  """Uppercase and strip everything that is not alphanumeric.

  Codes are shown with a dash and users re-type them with spaces or lower case;
  normalising means only the characters carry entropy, not the presentation.
  """
  return "".join(char for char in (raw or "").upper() if char.isalnum())


def hash_recovery_code(code: str) -> str:
  """HMAC-peppered digest; never a bare sha256 (see the module docstring)."""
  return hmac.new(recovery_key(), normalize_recovery_code(code).encode("utf-8"), hashlib.sha256).hexdigest()


def create_recovery_codes(session: Session, user_id: str) -> list[str]:
  """Replace nothing and insert a fresh set; returns the plaintext once.

  The caller decides whether old rows are deleted first (regeneration) or not
  (first enrolment). The plaintext is the return value only: it is never stored.
  """
  created_at = now_iso()
  codes: list[str] = []
  for _ in range(RECOVERY_CODE_COUNT):
    raw = new_recovery_code()
    codes.append(format_recovery_code(raw))
    session.add(
      MfaRecoveryCode(user_id=user_id, code_hmac=hash_recovery_code(raw), created_at=created_at)
    )
  session.flush()
  return codes


def delete_recovery_codes(session: Session, user_id: str) -> int:
  """Delete every recovery row for a user; returns how many were removed."""
  result = session.execute(
    delete(MfaRecoveryCode)
    .where(MfaRecoveryCode.user_id == user_id)
    .execution_options(synchronize_session=False)
  )
  return result.rowcount


def remaining_recovery_codes(session: Session, user_id: str) -> int:
  """How many unused recovery codes this account still has."""
  statement = (
    select(func.count())
    .select_from(MfaRecoveryCode)
    .where(MfaRecoveryCode.user_id == user_id, MfaRecoveryCode.used_at.is_(None))
  )
  return int(session.exec(statement).one())


def consume_recovery_code(session: Session, user_id: str, code: str) -> bool:
  """Mark one recovery code used; True only for the one request that won it.

  The single-use guard is the `used_at IS NULL` predicate on the UPDATE, so a
  lost read-modify-write cannot let two requests spend the same code.
  """
  result = session.execute(
    update(MfaRecoveryCode)
    .where(
      MfaRecoveryCode.user_id == user_id,
      MfaRecoveryCode.code_hmac == hash_recovery_code(code),
      MfaRecoveryCode.used_at.is_(None),
    )
    .values(used_at=int(_now()))
    .execution_options(synchronize_session=False)
  )
  return result.rowcount == 1


def otpauth_uri(*, secret: bytes, username: str, issuer: str = "Curiarium") -> str:
  """The standard key-URI an authenticator app scans."""
  label = f"{quote(issuer)}:{quote(username)}"
  return (
    f"otpauth://totp/{label}?secret={base32_secret(secret)}"
    f"&issuer={quote(issuer)}&algorithm={TOTP_ALGORITHM}&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
  )


def user_is_enrolled(user: Optional[User]) -> bool:
  """True when this account has a stored TOTP seed."""
  return bool(user is not None and user.totp_secret)


def mfa_ok(session_row) -> bool:
  """True when this session has completed a second factor."""
  return session_row is not None and session_row.mfa_verified_at is not None
