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
CONTRIBUTOR_ROLE = "contributor"
DEFAULT_ROLE = "viewer"
ROLES = (ADMIN_ROLE, EDITOR_ROLE, CONTRIBUTOR_ROLE, DEFAULT_ROLE)
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024

# argon2id with the library defaults (m=65536, t=3, p=4): a login costs ~50 ms,
# which is also why an unknown username has to run a dummy verify to keep the
# response time from telling attackers which accounts exist.
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("curiarium-dummy-password")


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


class LastAdmin(AccountError):
    """The change would leave no enabled administrator.

    The invariant is "at least one enabled administrator", checked on the state
    the account would have after the change. It is not cosmetic: the env
    break-glass admin only authenticates while the users table is EMPTY (see
    `auth.login`), so once a real account exists a lockout cannot be undone
    through the API.
    """

    status_code = 409


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


def create_sso_user(
    session: Session,
    username: str,
    email: Optional[str] = None,
    role: Optional[str] = DEFAULT_ROLE,
) -> User:
    """Insert an SSO-provisioned account. It has no password, ever.

    `password_hash` stays NULL, so `verify_password(None, ...)` fails closed and
    the account cannot be signed into locally - the identity provider is its only
    door. The role is clamped to what a claim may grant, and an `admin` role is
    refused here as well as in `oidc.role_for_claims`, so a future caller cannot
    reach the escalation this function deliberately has no path to.
    """
    cleaned_username = _clean_username(username)
    cleaned_role = _clean_role(role)
    if cleaned_role == ADMIN_ROLE:
        raise InvalidAccount("an SSO account cannot be an administrator")
    cleaned_email = _clean_email(email)
    now = _now_iso()
    user = User(
        id=str(uuid.uuid4()),
        username=cleaned_username,
        email=cleaned_email,
        password_hash=None,
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
        raise DuplicateAccount("that username or email already exists") from None
    return user


def is_viable_admin(user: User) -> bool:
    """True when this account can still administer the deployment."""
    return user.role == ADMIN_ROLE and not user.disabled


def count_enabled_admins(session: Session, exclude_user_id: Optional[str] = None) -> int:
    """Enabled admin accounts, optionally ignoring one (the account being changed)."""
    stmt = select(User.id).where(User.role == ADMIN_ROLE, User.disabled == 0)
    if exclude_user_id:
        stmt = stmt.where(User.id != exclude_user_id)
    return len(list(session.exec(stmt).all()))


def update_user(
    session: Session,
    user_id: str,
    *,
    disabled: Optional[bool] = None,
    role: Optional[str] = None,
) -> User:
    """Apply a partial change to one account; the caller commits.

    Raises `UnknownAccount` for a missing id, `InvalidAccount` for a role that
    is not in `ROLES`, and `LastAdmin` when the change would demote or disable
    the last enabled administrator.

    The guard reads the post-change viability of the target and excludes the
    target from the count of the others, in the same transaction as the
    mutation, so the decision and the write see one consistent state. Two
    concurrent demotions of the last two admins can still both pass the count
    check (SQLite serialises commits, not these reads); that is accepted for a
    self-hosted deployment and documented in docs/PERMISSIONS.md.
    """
    user = get_user(session, user_id)
    if user is None:
        raise UnknownAccount("no such user")
    new_role = _clean_role(role) if role is not None else user.role
    new_disabled = user.disabled if disabled is None else (1 if disabled else 0)
    stays_viable = new_role == ADMIN_ROLE and not new_disabled
    loses_last_admin = (
        is_viable_admin(user)
        and not stays_viable
        and count_enabled_admins(session, exclude_user_id=user.id) == 0
    )
    if loses_last_admin:
        raise LastAdmin("at least one enabled administrator is required")
    user.role = new_role
    user.disabled = new_disabled
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
