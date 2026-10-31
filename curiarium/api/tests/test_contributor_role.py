"""What a contributor may and may not do, end to end through the real routes.

Why this file exists: `tests/test_permissions_matrix.py` proves *per route* that
the matrix and the guards agree, but a level is only worth having if the action a
person actually performs works. Mf-01f0 split the old write level in two, so the
risk this suite covers is the opposite of the sweep's: not "did a route lose its
level" but "does a contributor get through the whole contribute workflow" -
upload, tag, add a supporting file, create folders and projects, edit membership
- while every destructive route stays an editor's move.

Three things here are deliberately *not* covered by the matrix sweep and need
their own assertions:

* the `/asset/{id}/meta` route declares contribute but escalates a `name`/`title`
  edit to write from inside the handler, before the 404 lookup (AC-8). The sweep
  cannot express that: its one meta call sends notes only, and a second spec for
  the same key would break `test_every_route_has_an_expectation_or_a_documented_reason`;
* a demotion has to bite the session the caller already holds, without a
  re-login (`require_auth` re-reads `users.role` per request);
* the audit row for a contributor's action must name the contributor role
  (AC-7), which is an audit question, not a permission one.

The harness is self-contained on purpose (no import from the matrix suite): a
shared helper would make one file's fixture change silently redefine the other's
sweeps.
"""

from dataclasses import dataclass
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, delete, select

import accounts
import asset_file_service
import asset_service
import audit
import db
import library_scan
import login_throttle as login_throttle_module
import main
import permissions
import settings_service
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, AuditEvent, Folder, MfaRecoveryCode, Project, ProjectAsset, User, UserSession

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
EDITOR_USERNAME = "editor"
EDITOR_PASSWORD = "editor-password-1"
CONTRIBUTOR_USERNAME = "contributor"
CONTRIBUTOR_PASSWORD = "contributor-password-1"
VIEWER_USERNAME = "viewer"
VIEWER_PASSWORD = "viewer-password-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}

# Smallest valid STL body: the upload route only stores bytes, it never parses them.
STL_BYTES = b"solid cube\nendsolid cube\n"
REQUEST_ID_HEADER = "X-Request-ID"


# --- harness ----------------------------------------------------------------


def truncate_accounts() -> None:
    with Session(engine) as db:
        db.execute(delete(MfaRecoveryCode))
        db.execute(delete(UserSession))
        db.execute(delete(User))
        db.commit()


@pytest.fixture(autouse=True)
def clean_accounts():
    """Migrate once, then start and finish every test without accounts."""
    run_migrations(engine)
    truncate_accounts()
    login_throttle_module.limiter.reset()
    yield
    truncate_accounts()
    login_throttle_module.limiter.reset()


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use argon2's floor parameters, in this file only.

    Every test bootstraps an admin plus a contributor and signs both in; at the
    library defaults each hash or verify costs ~50 ms. Nothing here asserts
    anything about hashing, so a cheap hasher only keeps the suite affordable.
    """
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point every storage binding at a temp root and undo the rows a test made.

    The database is shared for the whole session, so folders, assets and
    projects are removed afterwards: a leaked row would be a 409 (or a wrong
    count) in the next test file.
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
        # Projects first: membership rows point at both a project and an asset.
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
        # Audit rows are never cleaned up: the table's triggers refuse DELETE by
        # design, so a leftover row is the same state every other suite leaves.
        session.commit()


@pytest.fixture()
def client():
    with TestClient(main.app) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def create_user(client: TestClient, token: str, username: str, password: str, role: str) -> dict:
    response = client.post(
        "/users",
        json={"username": username, "password": password, "role": role},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def ok(response: Response) -> Response:
    """Seed requests are infrastructure: anything but 200 means the harness broke."""
    assert response.status_code == 200, response.text
    return response


@dataclass(frozen=True)
class Actor:
    """One signed-in account: its token, its id and its role."""

    token: str
    id: str
    role: str


def sign_in(client: TestClient, token: str, username: str, password: str, role: str) -> Actor:
    """Create `username` with `role` and sign it in, through the real routes."""
    user = create_user(client, token, username, password, role)
    session = login(client, username, password)
    return Actor(token=session["token"], id=user["id"], role=role)


@pytest.fixture()
def admin(client: TestClient) -> Actor:
    """The break-glass admin promoted to a real account, because the API needs one.

    Break-glass creates the first admin; that insert revokes the break-glass
    session in the same transaction, so every later request signs in as the real
    admin account.
    """
    glass = login(client, **BREAK_GLASS)
    user = create_user(client, glass["token"], ADMIN_USERNAME, ADMIN_PASSWORD, "admin")
    session = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    return Actor(token=session["token"], id=user["id"], role="admin")


@pytest.fixture()
def contributor(client: TestClient, admin: Actor) -> Actor:
    return sign_in(client, admin.token, CONTRIBUTOR_USERNAME, CONTRIBUTOR_PASSWORD, "contributor")


@pytest.fixture()
def editor(client: TestClient, admin: Actor) -> Actor:
    return sign_in(client, admin.token, EDITOR_USERNAME, EDITOR_PASSWORD, "editor")


def upload(client: TestClient, token: str, filename: str = "cube.stl") -> dict:
    """One real upload: the contributor's own asset, so a 403 later is not a 404."""
    response = ok(
        client.post(
            "/upload",
            files={"file": (filename, STL_BYTES, "model/stl")},
            headers=bearer(token),
        )
    )
    return response.json()


