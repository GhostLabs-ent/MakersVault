"""Bulk asset operations: one request, one result per id.

Every item runs in its own transaction and its own failure is caught, so one bad
id cannot roll back its neighbours: a request that changes nothing is the only
one that fails whole, and partial success is the contract, not an error. The
service returns plain models and dicts; ``main`` owns the HTTP shapes.
"""

import json
import logging
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session

import asset_service
import audit
from db import engine
from models import Asset

log = logging.getLogger(__name__)

# The equivalent single-item route's status decides the stable slug the client
# switches on; anything else is an unexpected failure.
FAILURE_CODE_BY_STATUS = {400: "invalid", 404: "not_found", 409: "conflict"}


def unique_asset_ids(raw: List[str]) -> List[str]:
    """Strip, drop empties and dedupe first-seen: one confirmation per asset."""
    seen: set[str] = set()
    result: List[str] = []
    for value in raw or []:
        cleaned = (value or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _clean_tags(values: List[str]) -> List[str]:
    return [value.strip() for value in values or [] if value and value.strip()]


def merge_tags(current: List[str], add: List[str], remove: List[str]) -> List[str]:
    """Apply add/remove to a tag list, matching strings exactly.

    The server's tag index is case-sensitive, so "PLA" and "pla" are different
    tags and must not be folded together here; whitespace is trimmed because a
    padded tag could never match anything else.
    """
    removed = set(_clean_tags(remove))
    merged = [tag for tag in current if tag not in removed]
    for tag in _clean_tags(add):
        if tag not in merged:
            merged.append(tag)
    return merged


def _failure(asset_id: str, error: BaseException) -> dict:
    """Describe one failed item without leaking internals."""
    if isinstance(error, HTTPException):
        status = int(error.status_code)
        detail = error.detail if isinstance(error.detail, str) else str(error.detail)
        return {"id": asset_id, "code": FAILURE_CODE_BY_STATUS.get(status, "error"), "status": status, "error": detail}
    log.exception("Bulk operation failed for asset %s", asset_id, exc_info=error)
    return {"id": asset_id, "code": "error", "status": 500, "error": "Unexpected error"}


def update_tags(
    asset_ids: List[str],
    add_tags: List[str],
    remove_tags: List[str],
    *,
    audit_ctx: Optional[audit.AuditContext],
) -> Tuple[List[Asset], List[dict]]:
    """Add and remove tags on each asset, one session per item.

    Tag edits are an exempt metadata class, so this accepts the uniform caller
    contract but stages nothing: rename and move are the audited asset edits.
    """
    updated: List[Asset] = []
    failed: List[dict] = []
    for asset_id in asset_ids:
        try:
            with Session(engine) as s:
                asset = s.get(Asset, asset_id)
                if not asset:
                    raise HTTPException(status_code=404, detail="Asset not found")
                current = json.loads(asset.tags_json or "[]")
                asset.tags_json = json.dumps(merge_tags(current, add_tags, remove_tags))
                s.add(asset)
                s.commit()
                # Refresh before the session closes: to_out must never see
                # expired detached attributes.
                s.refresh(asset)
                updated.append(asset)
        except Exception as error:
            failed.append(_failure(asset_id, error))
    return updated, failed


def move_to_folder(
    asset_ids: List[str],
    folder_id: Optional[str],
    *,
    audit_ctx: Optional[audit.AuditContext],
) -> Tuple[List[Asset], List[dict]]:
    """Move each asset into one folder, one transaction per item."""
    updated: List[Asset] = []
    failed: List[dict] = []
    for asset_id in asset_ids:
        try:
            updated.append(asset_service.move_asset_to_folder_by_id(asset_id, folder_id, audit_ctx=audit_ctx))
        except Exception as error:
            failed.append(_failure(asset_id, error))
    return updated, failed


def delete_assets(
    asset_ids: List[str],
    *,
    audit_ctx: Optional[audit.AuditContext],
) -> Tuple[List[str], List[dict]]:
    """Delete each asset, one transaction per item."""
    deleted: List[str] = []
    failed: List[dict] = []
    for asset_id in asset_ids:
        try:
            asset_service.delete_asset_permanently(asset_id, audit_ctx=audit_ctx)
            deleted.append(asset_id)
        except Exception as error:
            failed.append(_failure(asset_id, error))
    return deleted, failed
