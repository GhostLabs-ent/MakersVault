from fastapi.testclient import TestClient

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