def create_folder(client: TestClient, token: str, name: str) -> Response:
    return client.post("/folders", json={"name": name}, headers=bearer(token))


def create_project(client: TestClient, token: str, name: str) -> Response:
    return client.post("/projects", json={"name": name}, headers=bearer(token))


def add_supporting_file(client: TestClient, token: str, asset_id: str, filename: str = "notes.txt") -> dict:
    """Attach one supporting file and return its row.

    The POST answers with the *asset* (it is the asset card that refreshes), so
    the new row is read back from the list - which is also what proves the file
    really landed.
    """
    ok(
        client.post(
            f"/asset/{asset_id}/files",
            files={"file": (filename, b"layer notes\n", "text/plain")},
            headers=bearer(token),
        )
    )
    listed = ok(client.get(f"/asset/{asset_id}/files", headers=bearer(token))).json()
    matching = [row for row in listed if row["filename"] == filename]
    assert len(matching) == 1, listed
    return matching[0]


# --- the role exists and grants contribute ----------------------------------


def test_a_contributor_can_be_created_and_reports_its_role(client: TestClient, admin: Actor) -> None:
    """`contributor` is a creatable role, not just a string the rank table knows.

    If `POST /users` rejected the role the whole level would be unreachable, and
    if `/me` reported something else the client would render the wrong
    affordances; both are checked here rather than inferred from the matrix.
    """
    created = create_user(client, admin.token, CONTRIBUTOR_USERNAME, CONTRIBUTOR_PASSWORD, "contributor")
    assert created["role"] == "contributor"

    session = login(client, CONTRIBUTOR_USERNAME, CONTRIBUTOR_PASSWORD)
    me = client.get("/me", headers=bearer(session["token"]))
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "contributor"
    assert me.json()["id"] == created["id"]


def test_a_contributor_can_create_a_folder_and_a_project(client: TestClient, contributor: Actor) -> None:
    """Organising is contribute: a folder makes a directory, a project is row-only.

    Both were editor-only before the split, so they are the clearest statement
    of what the new rank is for: a contributor creates containers and rows, and
    never destroys what is already on disk.
    """
    folder = create_folder(client, contributor.token, "Contributor Shelf")
    assert folder.status_code == 200, folder.text
    assert folder.json()["name"] == "Contributor Shelf"

    project = create_project(client, contributor.token, "Contributor Project")
    assert project.status_code == 201, project.text
    assert project.json()["name"] == "Contributor Project"


