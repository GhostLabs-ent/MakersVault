import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, select

import offline_recovery
from migrations import run_migrations
from models import AuditEvent, RecoveryMarker, UserAccount
from recovery_marker_service import process_recovery_markers
from recovery_mutation import RecoveryMutationError


def test_startup_converts_pending_recovery_marker_to_secret_free_audit(
    tmp_path: Path,
) -> None:
    database_engine = create_engine(
        f"sqlite:///{tmp_path / 'app.db'}",
        connect_args={"check_same_thread": False},
    )
    run_migrations(database_engine)
    user_id = "11111111-1111-4111-8111-111111111111"
    marker_id = "22222222-2222-4222-8222-222222222222"
    with Session(database_engine) as session:
        session.add(
            UserAccount(
                id=user_id,
                username="recovered",
                username_normalized="recovered",
                display_name="Recovered",
                password_hash="$argon2id$v=19$fixture",
                enabled=True,
                password_policy_version=1,
                password_change_required=True,
                role="administrator",
                created_at="2026-09-03T00:00:00Z",
                updated_at="2026-09-03T00:00:00Z",
            )
        )
        session.add(
            RecoveryMarker(
                id=marker_id,
                kind="administrator_recovery",
                created_at="2026-09-03T00:00:01Z",
                details_json=json.dumps(
                    {"user_id": user_id, "revoked_sessions": 3}
                ),
            )
        )
        session.commit()

    assert process_recovery_markers(database_engine) == 1
    assert process_recovery_markers(database_engine) == 0

    with Session(database_engine) as session:
        marker = session.get(RecoveryMarker, marker_id)
        event = session.exec(
            select(AuditEvent).where(AuditEvent.action == "recovery.administrator")
        ).one()
        assert marker is not None and marker.processed_at is not None
        assert event.actor_user_id is None
        assert event.object_type == "user"
        assert event.object_id == user_id
        assert json.loads(event.details_json) == {"revoked_sessions": 3}
        serialized = json.dumps(event.model_dump())
        assert "password" not in serialized
        assert "backup" not in serialized


def test_startup_preserves_only_bounded_schema17_recovery_counts(
    tmp_path: Path,
) -> None:
    database_engine = create_engine(
        f"sqlite:///{tmp_path / 'app.db'}",
        connect_args={"check_same_thread": False},
    )
    run_migrations(database_engine)
    marker_id = "33333333-3333-4333-8333-333333333333"
    with Session(database_engine) as session:
        session.add(
            RecoveryMarker(
                id=marker_id,
                kind="raw_restore",
                created_at="2026-09-04T00:00:00Z",
                details_json=json.dumps(
                    {"revoked_sessions": 2, "revoked_challenges": 4}
                ),
            )
        )
        session.commit()

    assert process_recovery_markers(database_engine) == 1

    with Session(database_engine) as session:
        event = session.exec(
            select(AuditEvent).where(AuditEvent.action == "recovery.raw_restore")
        ).one()
        assert json.loads(event.details_json) == {
            "revoked_challenges": 4,
            "revoked_sessions": 2,
        }


def test_offline_recovery_reads_matching_passwords_only_from_protected_prompt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    prompts: list[str] = []
    values = iter(["correct temporary phrase", "correct temporary phrase"])

    def prompted(label: str) -> str:
        prompts.append(label)
        return next(values)

    captured: dict[str, object] = {}

    def recovered(database, backup, username, password_hash, policy_version):
        captured.update(
            database=database,
            backup=backup,
            username=username,
            password_hash=password_hash,
            policy_version=policy_version,
        )
        return {"user_id": "fixture"}

    monkeypatch.setattr(offline_recovery.getpass, "getpass", prompted)
    monkeypatch.setattr(offline_recovery, "hash_new_password", lambda value: "hashed")
    monkeypatch.setattr(offline_recovery, "recover_existing_administrator", recovered)

    result = offline_recovery.recover_interactively(
        tmp_path / "app.db", tmp_path / "backup.tar.gz", "Admin"
    )

    assert result == {"user_id": "fixture"}
    assert prompts == ["New temporary password: ", "Confirm temporary password: "]
    assert captured["password_hash"] == "hashed"
    assert "correct temporary phrase" not in repr(captured)


def test_offline_recovery_rejects_prompt_mismatch_before_mutation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    values = iter(["first temporary phrase", "different temporary phrase"])
    monkeypatch.setattr(offline_recovery.getpass, "getpass", lambda _label: next(values))
    monkeypatch.setattr(
        offline_recovery,
        "recover_existing_administrator",
        lambda *_args: pytest.fail("mutation must not run"),
    )

    with pytest.raises(RecoveryMutationError, match="does not match"):
        offline_recovery.recover_interactively(
            tmp_path / "app.db", tmp_path / "backup.tar.gz", "Admin"
        )
