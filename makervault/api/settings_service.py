from typing import Optional

from sqlmodel import Session

from db import engine
from models import AppConfig

MOUNT_IMPORT_ENABLED_KEY = "mount_import_enabled"
MOUNT_IMPORT_COPY_KEY = "mount_import_copy"
STORAGE_TEMPLATE_KEY = "storage_path_template"
DEFAULT_STORAGE_TEMPLATE = "{folder}/{model}/{filename}"


def get_setting(key: str) -> Optional[str]:
    with Session(engine) as s:
        row = s.get(AppConfig, key)
        return row.value if row else None


def _apply_setting(session: Session, key: str, value: str) -> None:
    """Upsert one setting on the caller's session; the caller commits."""
    row = session.get(AppConfig, key)
    if row:
        row.value = value
    else:
        row = AppConfig(key=key, value=value)
        session.add(row)


def set_setting(key: str, value: str, *, session: Optional[Session] = None) -> None:
    """Store one setting.

    With `session` given, the write joins the caller's transaction so a settings
    change and its audit row commit together; without it, a session is opened
    and committed here, which is the behaviour every non-request caller uses.
    """
    if session is not None:
        _apply_setting(session, key, value)
        return
    with Session(engine) as own:
        _apply_setting(own, key, value)
        own.commit()


def get_bool_setting(key: str, default: bool) -> bool:
    raw = get_setting(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def set_bool_setting(key: str, value: bool, *, session: Optional[Session] = None) -> None:
    set_setting(key, "1" if value else "0", session=session)


def get_mount_import_enabled(default: bool) -> bool:
    return get_bool_setting(MOUNT_IMPORT_ENABLED_KEY, default)


def set_mount_import_enabled(value: bool, *, session: Optional[Session] = None) -> None:
    set_bool_setting(MOUNT_IMPORT_ENABLED_KEY, value, session=session)


def get_mount_import_copy(default: bool) -> bool:
    return get_bool_setting(MOUNT_IMPORT_COPY_KEY, default)


def set_mount_import_copy(value: bool, *, session: Optional[Session] = None) -> None:
    set_bool_setting(MOUNT_IMPORT_COPY_KEY, value, session=session)


def get_storage_template() -> str:
    return get_setting(STORAGE_TEMPLATE_KEY) or DEFAULT_STORAGE_TEMPLATE


def set_storage_template(value: str, *, session: Optional[Session] = None) -> None:
    set_setting(STORAGE_TEMPLATE_KEY, value, session=session)
