"""Guard the ZFS snapshot documentation against drifting from the code.

The operator-facing contract for ``snapshot_zfs`` lives in CONFIGURATION.md: the
delegation command, the mountpoint command, the probe's state vocabulary and the
"copy back, never roll back" rule. Each of those is asserted here against the
module's own constants where one exists, so a rename or a typo in the code makes
this test fail instead of silently leaving the docs wrong.

Host-only, like ``test_auth_docs.py``: the guarded docs live above the API
directory, so this module skips itself in the container, where
``curiarium/api`` is the whole build context.
"""

from pathlib import Path

import pytest

import snapshot_zfs

CONFIGURATION_PATH = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "CONFIGURATION.md"

if not CONFIGURATION_PATH.exists():
    pytest.skip(
        "the zfs snapshot docs guard is host-only (the API image builds from curiarium/api, so "
        "curiarium/docs/ is absent)",
        allow_module_level=True,
    )

STATE_VOCABULARY = ("delegated", "available_but_not_delegated", "unavailable", "library_not_mountpoint")


def configuration_text() -> str:
    return CONFIGURATION_PATH.read_text(encoding="utf-8")


def test_the_docs_have_a_zfs_snapshot_section() -> None:
    assert "## Snapshots (ZFS)" in configuration_text()


def test_the_docs_quote_the_remedies_verbatim() -> None:
    text = configuration_text()

    assert snapshot_zfs.ALLOW_REMEDY in text
    assert snapshot_zfs.MOUNTPOINT_REMEDY in text


def test_the_docs_name_every_probe_state() -> None:
    text = configuration_text()

    for state in STATE_VOCABULARY:
        assert state in text, f"CONFIGURATION.md does not name the probe state {state!r}"
    assert {state.value for state in snapshot_zfs.ZfsState} == set(STATE_VOCABULARY)


def test_the_docs_state_the_container_and_visibility_caveats() -> None:
    text = configuration_text()

    assert "snapdir" in text
    assert "/dev/zfs" in text


def test_the_docs_say_restores_copy_out_and_never_roll_back() -> None:
    text = configuration_text()

    assert "never runs `zfs rollback`" in text
    assert "copies out" in text


def test_the_docs_mark_real_pool_verification_as_manual() -> None:
    text = configuration_text()

    assert "MANUAL" in text
    assert "manual" in text


def test_the_docs_state_the_mountpoint_precondition() -> None:
    text = configuration_text()

    assert "must be the dataset mountpoint" in text
