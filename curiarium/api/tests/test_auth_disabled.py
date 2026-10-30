"""With auth disabled every guard must stay open and every auth endpoint 503.

Proxy-only deployments run this way: the reverse proxy authenticates, the API
only has to keep answering. The endpoints read `auth.AUTH_ENABLED` at request
time, so monkeypatching it must be enough.
"""

import pytest
from fastapi.testclient import TestClient

import auth
import config
import main
import oidc
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


@pytest.mark.parametrize(
    "path",
    ["/auth/oidc/status", "/auth/oidc/start", "/auth/oidc/callback"],
)
def test_oidc_get_endpoints_answer_503(disabled_client: TestClient, path: str) -> None:
    response = disabled_client.get(path, follow_redirects=False)

    assert response.status_code == 503
    assert response.json()["detail"] == NOT_CONFIGURED


def test_oidc_exchange_answers_503(disabled_client: TestClient) -> None:
    response = disabled_client.post("/auth/oidc/exchange", json={"code": "anything"})

    assert response.status_code == 503
    assert response.json()["detail"] == NOT_CONFIGURED


def test_oidc_enabled_without_auth_refuses_to_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """The combination that would silently produce an unauthenticated deployment.

    With auth off every route answers anyway, so an SSO login on top of it would
    be a login page for a door with no lock. The boot must stop, not the request.
    """
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    monkeypatch.setattr(config, "OIDC_ENABLED", True)
    monkeypatch.setattr(config, "OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setattr(config, "OIDC_CLIENT_ID", "client")
    monkeypatch.setattr(config, "OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setattr(config, "OIDC_ALLOWED_GROUPS", "staff")
    monkeypatch.setenv("PUBLIC_URL", "https://vault.example.com")

    with pytest.raises(RuntimeError) as excinfo:
        oidc.validate_oidc_configuration()
    assert "AUTH_ENABLED" in str(excinfo.value)


def test_library_stays_open_without_a_token(disabled_client: TestClient) -> None:
    assert disabled_client.get("/assets").status_code == 200
