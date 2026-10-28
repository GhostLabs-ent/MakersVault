"""Regression tests for the hardening batch.

Each test here corresponds to a specific defect that shipped in the upstream
baseline, so that it cannot come back silently.
"""
import pytest
from fastapi.testclient import TestClient

import auth
import db
import main
import multipart_stream
from db import engine
from file_utils import sanitize_path_segment
from import_resolvers import is_makerworld_page_host
from models import Asset

# --- C1: published sample credentials must not be usable by default ----------

def test_startup_refuses_published_sample_credentials(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_ALLOW_INSECURE_DEFAULTS", False)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", auth.INSECURE_DEFAULT_PASSWORD)
    monkeypatch.setattr(auth, "AUTH_SECRET", "a-properly-random-secret")
    with pytest.raises(RuntimeError) as excinfo:
        auth.validate_auth_configuration()
    assert "AUTH_PASSWORD" in str(excinfo.value)


def test_startup_refuses_default_jwt_secret(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_ALLOW_INSECURE_DEFAULTS", False)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "a-real-password")
    monkeypatch.setattr(auth, "AUTH_SECRET", auth.INSECURE_DEFAULT_SECRET)
    with pytest.raises(RuntimeError) as excinfo:
        auth.validate_auth_configuration()
    assert "AUTH_SECRET" in str(excinfo.value)


def test_startup_accepts_real_credentials(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_ALLOW_INSECURE_DEFAULTS", False)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", "a-real-password")
    monkeypatch.setattr(auth, "AUTH_SECRET", "a-properly-random-secret")
    auth.validate_auth_configuration()


def test_startup_allows_disabled_auth_and_explicit_opt_out(monkeypatch):
    # proxy-only deployments run with auth disabled; the guard must not fire
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    monkeypatch.setattr(auth, "AUTH_ALLOW_INSECURE_DEFAULTS", False)
    monkeypatch.setattr(auth, "AUTH_SECRET", auth.INSECURE_DEFAULT_SECRET)
    auth.validate_auth_configuration()

    # deliberately opting back into the sample credentials is allowed
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_ALLOW_INSECURE_DEFAULTS", True)
    monkeypatch.setattr(auth, "AUTH_PASSWORD", auth.INSECURE_DEFAULT_PASSWORD)
    auth.validate_auth_configuration()


# --- C2: a failed upload must not leave an orphan row or partial file --------

def test_failed_upload_leaves_no_orphan_row(monkeypatch):
    def boom(_sink, _data):
        raise OSError("storage went away")

    monkeypatch.setattr(multipart_stream.FileSink, "write", boom)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        res = client.post(
            "/upload",
            files={"file": ("cube.stl", b"solid cube\nendsolid cube\n", "model/stl")},
            headers=auth_header(client),
        )
        assert res.status_code == 500
        assert client.get("/assets", headers=auth_header(client)).json() == []
        assert list(db.STORAGE.rglob("cube.stl")) == []
        incoming = db.STORAGE / ".incoming"
        assert not incoming.exists() or list(incoming.iterdir()) == []


def test_oversized_upload_rejected_without_orphan(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        res = client.post(
            "/upload",
            files={"file": ("big.stl", b"x" * 4096, "model/stl")},
            headers=auth_header(client),
        )
        assert res.status_code == 413
        assert client.get("/assets", headers=auth_header(client)).json() == []


def test_successful_upload_still_works():
    payload = b"solid cube\nendsolid cube\n"
    with TestClient(main.app, raise_server_exceptions=False) as client:
        res = client.post(
            "/upload",
            files={"file": ("good.stl", payload, "model/stl")},
            headers=auth_header(client),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["size"] == len(payload)
        assets = client.get("/assets", headers=auth_header(client)).json()
        assert [a["id"] for a in assets] == [body["id"]]
        # leave the library clean for other tests
        assert client.delete(f"/asset/{body['id']}", headers=auth_header(client)).status_code == 200


# --- H2: sqlite must be in WAL mode with a busy timeout ----------------------

def test_sqlite_uses_wal_and_busy_timeout():
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 10000
        # migration 007 relies on FK enforcement, so every pooled connection
        # must have it on, not just the one that happened to write last
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


# --- M2: session cookies must not leak to look-alike domains -----------------

@pytest.mark.parametrize("host", ["evil-makerworld.com", "notmakerworld.com", "makerworld.com.evil.io"])
def test_makerworld_host_check_rejects_lookalikes(host):
    assert is_makerworld_page_host(host) is False


@pytest.mark.parametrize("host", ["makerworld.com", "www.makerworld.com", "makerworld.com"])
def test_makerworld_host_check_accepts_real_host(host):
    assert is_makerworld_page_host(host) is True


# --- M3: download zips must not contain traversal entries -------------------

@pytest.mark.parametrize("label", ["../../etc", "..", "./hidden", "a/b", "C:\\temp"])
def test_zip_arcnames_are_sanitised(label):
    asset = Asset(name="model", filename="cube.stl", mime="model/stl", size=1, folder_id="f1")
    arcname = main.arcname_for_asset(asset, {"f1": label})
    parts = arcname.split("/")
    assert len(parts) == 2, arcname
    assert all(part not in {"", ".", ".."} for part in parts), arcname
    assert not arcname.startswith("/")
    assert "\\" not in arcname


@pytest.mark.parametrize("value,expected", [
    ("plain", "plain"),
    ("../../etc", "_.._etc"),
    ("..", "item"),
    ("  spaced  ", "spaced"),
])
def test_sanitize_path_segment(value, expected):
    assert sanitize_path_segment(value) == expected


# --- helpers ----------------------------------------------------------------

def auth_header(client: TestClient) -> dict:
    """Bearer token, or empty when the app is running with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}
