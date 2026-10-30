import logging

import pytest
from fastapi.testclient import TestClient

import config
import login_throttle
from main import app

ADMIN = {"username": "admin", "password": "super-secret"}
WRONG = {"username": "admin", "password": "wrong-password"}
THROTTLE_DETAIL = "Too many failed login attempts. Try again later."
MAX_FAILURES = 3
WINDOW_SECONDS = 60
LOCKOUT_SECONDS = 2
MAX_LOCKOUT_SECONDS = 8


@pytest.fixture(autouse=True)
def throttle_clock(monkeypatch):
    """Freeze the throttle clock and use fast, deterministic limits."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(login_throttle, "_now", lambda: clock["now"])
    monkeypatch.setattr(config, "LOGIN_THROTTLE_ENABLED", True)
    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES", MAX_FAILURES)
    monkeypatch.setattr(config, "LOGIN_FAILURE_WINDOW_SECONDS", WINDOW_SECONDS)
    monkeypatch.setattr(config, "LOGIN_LOCKOUT_SECONDS", LOCKOUT_SECONDS)
    monkeypatch.setattr(config, "LOGIN_MAX_LOCKOUT_SECONDS", MAX_LOCKOUT_SECONDS)
    login_throttle.limiter.reset()
    yield clock
    login_throttle.limiter.reset()


def post_login(client: TestClient, credentials: dict):
    return client.post("/login", json=credentials)


def lock_username(client: TestClient, username: str):
    """Exhaust a username's failure budget and return the first throttled response."""
    credentials = {"username": username, "password": "wrong-password"}
    for _ in range(MAX_FAILURES):
        assert post_login(client, credentials).status_code == 401
    response = post_login(client, credentials)
    assert response.status_code == 429
    return response


def lock_account(client: TestClient):
    return lock_username(client, "admin")


def test_correct_credentials_work_below_threshold_and_clear_history():
    with TestClient(app) as client:
        for _ in range(MAX_FAILURES - 1):
            assert post_login(client, WRONG).status_code == 401
        assert post_login(client, ADMIN).status_code == 200
        # the success cleared the bucket: this failure starts a fresh run
        assert post_login(client, WRONG).status_code == 401


def test_threshold_failure_locks_out_even_correct_credentials():
    with TestClient(app) as client:
        for _ in range(MAX_FAILURES):
            assert post_login(client, WRONG).status_code == 401
        locked = post_login(client, ADMIN)
        assert locked.status_code == 429
        assert locked.json()["detail"] == THROTTLE_DETAIL
        retry_after = locked.headers["Retry-After"]
        assert retry_after.isdigit()
        assert int(retry_after) >= 1

        blocked = post_login(client, ADMIN)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == THROTTLE_DETAIL
        assert blocked.headers["Retry-After"].isdigit()
        assert int(blocked.headers["Retry-After"]) >= 1


def test_lockout_expiry_restores_login(throttle_clock):
    with TestClient(app) as client:
        lock_account(client)
        assert post_login(client, ADMIN).status_code == 429

        throttle_clock["now"] += LOCKOUT_SECONDS + 1
        assert post_login(client, ADMIN).status_code == 200


def test_repeated_strikes_double_and_cap_lockout(throttle_clock):
    with TestClient(app) as client:
        first = lock_account(client)
        first_retry = int(first.headers["Retry-After"])
        assert first_retry == LOCKOUT_SECONDS

        throttle_clock["now"] += LOCKOUT_SECONDS + 1
        second = lock_account(client)
        second_retry = int(second.headers["Retry-After"])
        assert second_retry == first_retry * 2

        # further strikes keep doubling until the configured ceiling
        for expected in (MAX_LOCKOUT_SECONDS, MAX_LOCKOUT_SECONDS):
            throttle_clock["now"] += second_retry + 1
            response = lock_account(client)
            second_retry = int(response.headers["Retry-After"])
            assert second_retry == expected


def test_lockout_is_scoped_to_one_username():
    with TestClient(app) as client:
        lock_account(client)
        assert post_login(client, ADMIN).status_code == 429

        other = post_login(client, {"username": "intruder", "password": "nope"})
        assert other.status_code == 401


def test_disabled_throttle_never_locks(monkeypatch):
    monkeypatch.setattr(config, "LOGIN_THROTTLE_ENABLED", False)
    with TestClient(app) as client:
        for _ in range(MAX_FAILURES * 3):
            assert post_login(client, WRONG).status_code == 401


def test_failures_and_lockouts_are_logged_without_the_password(caplog):
    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            lock_account(client)

    assert "Failed login attempt for username 'admin' from testclient" in caplog.text
    assert "Login throttled for username 'admin' from testclient" in caplog.text
    assert WRONG["password"] not in caplog.text


def test_all_locked_overflow_sentinel_throttles_new_usernames(monkeypatch):
    monkeypatch.setattr(login_throttle, "MAX_BUCKETS", 2)
    with TestClient(app) as client:
        lock_username(client, "admin")
        lock_username(client, "intruder")

        # No bucket is evictable, so the next new username falls back to the
        # shared overflow throttle instead of clearing a real lockout.
        assert post_login(client, {"username": "third", "password": "nope"}).status_code == 401
        overflow = post_login(client, {"username": "third", "password": "nope"})
        assert overflow.status_code == 429
        assert overflow.headers["Retry-After"] == str(login_throttle.OVERFLOW_RETRY_AFTER)
        assert post_login(client, ADMIN).status_code == 429


def test_username_spray_cannot_evict_an_active_lockout(monkeypatch):
    monkeypatch.setattr(login_throttle, "MAX_BUCKETS", 3)
    with TestClient(app) as client:
        lock_account(client)
        for index in range(20):
            response = post_login(client, {"username": f"junk-{index}", "password": "nope"})
            assert response.status_code in (401, 429)
        # active lockouts survive eviction pressure from other usernames
        assert post_login(client, ADMIN).status_code == 429


def test_usernames_are_normalized_and_truncated():
    with TestClient(app) as client:
        for _ in range(MAX_FAILURES - 1):
            assert post_login(client, {"username": " admin ", "password": "nope"}).status_code == 401
        # " admin " and "admin" share one bucket, so this reaches the limit
        assert post_login(client, {"username": "admin", "password": "nope"}).status_code == 401
        assert post_login(client, {"username": "admin", "password": "nope"}).status_code == 429

    assert login_throttle.normalize_username(" Admin ") == "Admin"
    assert login_throttle.normalize_username("  ") == ""
    assert login_throttle.normalize_username("x" * 500) == "x" * 128

    with TestClient(app) as client:
        oversized = post_login(client, {"username": "y" * 500, "password": "nope"})
        assert oversized.status_code == 401


def test_new_lifespan_context_starts_with_clean_throttle_state():
    with TestClient(app) as client:
        lock_account(client)
        assert post_login(client, ADMIN).status_code == 429

    with TestClient(app) as client:
        assert post_login(client, ADMIN).status_code == 200
