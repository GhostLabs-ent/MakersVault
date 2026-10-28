"""Reusable normalisers for editable asset metadata (Mf-pnc2).

The request schemas call these from pydantic ``field_validator``s, so bad input
is a 422 at the edge - before a route handler, and therefore before any
``sanitize_path_segment``/``unique_model_name`` call could silently change it
into something else. Every rule lives here once so the single-item edit and the
batch edit cannot drift apart.

The functions return the value to store (or ``None`` for "clear"), and raise
``ValueError`` for input the API should refuse; pydantic turns that into a 422.
``collection`` is deliberately absent: ADR 0003 retires it, so it keeps the
legacy ``strip() or None`` behaviour and is not validated.
"""

import unicodedata
from typing import Optional

CREATOR_MAX_LENGTH = 120
NAME_MAX_LENGTH = 120
NOTES_MAX_LENGTH = 4000
# A model name becomes a path component, so a separator is a validation error
# here rather than something sanitising can quietly rewrite into an underscore.
NAME_SEPARATORS = ("/", "\\")
# Notes are prose: line breaks and tabs are meaningful, every other control
# character is still refused.
NOTES_ALLOWED_CONTROLS = "\n\t"


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _reject_controls(value: str, field: str, allowed: str = "") -> None:
    for char in value:
        if char in allowed:
            continue
        if unicodedata.category(char) == "Cc":
            raise ValueError(f"{field} must not contain control characters")


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def normalise_creator(value: object) -> Optional[str]:
    """Trim, collapse whitespace and cap a creator; blank clears the field."""
    if value is None:
        return None
    text = _require_string(value, "creator")
    _reject_controls(text, "creator")
    text = _collapse_whitespace(text)
    if not text:
        return None
    if len(text) > CREATOR_MAX_LENGTH:
        raise ValueError(f"creator must be at most {CREATOR_MAX_LENGTH} characters")
    return text


def normalise_name(value: object, field: str = "name") -> Optional[str]:
    """Trim, collapse, reject separators and cap a model name or title.

    ``None`` means "not provided" and stays ``None``; a provided value must be
    non-empty, because an empty name would only be replaced by a fallback later.
    Title uses exactly these rules - there is no separate title cap.
    """
    if value is None:
        return None
    text = _require_string(value, field)
    _reject_controls(text, field)
    if any(separator in text for separator in NAME_SEPARATORS):
        raise ValueError(f"{field} must not contain path separators")
    text = _collapse_whitespace(text)
    if not text:
        raise ValueError(f"{field} must not be empty")
    if len(text) > NAME_MAX_LENGTH:
        raise ValueError(f"{field} must be at most {NAME_MAX_LENGTH} characters")
    return text


def normalise_notes(value: object) -> Optional[str]:
    """Trim outer whitespace and cap notes; internal line breaks are preserved."""
    if value is None:
        return None
    text = _require_string(value, "notes")
    _reject_controls(text, "notes", NOTES_ALLOWED_CONTROLS)
    text = text.strip()
    if not text:
        return None
    if len(text) > NOTES_MAX_LENGTH:
        raise ValueError(f"notes must be at most {NOTES_MAX_LENGTH} characters")
    return text
