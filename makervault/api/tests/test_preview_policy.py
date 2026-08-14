import pytest

from preview_policy import (
    automatic_preview_disposition,
    preview_policy_payload,
    validate_preview_state,
)


def test_automatic_policy_is_separate_from_upload_limit() -> None:
    policy = preview_policy_payload()
    assert automatic_preview_disposition("small.stl", policy["automatic_max_bytes"])[0] == "pending"
    assert automatic_preview_disposition("large.stl", policy["automatic_max_bytes"] + 1) == (
        "skipped_policy",
        "file_too_large",
    )
    assert automatic_preview_disposition("assembly.step", 1024) == (
        "skipped_policy",
        "step_manual_only",
    )
    assert automatic_preview_disposition("laser-project.lbrn2", 1024) == ("pending", None)
    assert automatic_preview_disposition("large.stl", policy["automatic_max_bytes"] + 1, True) == (
        "ready",
        None,
    )


def test_preview_state_validation_requires_safe_reason_codes() -> None:
    assert validate_preview_state("failed", "malformed_stl") == ("failed", "malformed_stl")
    assert validate_preview_state("pending", "timeout") == ("pending", None)
    with pytest.raises(ValueError, match="requires a reason"):
        validate_preview_state("failed", None)
    with pytest.raises(ValueError, match="Unknown preview reason"):
        validate_preview_state("failed", "raw parser stack")