def test_a_contributor_can_upload_and_tag_and_add_a_supporting_file(
    client: TestClient, contributor: Actor
) -> None:
    """The upload workspace a contributor works in has to be complete.

    A contributor who could upload but not tag would have to hand an editor the
    asset they just created, and one who could not add a supporting file could
    not attach a slicer profile. Removing project membership is included because
    it is the one DELETE a contributor holds: the join row goes, the bytes stay.
    """
    asset = upload(client, contributor.token)

    tags = client.post(f"/asset/{asset['id']}/tags", json={"tags": ["benchmark"]}, headers=bearer(contributor.token))
    assert tags.status_code == 200, tags.text
    assert "benchmark" in tags.json()["tags"]

    supporting = add_supporting_file(client, contributor.token, asset["id"])
    assert supporting["filename"] == "notes.txt"
    assert supporting["mime"] == "text/plain"

    project = create_project(client, contributor.token, "Membership Project")
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    added = client.post(
        f"/project/{project_id}/assets",
        json={"asset_ids": [asset["id"]]},
        headers=bearer(contributor.token),
    )
    assert added.status_code == 200, added.text
    assert added.json()["added"] == [asset["id"]]

    # A DELETE with a JSON body: send it through request() explicitly.
    removed = client.request(
        "DELETE",
        f"/project/{project_id}/assets",
        json={"asset_ids": [asset["id"]]},
        headers=bearer(contributor.token),
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["removed"] == [asset["id"]]


def test_a_contributor_cannot_destroy_anything(client: TestClient, contributor: Actor) -> None:
    """Every destructive route answers 403 with the write detail, not 404.

    The rows are created first and owned by the contributor, so each 403 is a
    permission answer about an object that exists - a 404 would pass a looser
    assertion while proving the guard never ran. The guard runs in the route
    dependency, before any handler can touch the host, so no snapshot fake is
    needed here.
    """
    asset = upload(client, contributor.token)
    folder = ok(create_folder(client, contributor.token, "Doomed Shelf")).json()
    project = create_project(client, contributor.token, "Doomed Project")
    assert project.status_code == 201, project.text

    denials = {
        "asset": client.delete(
            f"/asset/{asset['id']}", params={"confirm_name": asset["filename"]}, headers=bearer(contributor.token)
        ),
        "folder": client.delete(f"/folder/{folder['id']}", params={"confirm_name": folder["name"]}, headers=bearer(contributor.token)),
        "project": client.delete(f"/project/{project.json()['id']}", headers=bearer(contributor.token)),
        "batch": client.post(
            "/assets/batch/delete",
            json={"asset_ids": [asset["id"]], "confirm_count": 1},
            headers=bearer(contributor.token),
        ),
    }

    for name, response in denials.items():
        assert response.status_code == 403, f"a contributor was allowed to delete a {name}: {response.status_code} {response.text}"
        assert response.json()["detail"] == permissions.DENY_DETAIL[permissions.WRITE]


def test_a_contributor_demoted_to_viewer_loses_contribute(client: TestClient, admin: Actor, contributor: Actor) -> None:
    """A demotion bites the session the contributor already holds.

    No re-login and no revocation: `require_auth` re-reads `users.role` per
    request, so the *same* token is the proof that the demotion is live. If the
    role were cached on the session row this test would pass only by accident
    of a re-login, which is why the token is deliberately not refreshed.
    """
    assert create_folder(client, contributor.token, "Before Demotion").status_code == 200

    demoted = client.patch(f"/users/{contributor.id}", json={"role": "viewer"}, headers=bearer(admin.token))
    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["role"] == "viewer"

    denied = create_folder(client, contributor.token, "After Demotion")
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"] == permissions.DENY_DETAIL[permissions.CONTRIBUTE]
    # Reads still work with the same token: only the rank it carries dropped.
    assert client.get("/assets", headers=bearer(contributor.token)).status_code == 200


# --- the meta route escalates a rename to write ------------------------------


def test_the_meta_route_escalates_a_rename_to_write(client: TestClient, contributor: Actor, editor: Actor) -> None:
    """AC-8: `/asset/{id}/meta` is contribute for metadata and write for a rename.

    The route cannot declare two levels, so the escalation is an explicit
    `authorize()` call in the handler. Four things have to hold at once:

    * a notes edit succeeds for a contributor, and the 200 is real (the row
      changed), otherwise "escalates" could be satisfied by a route that refuses
      everything;
    * `name` and `title` both escalate - `title` is the rename fallback;
    * a rename request for a *missing* asset answers 403, not 404, because the
      escalation runs before the lookup (no existence oracle);
    * an editor still renames, so the escalation did not turn today's powers
      into a regression.
    """
    asset = upload(client, contributor.token, "cube.stl")

    notes = client.post(f"/asset/{asset['id']}/meta", json={"notes": "a note"}, headers=bearer(contributor.token))
    assert notes.status_code == 200, notes.text
    assert notes.json()["notes"] == "a note"

    for body in ({"name": "renamed.stl"}, {"title": "renamed"}):
        denied = client.post(f"/asset/{asset['id']}/meta", json=body, headers=bearer(contributor.token))
        assert denied.status_code == 403, f"a contributor renamed with {sorted(body)}: {denied.status_code} {denied.text}"
        assert denied.json()["detail"] == permissions.DENY_DETAIL[permissions.WRITE]

    # The existence-oracle guard: a rename for an id that does not exist is
    # still refused on permission, so the answer says nothing about the row.
    missing = client.post("/asset/does-not-exist/meta", json={"name": "renamed.stl"}, headers=bearer(contributor.token))
    assert missing.status_code == 403, f"a rename on a missing asset leaked existence: {missing.status_code} {missing.text}"
    assert missing.json()["detail"] == permissions.DENY_DETAIL[permissions.WRITE]

    renamed = client.post(f"/asset/{asset['id']}/meta", json={"name": "renamed.stl"}, headers=bearer(editor.token))
    assert renamed.status_code == 200, renamed.text
    # The metadata editor takes a model name, so the typed suffix is stripped.
    assert renamed.json()["name"] == "renamed"


# --- the contributor's actions are audited as the contributor ---------------


def test_a_contributor_action_is_audited_with_the_contributor_role(client: TestClient, contributor: Actor) -> None:
    """AC-7: rows written on a contribute route name the actor as a contributor.

    A support bundle that says "editor" for a contributor's action would make the
    audit trail useless exactly where the new rank is asked about. A supporting
    file rename is used because it is the audited CONTRIBUTE route that records
    a metadata-only edit, with its own action; a notes-only `/asset/{id}/meta`
    edit stages nothing. `POST /upload` also writes a row now (creation is
    audited, Mf-0u1y) but that is a different action.
    """
    asset = upload(client, contributor.token)
    supporting = add_supporting_file(client, contributor.token, asset["id"])

    value = f"contributor-audit-{uuid4().hex}"
    renamed = client.patch(
        f"/asset/{asset['id']}/files/{supporting['id']}",
        json={"filename": f"renamed-{uuid4().hex}.txt"},
        headers={**bearer(contributor.token), REQUEST_ID_HEADER: value},
    )
    assert renamed.status_code == 200, renamed.text

    with Session(engine) as session:
        rows = list(session.exec(select(AuditEvent).where(AuditEvent.request_id == value)))
    assert len(rows) == 1, [row.action for row in rows]
    row = rows[0]
    assert row.action == audit.ASSET_FILE_RENAME
    assert row.actor_role == "contributor"
    assert row.actor == CONTRIBUTOR_USERNAME

    # The split changed because creation is audited now (Mf-0u1y), not because
    # a level moved: the upload route moved from exempt to audited, and the
    # coverage guard sees 41 audited / 14 exempt routes.
    assert audit.ROUTE_ACTIONS[("POST", "/upload")] == (audit.ASSET_CREATE,)
    assert audit.assert_audit_coverage() is audit.ROUTE_ACTIONS
    assert len(audit.ROUTE_ACTIONS) == 41
    assert len(audit.EXEMPT_ROUTES) == 14
