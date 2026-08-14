import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from http_security import HostPolicyMiddleware, SecurityHeadersMiddleware, host_is_allowed, resolve_trusted_hosts
from login_security import LoginAttemptLimiter
from main import app


def test_login_limiter_progresses_expires_and_stays_bounded() -> None:
    now = [100.0]
    limiter = LoginAttemptLimiter(
        idle_ttl_seconds=15,
        max_entries=4,
        clock=lambda: now[0],
    )

    assert limiter.record_failure("client-a", "admin") == 0
    assert limiter.record_failure("client-a", "admin") == 0
    assert limiter.record_failure("client-a", "admin") == 1
    assert limiter.retry_after("client-a", "different-name") == 1

    now[0] += 1
    assert limiter.record_failure("client-a", "admin") == 2
    assert limiter.retry_after("client-a", "admin") == 2

    for index in range(10):
        limiter.record_failure(f"client-{index}", f"user-{index}")
    assert limiter.entry_count() <= 4

    now[0] += 16
    assert limiter.retry_after("client-a", "admin") == 0
    assert limiter.entry_count() == 0


def test_login_endpoint_throttles_without_logging_secrets(monkeypatch, caplog) -> None:
    now = [100.0]
    limiter = LoginAttemptLimiter(clock=lambda: now[0])
    monkeypatch.setattr(main, "login_limiter", limiter)
    password = "never-log-this-password"

    with caplog.at_level(logging.INFO, logger="makersvault.security"):
        with TestClient(app) as client:
            for _ in range(3):
                response = client.post(
                    "/login",
                    json={"username": "admin", "password": password},
                )
                assert response.status_code == 401
                assert response.json()["detail"] == "Invalid username or password"

            limited = client.post(
                "/login",
                json={"username": "another-name", "password": password},
            )
            assert limited.status_code == 429
            assert limited.headers["retry-after"] == "1"

            now[0] += 1
            success = client.post(
                "/login",
                json={"username": "admin", "password": "test-only-password"},
            )
            assert success.status_code == 200
            issued_token = success.json()["token"]

    log_output = caplog.text
    assert "login_failed source=testclient" in log_output
    assert "login_throttled source=testclient" in log_output
    assert "login_succeeded source=testclient" in log_output
    assert password not in log_output
    assert issued_token not in log_output


def test_trusted_host_resolution_and_matching() -> None:
    derived = resolve_trusted_hosts({"PUBLIC_URL": "https://Vault.Example:8443/library"})
    assert "vault.example" in derived
    assert host_is_allowed("vault.example:443", derived)
    assert host_is_allowed("127.0.0.1:8000", derived)
    assert not host_is_allowed("attacker.example", derived)

    explicit = resolve_trusted_hosts({"TRUSTED_HOSTS": "api.example,*.vault.lan"})
    assert host_is_allowed("api.example", explicit)
    assert host_is_allowed("printer.vault.lan:8000", explicit)
    assert not host_is_allowed("vault.lan.attacker.example", explicit)
    assert not host_is_allowed("api.example:invalid", explicit)
    assert resolve_trusted_hosts({}) == ["*"]


def test_api_security_headers_are_present() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert "camera=()" in response.headers["permissions-policy"]


def test_host_policy_rejects_unlisted_host_with_security_headers() -> None:
    protected = FastAPI()
    protected.add_middleware(HostPolicyMiddleware, allowed_hosts=["vault.example"])
    protected.add_middleware(SecurityHeadersMiddleware)

    @protected.get("/health")
    def health():
        return {"ok": True}

    with TestClient(protected, base_url="https://vault.example") as client:
        assert client.get("/health").status_code == 200
        rejected = client.get("/health", headers={"Host": "attacker.example"})
    assert rejected.status_code == 400
    assert rejected.headers["x-content-type-options"] == "nosniff"
