from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import (
    PREVIEW_AUTO_3MF_ENTRIES,
    PREVIEW_AUTO_3MF_EXPANDED_BYTES,
    PREVIEW_AUTO_MAX_BYTES,
    PREVIEW_AUTO_MAX_TRIANGLES,
    PREVIEW_AUTO_MEMORY_BYTES,
    PREVIEW_AUTO_QUEUE,
    PREVIEW_AUTO_TIMEOUT_SECONDS,
    PREVIEW_DETAIL_3MF_ENTRIES,
    PREVIEW_DETAIL_3MF_EXPANDED_BYTES,
    PREVIEW_DETAIL_MAX_BYTES,
    PREVIEW_DETAIL_MAX_TRIANGLES,
    PREVIEW_DETAIL_MEMORY_BYTES,
    PREVIEW_DETAIL_TIMEOUT_SECONDS,
    PREVIEW_POLICY_VERSION,
)
from models import Asset


PREVIEW_MODEL_EXTENSIONS = {".stl", ".obj", ".3mf", ".step", ".stp"}
PREVIEW_AUTOMATIC_EXTENSIONS = {".stl", ".obj", ".3mf", ".lbrn", ".lbrn2"}
PREVIEW_STATES = {"pending", "ready", "failed", "skipped_policy", "retry_requested"}
PREVIEW_REASON_CODES = {
    "archive_entries",
    "archive_expanded",
    "browser_unsupported",
    "cancelled",
    "file_too_large",
    "invalid_geometry",
    "malformed_3mf",
    "malformed_lightburn",
    "malformed_obj",
    "malformed_step",
    "malformed_stl",
    "memory_budget",
    "step_manual_only",
    "timeout",
    "too_many_triangles",
    "unsupported_type",
}


def preview_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def automatic_preview_disposition(filename: str, size: int, has_thumbnail: bool = False) -> tuple[str, Optional[str]]:
    if has_thumbnail:
        return "ready", None
    extension = Path(filename or "").suffix.lower()
    if extension in {".step", ".stp"}:
        return "skipped_policy", "step_manual_only"
    if extension not in PREVIEW_AUTOMATIC_EXTENSIONS:
        return "skipped_policy", "unsupported_type"
    if max(0, size) > PREVIEW_AUTO_MAX_BYTES:
        return "skipped_policy", "file_too_large"
    return "pending", None


def apply_automatic_preview_disposition(asset: Asset, has_thumbnail: bool = False) -> None:
    state, reason = automatic_preview_disposition(asset.filename, asset.size, has_thumbnail)
    asset.preview_status = state
    asset.preview_reason = reason
    asset.preview_policy_version = PREVIEW_POLICY_VERSION
    asset.preview_updated_at = preview_timestamp()
    if state == "ready" and not asset.preview_source:
        asset.preview_source = "embedded"


def validate_preview_state(status: str, reason: Optional[str]) -> tuple[str, Optional[str]]:
    normalized_status = (status or "").strip().lower()
    normalized_reason = (reason or "").strip().lower() or None
    if normalized_status not in PREVIEW_STATES:
        raise ValueError("Unknown preview status")
    if normalized_reason and normalized_reason not in PREVIEW_REASON_CODES:
        raise ValueError("Unknown preview reason")
    if normalized_status in {"failed", "skipped_policy"} and not normalized_reason:
        raise ValueError("A terminal preview status requires a reason")
    if normalized_status in {"pending", "ready", "retry_requested"}:
        normalized_reason = None
    return normalized_status, normalized_reason


def preview_policy_payload() -> dict[str, int | bool]:
    return {
        "version": PREVIEW_POLICY_VERSION,
        "active_jobs": 1,
        "queue_limit": PREVIEW_AUTO_QUEUE,
        "automatic_max_bytes": PREVIEW_AUTO_MAX_BYTES,
        "automatic_max_triangles": PREVIEW_AUTO_MAX_TRIANGLES,
        "automatic_3mf_expanded_bytes": PREVIEW_AUTO_3MF_EXPANDED_BYTES,
        "automatic_3mf_entries": PREVIEW_AUTO_3MF_ENTRIES,
        "automatic_memory_bytes": PREVIEW_AUTO_MEMORY_BYTES,
        "automatic_timeout_seconds": PREVIEW_AUTO_TIMEOUT_SECONDS,
        "detail_max_bytes": PREVIEW_DETAIL_MAX_BYTES,
        "detail_max_triangles": PREVIEW_DETAIL_MAX_TRIANGLES,
        "detail_3mf_expanded_bytes": PREVIEW_DETAIL_3MF_EXPANDED_BYTES,
        "detail_3mf_entries": PREVIEW_DETAIL_3MF_ENTRIES,
        "detail_memory_bytes": PREVIEW_DETAIL_MEMORY_BYTES,
        "detail_timeout_seconds": PREVIEW_DETAIL_TIMEOUT_SECONDS,
        "automatic_step_enabled": False,
    }
