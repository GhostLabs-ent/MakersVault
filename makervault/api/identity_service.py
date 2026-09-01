"""Gate 11A persistent first-administrator identity and password policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import unicodedata
import uuid

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from models import UserAccount


PASSWORD_POLICY_VERSION = 1
PASSWORD_MIN_CHARACTERS = 15
PASSWORD_MAX_CHARACTERS = 4096
ARGON2_MEMORY_KIB = 64 * 1024
ARGON2_TIME_COST = 3
ARGON2_PARALLELISM = 1
ARGON2_HASH_PREFIX = "$argon2id$v=19$"
PASSWORD_HASH_CONCURRENCY = 2

_COMMON_PASSWORDS = frozenset(
    {
        "123456789012345",
        "adminadminadmin",
        "changemechangeme",
        "correcthorsebatterystaple",
        "letmeinletmeinletmein",
        "makersvaultmakersvault",
        "passwordpassword",
        "qwertyqwertyqwerty",
        "welcomecomewelcome",
    }
)

PASSWORD_HASHER = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_KIB,
    parallelism=ARGON2_PARALLELISM,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
_HASH_SLOTS = threading.BoundedSemaphore(PASSWORD_HASH_CONCURRENCY)
_DUMMY_HASH = PASSWORD_HASHER.hash("MakersVault timing-only credential")


class PasswordPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class BootstrapResult:
    created: bool
    user_id: str
    password_change_required: bool


@dataclass(frozen=True)
class AuthenticatedAdministrator:
    id: str
    username: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_username(username: str) -> str:
    normalized = unicodedata.normalize("NFKC", username).strip().casefold()
    if not normalized or len(normalized) > 256:
        raise ValueError("username must contain between 1 and 256 characters")
    return normalized


def validate_new_password(password: str) -> str:
    if len(password) < PASSWORD_MIN_CHARACTERS:
        raise PasswordPolicyError(
            f"password must contain at least {PASSWORD_MIN_CHARACTERS} characters"
        )
    if len(password) > PASSWORD_MAX_CHARACTERS:
        raise PasswordPolicyError(
            f"password must contain at most {PASSWORD_MAX_CHARACTERS} characters"
        )
    blocklist_value = unicodedata.normalize("NFKC", password).strip().casefold()
    if blocklist_value in _COMMON_PASSWORDS:
        raise PasswordPolicyError("password is too common or compromised")
    return password


def _password_requires_change(password: str) -> bool:
    try:
        validate_new_password(password)
    except PasswordPolicyError:
        return True
    return False


def _hash_password(password: str) -> str:
    with _HASH_SLOTS:
        return PASSWORD_HASHER.hash(password)


def _verify_password(password_hash: str, password: str) -> bool:
    try:
        with _HASH_SLOTS:
            return bool(PASSWORD_HASHER.verify(password_hash, password))
    except (InvalidHashError, VerificationError):
        return False


def _first_user(database_engine: Engine) -> UserAccount | None:
    with Session(database_engine) as session:
        return session.exec(
            select(UserAccount).order_by(UserAccount.created_at, UserAccount.id)
        ).first()


def bootstrap_initial_administrator(
    database_engine: Engine,
    *,
    username: str,
    password: str,
) -> BootstrapResult:
    """Create exactly the first persistent identity; never update an existing one."""
    existing = _first_user(database_engine)
    if existing is not None:
        return BootstrapResult(
            created=False,
            user_id=existing.id,
            password_change_required=existing.password_change_required,
        )

    normalized = normalize_username(username)
    timestamp = _now()
    candidate = UserAccount(
        id=str(uuid.uuid4()),
        username=username,
        username_normalized=normalized,
        display_name=username,
        password_hash=_hash_password(password),
        enabled=True,
        password_policy_version=PASSWORD_POLICY_VERSION,
        password_change_required=_password_requires_change(password),
        created_at=timestamp,
        updated_at=timestamp,
    )
    try:
        with Session(database_engine) as session:
            if session.exec(select(UserAccount.id).limit(1)).first() is None:
                session.add(candidate)
                session.commit()
                return BootstrapResult(
                    created=True,
                    user_id=candidate.id,
                    password_change_required=candidate.password_change_required,
                )
    except IntegrityError:
        pass

    existing = _first_user(database_engine)
    if existing is None:
        raise RuntimeError("persistent administrator bootstrap did not publish an identity")
    return BootstrapResult(
        created=False,
        user_id=existing.id,
        password_change_required=existing.password_change_required,
    )


def authenticate_initial_administrator(
    database_engine: Engine,
    *,
    username: str,
    password: str,
) -> AuthenticatedAdministrator | None:
    """Authenticate persistently; environment credentials are never a login bypass."""
    try:
        normalized = normalize_username(username)
    except ValueError:
        normalized = ""

    with Session(database_engine) as session:
        user = session.exec(
            select(UserAccount).where(UserAccount.username_normalized == normalized)
        ).first()
        candidate_hash = user.password_hash if user is not None and user.enabled else _DUMMY_HASH
        valid = _verify_password(candidate_hash, password)
        if user is None or not user.enabled or not valid:
            return None

        timestamp = _now()
        try:
            needs_rehash = PASSWORD_HASHER.check_needs_rehash(user.password_hash)
        except InvalidHashError:
            return None
        if needs_rehash:
            user.password_hash = _hash_password(password)
            user.password_policy_version = PASSWORD_POLICY_VERSION
        user.last_login_at = timestamp
        user.updated_at = timestamp
        identity = AuthenticatedAdministrator(id=user.id, username=user.username)
        session.add(user)
        session.commit()
        return identity
