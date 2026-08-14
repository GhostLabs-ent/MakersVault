from fastapi.testclient import TestClient
from fastapi import HTTPException

import main
from main import app


def test_health_and_authenticated_library_smoke() -> None:
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"ok": True, "auth_required": True}

        assert client.get("/assets").status_code == 401

        login = client.post(
            "/login",
            json={"username": "admin", "password": "test-only-password"},
        )
        assert login.status_code == 200
        token = login.json()["token"]

        assets = client.get(
            "/assets",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert assets.status_code == 200
        assert assets.json() == []


def test_failed_primary_upload_removes_database_record(monkeypatch) -> None:
    async def reject_upload(*_args, **_kwargs):
        raise HTTPException(status_code=413, detail="Uploaded file exceeds size limit")

    monkeypatch.setattr(main, "stream_upload_to_file", reject_upload)
    with TestClient(app) as client:
        login = client.post(
            "/login",
            json={"username": "admin", "password": "test-only-password"},
        )
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        before = client.get("/assets", headers=headers).json()

        response = client.post(
            "/upload",
            headers=headers,
            files={"file": ("large.stl", b"solid", "model/stl")},
        )

        assert response.status_code == 413
        assert client.get("/assets", headers=headers).json() == before
