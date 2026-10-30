"""Who added each asset, and by which door (Mf-0u1y).

The matrix is the cross-path one: every route that can create an asset row is
driven for real - the network is the only thing faked, through the documented
`main` patch points - and the same three facts are asserted each time:

* the API response carries `(created_by, created_via)`;
* the stored row carries the same pair;
* EXACTLY ONE `asset.create` row exists, whose actor is that same username and
  whose target IS the asset id, so `GET /audit?target=<id>` cross-links them.

The anonymous case (authentication disabled) is the other half of the contract:
a row created with no principal is honestly `(None, 'upload')`, and its audit row
still names the fixed `local` actor.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import uuid4
from zipfile import ZipFile

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

import accounts
import asset_file_service
import asset_service
import audit
import auth
import db
import import_service
import library_scan
import login_throttle as login_throttle_module
import main
import settings_service
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, AuditEvent, Folder, Project, ProjectAsset, User, UserSession

BREAK_GLASS = {"username": "admin", "password": "super-secret"}
ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
CONTRIBUTOR_USERNAME = "ada"
CONTRIBUTOR_PASSWORD = "ada-password-1"

STL_BYTES = b"solid cube\nendsolid cube\n"
REQUEST_ID_HEADER = "X-Request-ID"


def truncate_accounts() -> None:
    with Session(engine) as db_session:
        # Children first: these hold foreign keys onto users.
        db_session.execute(delete(UserSession))
        db_session.execute(delete(User))
        db_session.commit()


@pytest.fixture(autouse=True)
def clean_accounts():
    run_migrations(engine)
    truncate_accounts()
    login_throttle_module.limiter.reset()
    yield
    truncate_accounts()
    login_throttle_module.limiter.reset()


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argon2's floor parameters: every test here bootstraps an account."""
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """A temp storage root, and the rows this test created removed afterwards.

    Audit rows are deliberately not removed: the append-only triggers refuse it,
    so each test addresses its own rows by target instead.
    """
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(main, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_service, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    run_migrations(engine)

    template_before = settings_service.get_storage_template()
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        projects_before = {project.id for project in session.exec(select(Project))}

    yield storage

    settings_service.set_storage_template(template_before)
    with Session(engine) as session:
        # Projects first: the name index is case-insensitive, so a leaked row
        # would 409 the next test's seed.
        for membership in list(session.exec(select(ProjectAsset))):
            if membership.project_id not in projects_before:
                session.delete(membership)
        for project in list(session.exec(select(Project))):
            if project.id not in projects_before:
                session.delete(project)
        for asset_file in list(session.exec(select(AssetFile))):
            if asset_file.asset_id not in assets_before:
                session.delete(asset_file)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        session.commit()


@pytest.fixture()
def client():
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


@dataclass(frozen=True)
class Principal:
    """A real contributor, plus the admin token `/audit` needs to be read back."""

    username: str
    token: str
    admin_token: str


def create_user(client: TestClient, token: str, username: str, password: str, role: str) -> dict:
    response = client.post(
        "/users",
        json={"username": username, "password": password, "role": role},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def contributor(client: TestClient) -> Principal:
    """A real contributor, and a real admin token for reading `/audit` back.

    The break-glass admin exists only while the users table is empty, so it
    bootstraps one admin account and is then done.
    """
    glass = login(client, **BREAK_GLASS)
    create_user(client, glass["token"], ADMIN_USERNAME, ADMIN_PASSWORD, accounts.ADMIN_ROLE)
    admin_session = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    create_user(client, admin_session["token"], CONTRIBUTOR_USERNAME, CONTRIBUTOR_PASSWORD, accounts.CONTRIBUTOR_ROLE)
    session = login(client, CONTRIBUTOR_USERNAME, CONTRIBUTOR_PASSWORD)
    return Principal(CONTRIBUTOR_USERNAME, session["token"], admin_session["token"])


class FakeImportResponse:
    """The slice of a remote response the import service reads, and nothing else.

    No socket is ever opened: the seam stubs below hand the real
    `persist_asset_from_response` one of these.
    """

    def __init__(self, payload: bytes, filename: str = "model.stl", content_type: str = "model/stl"):
        self._payload = payload
        self._offset = 0
        self._url = f"https://example.com/{filename}"
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(payload))}

    def read(self, size: int) -> bytes:
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self._offset = len(self._payload)

    def __enter__(self) -> "FakeImportResponse":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def install_link_import_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """`POST /import`: real persist, fake transport."""

    def stub(url: str, body, *, origin=None):
        return import_service.persist_asset_from_response(FakeImportResponse(STL_BYTES), url, body, origin=origin)

    monkeypatch.setattr(main, "normalize_import_url", lambda url: url)
    monkeypatch.setattr(main, "import_asset_from_url", stub)


