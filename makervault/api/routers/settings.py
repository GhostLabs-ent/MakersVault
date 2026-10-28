"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

import audit
from asset_service import STORAGE_TEMPLATE_TOKENS, sample_storage_path, validate_storage_template
from auth import AuthContext
from config import MOUNT_IMPORT_COPY, MOUNT_IMPORT_ENABLED, MOUNT_IMPORT_PATH
from db import engine
from permissions import require_admin
from schemas import MountImportSettings, MountImportSettingsOut, StorageSettings, StorageSettingsOut
from settings_service import (
    DEFAULT_STORAGE_TEMPLATE,
    STORAGE_TEMPLATE_KEY,
    get_mount_import_copy,
    get_mount_import_enabled,
    get_storage_template,
    set_mount_import_copy,
    set_mount_import_enabled,
    set_storage_template,
)

router = APIRouter()


@router.get("/settings/mount-import", response_model=MountImportSettingsOut)
def get_mount_import_settings(_: Optional[AuthContext] = Depends(require_admin)):
    return MountImportSettingsOut(
        enabled=get_mount_import_enabled(MOUNT_IMPORT_ENABLED),
        copy_files=get_mount_import_copy(MOUNT_IMPORT_COPY),
        path=MOUNT_IMPORT_PATH or None,
    )


@router.post("/settings/mount-import", response_model=MountImportSettingsOut)
def update_mount_import_settings(
    body: MountImportSettings,
    request: Request,
    context: Optional[AuthContext] = Depends(require_admin),
):
    # One session, one transaction: the two settings and the audit row commit or
    # roll back together.
    with Session(engine) as s:
        set_mount_import_enabled(body.enabled, session=s)
        set_mount_import_copy(body.copy_files, session=s)
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(
                audit.SETTINGS_MOUNT_IMPORT_UPDATE,
                "mount_import",
                {"enabled": body.enabled, "copy_files": body.copy_files},
            ),
        )
        s.commit()
    return MountImportSettingsOut(
        enabled=get_mount_import_enabled(MOUNT_IMPORT_ENABLED),
        copy_files=get_mount_import_copy(MOUNT_IMPORT_COPY),
        path=MOUNT_IMPORT_PATH or None,
    )


def storage_settings_out(template: str, moved: int = 0, skipped: int = 0) -> StorageSettingsOut:
    return StorageSettingsOut(
        template=template,
        default_template=DEFAULT_STORAGE_TEMPLATE,
        allowed_tokens=list(STORAGE_TEMPLATE_TOKENS),
        sample_path=sample_storage_path(template),
        moved=moved,
        skipped=skipped,
    )


@router.get("/settings/storage", response_model=StorageSettingsOut)
def get_storage_settings(_: Optional[AuthContext] = Depends(require_admin)):
    template = validate_storage_template(get_storage_template())
    return storage_settings_out(template)


@router.post("/settings/storage", response_model=StorageSettingsOut)
def update_storage_settings(
    body: StorageSettings,
    request: Request,
    context: Optional[AuthContext] = Depends(require_admin),
):
    template = validate_storage_template(body.template)
    previous = validate_storage_template(get_storage_template())
    # The template governs new uploads and imports only; existing files never move.
    with Session(engine) as s:
        set_storage_template(template, session=s)
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.SETTINGS_STORAGE_UPDATE, STORAGE_TEMPLATE_KEY, {"from": previous, "to": template}),
        )
        s.commit()
    return storage_settings_out(template)
