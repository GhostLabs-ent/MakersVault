"""With auth disabled every guard must stay open and every auth endpoint 503.

Proxy-only deployments run this way: the reverse proxy authenticates, the API
only has to keep answering. The endpoints read `auth.AUTH_ENABLED` at request
time, so monkeypatching it must be enough.
"""

import pytest
from fastapi.testclient import TestClient

import auth
import main
from version import __version__

NOT_CONFIGURED = "Authentication is not configured on the server"


@pytest.fixture()
def disabled_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    with TestClient(main.app) as test_client:
        yield test_client


def test_health_reports_auth_is_off(disabled_client: TestClient) -> None:
    assert disabled_client.get("/health").json() == {"ok": True, "auth_required": False, "version": __version__}


@pytest.mark.parametrize("path", ["/login", "/refresh", "/logout"])
def test_auth_post_endpoints_answer_503(disabled_client: TestClient, path: str) -> None:
    response = disabled_client.post(path, json={"username": "admin", "password": "super-secret"})

    assert response.status_code == 503
    assert response.json()["detail"] == NOT_CONFIGURED


@pytest.mark.parametrize("path", ["/me", "/users"])
def test_auth_read_endpoints_answer_503(disabled_client: TestClient, path: str) -> None:
    response = disabled_client.get(path)

    assert response.status_code == 503
    assert response.json()["detail"] == NOT_CONFIGURED


def test_library_stays_open_without_a_token(disabled_client: TestClient) -> None:
    assert disabled_client.get("/assets").status_code == 200
