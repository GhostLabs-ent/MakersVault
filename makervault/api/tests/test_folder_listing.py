import json

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, select

from main import app, engine
from models import Folder


def _login(client):
    response = client.post("/login", json={"username": "admin", "password": "test-only-password"})
    assert response.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


def test_large_folder_listing_preserves_values_without_hydrating_orm_objects():
    with TestClient(app) as client:
        _login(client)
        root = Folder(name='Root "日本語"', tags_json=json.dumps(["a", "a", "é"]))
        children = [Folder(name=f"Part {i}", parent_id=root.id, tags_json="") for i in range(1039)]
        folders = [root, *children]
        expected = {
            folder.id: {"id": folder.id, "name": folder.name,
                        "tags": json.loads(folder.tags_json or "[]"), "parent_id": folder.parent_id}
            for folder in folders
        }
        with Session(engine) as session:
            session.add_all(folders)
            session.commit()
        loaded = []
        def on_load(folder, context):
            loaded.append(folder.id)
        event.listen(Folder, "load", on_load)
        try:
            response = client.get("/folders")
            assert response.status_code == 200
            actual = {folder["id"]: folder for folder in response.json()}
            assert {key: actual[key] for key in expected} == expected
            assert loaded == []
        finally:
            event.remove(Folder, "load", on_load)
            with Session(engine) as session:
                for folder in session.exec(select(Folder).where(Folder.id.in_(expected))).all():
                    session.delete(folder)
                session.commit()


def test_folder_listing_immediately_reflects_create_edit_reparent_and_delete():
    with TestClient(app) as client:
        headers = _login(client)
        roots = []
        try:
            for name in ("Listing root A", "Listing root B"):
                response = client.post("/folders", headers=headers, json={"name": name})
                assert response.status_code == 200
                roots.append(response.json())
            listed = {row["id"]: row for row in client.get("/folders").json()}
            assert all(listed[row["id"]] == row for row in roots)
            edited = client.patch(f"/folder/{roots[0]['id']}", headers=headers,
                                  json={"name": "Renamed", "tags": ["updated"], "parent_id": roots[1]["id"]})
            assert edited.status_code == 200
            listed = {row["id"]: row for row in client.get("/folders").json()}
            assert listed[roots[0]["id"]] == edited.json()
            assert client.delete(f"/folder/{roots[0]['id']}", headers=headers).status_code == 200
            assert roots[0]["id"] not in {row["id"] for row in client.get("/folders").json()}
        finally:
            for root in roots:
                client.delete(f"/folder/{root['id']}", headers=headers)


def test_folder_listing_still_requires_authentication():
    with TestClient(app) as client:
        assert client.get("/folders").status_code == 401
