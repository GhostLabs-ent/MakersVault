from typing import Optional

from sqlmodel import Session

from db import engine
from models import AppConfig

MOUNT_IMPORT_ENABLED_KEY = "mount_import_enabled"
MOUNT_IMPORT_COPY_KEY = "mount_import_copy"
STORAGE_TEMPLATE_KEY = "storage_path_template"
TRASH_RETENTION_KEY = "trash_retention"
DEFAULT_STORAGE_TEMPLATE = "{folder}/{model}/{filename}"
DEFAULT_TRASH_RETENTION = "until_needed"
TRASH_RETENTION_CHOICES = {"until_needed", "day", "week", "month", "never"}


def get_setting(key: str) -> Optional[str]:
    with Session(engine) as s:
        row = s.get(AppConfig, key)
        return row.value if row else None


def set_setting(key: str, value: str) -> None:
    with Session(engine) as s:
        row = s.get(AppConfig, key)
        if row:
            row.value = value
        else:
            row = AppConfig(key=key, value=value)
            s.add(row)
        s.commit()


def get_bool_setting(key: str, default: bool) -> bool:
    raw = get_setting(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def set_bool_setting(key: str, value: bool) -> None:
    set_setting(key, "1" if value else "0")


def get_mount_import_enabled(default: bool) -> bool:
    return get_bool_setting(MOUNT_IMPORT_ENABLED_KEY, default)


def set_mount_import_enabled(value: bool) -> None:
    set_bool_setting(MOUNT_IMPORT_ENABLED_KEY, value)


def get_mount_import_copy(default: bool) -> bool:
    return get_bool_setting(MOUNT_IMPORT_COPY_KEY, default)


def set_mount_import_copy(value: bool) -> None:
    set_bool_setting(MOUNT_IMPORT_COPY_KEY, value)


def get_storage_template() -> str:
    return get_setting(STORAGE_TEMPLATE_KEY) or DEFAULT_STORAGE_TEMPLATE


def set_storage_template(value: str) -> None:
    set_setting(STORAGE_TEMPLATE_KEY, value)


def get_trash_retention() -> str:
    value = get_setting(TRASH_RETENTION_KEY) or DEFAULT_TRASH_RETENTION
    return value if value in TRASH_RETENTION_CHOICES else DEFAULT_TRASH_RETENTION


def set_trash_retention(value: str) -> None:
    if value not in TRASH_RETENTION_CHOICES:
        raise ValueError("Invalid Trash retention policy")
    set_setting(TRASH_RETENTION_KEY, value)
