"""Database accounts: argon2id passwords and user administration.

Callers own the transaction: every function here adds or mutates rows and
flushes, but never commits. That lets the caller create the first user and
revoke the bootstrap sessions in one transaction (see `main.create_user`).

`password_hash` never leaves this module in a response: `schemas.UserOut` and
`schemas.MeOut` have no such field.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from models import User

ADMIN_ROLE = "admin"
EDITOR_ROLE = "editor"
DEFAULT_ROLE = "viewer"
ROLES = (ADMIN_ROLE, EDITOR_ROLE, DEFAULT_ROLE)
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024

# argon2id with the library defaults (m=65536, t=3, p=4): a login costs ~50 ms,
# which is also why an unknown username has to run a dummy verify to keep the
# response time from telling attackers which accounts exist.
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("makervault-dummy-password")


class AccountError(Exception):
    """Base class for user-administration failures that map to one HTTP status."""

    status_code = 422


class InvalidAccount(AccountError):
    """The submitted user data is unusable."""

    status_code = 422


class DuplicateAccount(AccountError):
    """The username or email address is already taken."""

    status_code = 409


class UnknownAccount(AccountError):
    """No user with that id."""

    status_code = 404


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password_hash: Optional[str], password: str) -> bool:
    """Constant-time argon2 verification; a malformed or missing hash fails closed."""
    if not password_hash:
        return False
    try:
        return hasher.verify(password_hash, password)
    except Argon2Error:
        return False


def dummy_verify() -> None:
    """Spend the same time a real verification would, for unknown usernames."""
    try:
        hasher.verify(DUMMY_HASH, "not-the-password")
    except Argon2Error:
        pass


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash used weaker parameters than we use now."""
    try:
        return hasher.check_needs_rehash(password_hash)
    except Argon2Error:
        return True


def _clean_username(username: str) -> str:
    cleaned = (username or "").strip()
    if not cleaned:
        raise InvalidAccount("username must not be empty")
    return cleaned


def _clean_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise InvalidAccount(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise InvalidAccount(f"password must be at most {MAX_PASSWORD_LENGTH} characters")
    return password


def _clean_role(role: Optional[str]) -> str:
    cleaned = (role or DEFAULT_ROLE).strip().lower()
    if cleaned not in ROLES:
        raise InvalidAccount("role must be one of: " + ", ".join(ROLES))
    return cleaned


def _clean_email(email: Optional[str]) -> Optional[str]:
    cleaned = (email or "").strip()
    return cleaned or None


def users_table_empty(session: Session) -> bool:
    """True when no account exists, i.e. the env credentials still work."""
    return session.exec(select(User.id).limit(1)).first() is None


def get_user(session: Session, user_id: Optional[str]) -> Optional[User]:
    if not user_id:
        return None
    return session.get(User, user_id)


def get_user_by_username(session: Session, username: str) -> Optional[User]:
    """Look the account up case-insensitively, matching the unique index."""
    return session.exec(select(User).where(User.username.collate("NOCASE") == (username or "").strip())).first()


def list_users(session: Session) -> list[User]:
    return list(session.exec(select(User).order_by(User.username.collate("NOCASE"))).all())


def create_user(
    session: Session,
    username: str,
    password: str,
    email: Optional[str] = None,
    role: Optional[str] = DEFAULT_ROLE,
) -> User:
    """Insert a new account; the caller commits (see the module docstring)."""
    cleaned_username = _clean_username(username)
    cleaned_password = _clean_password(password)
    cleaned_role = _clean_role(role)
    cleaned_email = _clean_email(email)
    now = _now_iso()
    user = User(
        id=str(uuid.uuid4()),
        username=cleaned_username,
        email=cleaned_email,
        password_hash=hash_password(cleaned_password),
        role=cleaned_role,
        disabled=0,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise DuplicateAccount("username or email address is already taken") from None
    return user


def set_disabled(session: Session, user_id: str, disabled: bool) -> User:
    """Enable or disable an account; disabled accounts lose every live session."""
    user = get_user(session, user_id)
    if user is None:
        raise UnknownAccount("no such user")
    user.disabled = 1 if disabled else 0
    user.updated_at = _now_iso()
    session.add(user)
    session.flush()
    return user


def update_password_hash(session: Session, user: User, password: str) -> None:
    """Store a fresh hash for a password that still verifies (transparent rehash)."""
    user.password_hash = hash_password(password)
    user.updated_at = _now_iso()
    session.add(user)
    session.flush()
