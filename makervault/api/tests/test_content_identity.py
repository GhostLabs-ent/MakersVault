import hashlib
import time

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from db import engine
from main import app
from models import ArtifactRevision, Asset, ContentHashJob, ContentHashJobItem
from content_identity import recover_interrupted_content_hash_jobs
from asset_service import managed_asset_path


def _headers(client: TestClient) -> dict[str, str]:
    login = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _upload(client: TestClient, headers: dict[str, str], filename: str, data: bytes) -> dict:
    response = client.post(
        "/upload",
        headers=headers,
        files={"file": (filename, data, "application/octet-stream")},
    )
    assert response.status_code == 200
    return response.json()


def test_new_ingestion_creates_ready_revision_and_duplicate_suggestion() -> None:
    content = b"exact revision bytes\n"
    with TestClient(app) as client:
        headers = _headers(client)
        first = _upload(client, headers, "identity-a.stl", content)
        second = _upload(client, headers, "identity-b.stl", content)
        try:
            revisions = client.get(
                f"/asset/{first['id']}/revisions", headers=headers
            )
            assert revisions.status_code == 200
            revision = revisions.json()[0]
            assert revision["revision_number"] == 1
            assert revision["origin_revision_id"] is None
            assert revision["filename"] == "identity-a.stl"
            assert revision["mime"] == "application/octet-stream"
            assert revision["size"] == len(content)
            assert revision["sha256"] == hashlib.sha256(content).hexdigest()
            assert revision["content_state"] == "ready"
            assert revision["content_reason"] is None
            assert revision["is_current"] is True

            duplicates = client.get(
                f"/asset/{first['id']}/duplicates", headers=headers
            )
            assert duplicates.status_code == 200
            assert [row["id"] for row in duplicates.json()] == [second["id"]]
        finally:
            client.delete(f"/asset/{first['id']}", headers=headers)
            client.delete(f"/asset/{second['id']}", headers=headers)

    with Session(engine) as session:
        remaining = list(
            session.exec(
                select(ArtifactRevision).where(
                    ArtifactRevision.asset_id.in_([first["id"], second["id"]])
                )
            )
        )
    assert remaining == []


def test_pending_revision_backfill_is_durable_and_bounded_per_item() -> None:
    content = b"backfill these bytes\n"
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "backfill.stl", content)
        try:
            with Session(engine) as session:
                row = session.get(Asset, asset["id"])
                revision = session.get(ArtifactRevision, row.current_revision_id)
                revision.sha256 = None
                revision.observed_sha256 = None
                revision.content_state = "pending"
                revision.content_reason = None
                revision.content_checked_at = None
                session.add(revision)
                session.commit()

            started = client.post(
                "/settings/content-identity/backfill",
                headers=headers,
                json={"verify_all": False},
            )
            assert started.status_code == 200
            assert started.json()["started"] is True

            terminal = None
            for _ in range(100):
                response = client.get("/settings/content-identity", headers=headers)
                assert response.status_code == 200
                terminal = response.json()
                if terminal and terminal["status"] != "running":
                    break
                time.sleep(0.01)

            assert terminal is not None
            assert terminal["status"] == "completed"
            assert terminal["total"] == 1
            assert terminal["processed"] == 1
            assert terminal["ready"] == 1
            revision = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()[0]
            assert revision["sha256"] == hashlib.sha256(content).hexdigest()
            assert revision["content_state"] == "ready"
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_interrupted_hash_job_resets_only_running_items() -> None:
    with Session(engine) as session:
        asset = Asset(
            name="Interrupted hash",
            filename="interrupted-hash.stl",
            mime="model/stl",
            size=1,
            storage_path="missing/interrupted-hash.stl",
        )
        session.add(asset)
        session.flush()
        revision = ArtifactRevision(
            asset_id=asset.id,
            revision_number=1,
            created_at="2026-08-22T00:00:00Z",
            filename=asset.filename,
            mime=asset.mime,
            size=asset.size,
            storage_path=asset.storage_path,
        )
        asset.current_revision_id = revision.id
        job = ContentHashJob(
            trigger="manual",
            status="running",
            started_at="2026-08-22T00:00:00Z",
            total=1,
        )
        session.add(revision)
        session.add(job)
        session.flush()
        item = ContentHashJobItem(
            job_id=job.id,
            revision_id=revision.id,
            status="running",
        )
        session.add(item)
        session.add(asset)
        session.commit()
        asset_id = asset.id
        revision_id = revision.id
        job_id = job.id

    assert recover_interrupted_content_hash_jobs() >= 1

    with Session(engine) as session:
        job = session.get(ContentHashJob, job_id)
        item = session.get(ContentHashJobItem, (job_id, revision_id))
        assert job.status == "interrupted"
        assert item.status == "pending"
        session.delete(item)
        session.delete(job)
        session.delete(session.get(ArtifactRevision, revision_id))
        session.delete(session.get(Asset, asset_id))
        session.commit()


def test_verify_all_marks_changed_bytes_without_replacing_recorded_digest() -> None:
    original = b"original immutable bytes\n"
    changed = b"changed immutable bytes!\n"
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, "changed-content.stl", original)
        original_digest = hashlib.sha256(original).hexdigest()
        try:
            with Session(engine) as session:
                row = session.get(Asset, asset["id"])
                path = managed_asset_path(row)
            path.write_bytes(changed)

            started = client.post(
                "/settings/content-identity/backfill",
                headers=headers,
                json={"verify_all": True},
            )
            assert started.status_code == 200
            assert started.json()["started"] is True

            terminal = None
            for _ in range(100):
                terminal = client.get(
                    "/settings/content-identity", headers=headers
                ).json()
                if terminal and terminal["status"] != "running":
                    break
                time.sleep(0.01)
            assert terminal["status"] == "completed_with_findings"
            assert terminal["changed"] == 1

            revision = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()[0]
            assert revision["content_state"] == "changed"
            assert revision["content_reason"] == "digest_mismatch"
            assert revision["sha256"] == original_digest
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)