def install_single_attempt_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """`POST /import/project` without `entries`: real persist, fake transport."""

    def stub(url: str, body, *, origin=None):
        asset = import_service.persist_asset_from_response(FakeImportResponse(STL_BYTES), url, body, origin=origin)
        return import_service.ImportAttempt(asset=asset)

    monkeypatch.setattr(main, "normalize_import_url", lambda url: url)
    monkeypatch.setattr(main, "import_asset_attempt", stub)


def write_zip(directory: Path, entries: dict[str, bytes]) -> Path:
    path = directory / f"models-{uuid4().hex}.zip"
    with ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return path


def install_zip_download_stub(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """`POST /import/zip`: a real zip on disk, and the route's own unlink."""

    path = write_zip(tmp_path, {"a.stl": STL_BYTES})

    def stub(url: str, body):
        return path, "models.zip", "application/zip"

    monkeypatch.setattr(main, "normalize_import_url", lambda url: url)
    monkeypatch.setattr(main, "download_import_to_temp", stub)


def install_project_zip_stub(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """`POST /import/project` with `entries`: a real zip through the real extractor."""
    path = write_zip(tmp_path, {"a.stl": STL_BYTES})

    def stub(url: str, body):
        return import_service.ZipAttempt(tmp_path=path, filename="models.zip", mime="application/zip")

    monkeypatch.setattr(main, "normalize_import_url", lambda url: url)
    monkeypatch.setattr(main, "download_zip_attempt", stub)


def stored_row(asset_id: str) -> Asset:
    """The row straight from the database, not the response."""
    with Session(engine) as session:
        row = session.get(Asset, asset_id)
        assert row is not None, asset_id
        return row


def stored_attribution(asset_id: str) -> tuple[Optional[str], Optional[str]]:
    row = stored_row(asset_id)
    return row.created_by, row.created_via


def creation_events(asset_id: str) -> list[AuditEvent]:
    with Session(engine) as session:
        return list(
            session.exec(
                select(AuditEvent).where(AuditEvent.action == audit.ASSET_CREATE, AuditEvent.target == asset_id)
            )
        )


def assert_attributed(
    client: TestClient,
    admin_token: str,
    body: dict,
    *,
    actor: str,
    created_by: Optional[str],
    created_via: str,
) -> None:
    """The response, the row and the one audit row all agree, and cross-link."""
    asset_id = body["id"]
    assert (body["created_by"], body["created_via"]) == (created_by, created_via)

    assert stored_attribution(asset_id) == (created_by, created_via)
    name = stored_row(asset_id).name

    rows = creation_events(asset_id)
    assert len(rows) == 1, [row.action for row in rows]
    event = rows[0]
    assert event.actor == actor
    assert event.target == asset_id
    assert json.loads(event.detail_json) == {"via": created_via, "name": name}

    linked = client.get("/audit", params={"target": asset_id}, headers=bearer(admin_token))
    assert linked.status_code == 200, linked.text
    assert [item["id"] for item in linked.json()["events"]] == [event.id]


def test_an_upload_is_stamped_with_its_contributor(client: TestClient, contributor: Principal) -> None:
    response = client.post(
        "/upload",
        files={"file": ("uploaded.stl", STL_BYTES, "model/stl")},
        headers=bearer(contributor.token),
    )

    assert response.status_code == 200, response.text
    assert_attributed(
        client,
        contributor.admin_token,
        response.json(),
        actor=contributor.username,
        created_by=contributor.username,
        created_via="upload",
    )


def test_a_link_import_is_stamped_with_its_contributor(
    client: TestClient, contributor: Principal, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_link_import_stub(monkeypatch)

    response = client.post(
        "/import",
        json={"url": "https://example.com/model.stl"},
        headers=bearer(contributor.token),
    )

    assert response.status_code == 200, response.text
    assert_attributed(
        client,
        contributor.admin_token,
        response.json(),
        actor=contributor.username,
        created_by=contributor.username,
        created_via="link-import",
    )


def test_a_zip_import_is_stamped_with_its_contributor(
    client: TestClient, contributor: Principal, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    install_zip_download_stub(monkeypatch, tmp_path)

    response = client.post(
        "/import/zip",
        json={"url": "https://example.com/models.zip", "entries": ["a.stl"]},
        headers=bearer(contributor.token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["failed"] == []
    assert len(body["assets"]) == 1
    assert_attributed(
        client,
        contributor.admin_token,
        body["assets"][0],
        actor=contributor.username,
        created_by=contributor.username,
        created_via="zip-import",
    )


def test_a_single_file_project_import_is_a_link_import(
    client: TestClient, contributor: Principal, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_single_attempt_stub(monkeypatch)

    response = client.post(
        "/import/project",
        json={"url": "https://example.com/model.stl"},
        headers=bearer(contributor.token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["assets"]) == 1
    assert_attributed(
        client,
        contributor.admin_token,
        body["assets"][0],
        actor=contributor.username,
        created_by=contributor.username,
        created_via="link-import",
    )


def test_a_zip_project_import_is_a_zip_import(
    client: TestClient, contributor: Principal, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    install_project_zip_stub(monkeypatch, tmp_path)

    response = client.post(
        "/import/project",
        json={"url": "https://example.com/models.zip", "entries": ["a.stl"]},
        headers=bearer(contributor.token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["failed"] == []
    assert len(body["assets"]) == 1
    assert_attributed(
        client,
        contributor.admin_token,
        body["assets"][0],
        actor=contributor.username,
        created_by=contributor.username,
        created_via="zip-import",
    )


def test_a_bare_service_call_is_anonymous_system_and_writes_no_audit_row() -> None:
    """No origin means nobody made it: (NULL, 'system') and no event."""
    asset = asset_service.create_asset_record("bare.stl", "model/stl", "Bare", None, [], None)

    assert stored_attribution(asset.id) == (None, "system")
    assert creation_events(asset.id) == []


def test_the_anonymous_upload_is_recorded_as_local(
    client: TestClient, contributor: Principal, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-6: with authentication off there is no principal, and that is recorded."""
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)

    response = client.post("/upload", files={"file": ("anonymous.stl", STL_BYTES, "model/stl")})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_by"] is None
    assert body["created_via"] == "upload"
    assert stored_attribution(body["id"]) == (None, "upload")

    with Session(engine) as session:
        usernames = set(session.exec(select(User.username)).all())
    assert usernames, "the fixture created accounts, so this comparison is not vacuous"
    assert body["created_by"] not in usernames

    rows = creation_events(body["id"])
    assert len(rows) == 1
    assert rows[0].actor == audit.ACTOR_DISABLED_USERNAME
    assert rows[0].actor_role == audit.ACTOR_DISABLED_ROLE


def test_a_legacy_row_with_both_columns_null_still_serialises(client: TestClient, contributor: Principal) -> None:
    """AC-1's boundary: a pre-014 row is (NULL, NULL), not a 500."""
    with Session(engine) as session:
        legacy = Asset(
            id=str(uuid4()),
            name=f"Legacy {uuid4().hex[:8]}",
            filename="legacy.stl",
            mime="model/stl",
            size=1,
            storage_path="legacy.stl",
        )
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id

    response = client.get("/assets", params={"limit": 1000}, headers=bearer(contributor.token))

    assert response.status_code == 200, response.text
    listed = next(item for item in response.json() if item["id"] == legacy_id)
    assert listed["created_by"] is None
    assert listed["created_via"] is None
