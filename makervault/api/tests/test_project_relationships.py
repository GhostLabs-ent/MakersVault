from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from db import engine
from main import app
from models import Asset, Project, ProjectMembership, ProjectRelationship


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _project(client: TestClient, headers: dict[str, str], name: str) -> dict:
    response = client.post("/projects", headers=headers, json={"name": name})
    assert response.status_code == 201
    return response.json()


def _asset(client: TestClient, headers: dict[str, str], filename: str) -> dict:
    response = client.post(
        "/upload",
        headers=headers,
        files={"file": (filename, b"cube([21, 22, 23]);\n", "text/plain")},
    )
    assert response.status_code == 200
    return response.json()


def _join(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    asset_id: str,
) -> None:
    response = client.post(
        f"/project/{project_id}/items/{asset_id}", headers=headers
    )
    assert response.status_code == 201


def _relationship(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    source_id: str,
    target_id: str,
    kind: str,
):
    return client.post(
        f"/project/{project_id}/relationships",
        headers=headers,
        json={
            "source_asset_id": source_id,
            "target_asset_id": target_id,
            "kind": kind,
        },
    )


def _remove_projects(project_ids: list[str]) -> None:
    with Session(engine) as session:
        for relationship in session.exec(
            select(ProjectRelationship).where(
                ProjectRelationship.project_id.in_(project_ids)
            )
        ):
            session.delete(relationship)
        for membership in session.exec(
            select(ProjectMembership).where(
                ProjectMembership.project_id.in_(project_ids)
            )
        ):
            session.delete(membership)
        for project_id in project_ids:
            project = session.get(Project, project_id)
            if project:
                session.delete(project)
        session.commit()


def _purge_assets(
    client: TestClient,
    headers: dict[str, str],
    asset_ids: list[str],
) -> None:
    for asset_id in asset_ids:
        with Session(engine) as session:
            asset = session.get(Asset, asset_id)
            if not asset:
                continue
            already_trashed = bool(asset.deleted_at)
        if not already_trashed:
            client.delete(f"/asset/{asset_id}", headers=headers)
        client.post(
            "/trash/permanent",
            headers=headers,
            json={
                "asset_ids": [asset_id],
                "confirmation": "PERMANENTLY DELETE",
            },
        )


def test_relationship_routes_require_authentication() -> None:
    project_id = str(uuid4())
    relationship_id = str(uuid4())
    assert TestClient(app).get(
        f"/project/{project_id}/relationships"
    ).status_code == 401
    assert TestClient(app).post(
        f"/project/{project_id}/relationships",
        json={
            "source_asset_id": str(uuid4()),
            "target_asset_id": str(uuid4()),
            "kind": "derived_from",
        },
    ).status_code == 401
    assert TestClient(app).delete(
        f"/project/{project_id}/relationships/{relationship_id}"
    ).status_code == 401


def test_relationship_kinds_membership_duplicates_and_bounded_labels() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    asset_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        first = _project(client, headers, f"Relationship Rules {suffix}")
        second = _project(client, headers, f"Other Relationship Rules {suffix}")
        project_ids.extend([first["id"], second["id"]])
        assets = [_asset(client, headers, f"relation-{suffix}-{i}.scad") for i in range(4)]
        asset_ids.extend(asset["id"] for asset in assets)
        for asset in assets[:3]:
            _join(client, headers, first["id"], asset["id"])
        _join(client, headers, second["id"], assets[3]["id"])
        try:
            created = _relationship(
                client,
                headers,
                first["id"],
                assets[0]["id"],
                assets[1]["id"],
                "derived_from",
            )
            assert created.status_code == 201
            body = created.json()
            assert body["source_name"] == assets[0]["name"]
            assert body["target_name"] == assets[1]["name"]
            assert body["forward_label"] == "Derived from"
            assert body["inverse_label"] == "Source of"

            duplicate = _relationship(
                client, headers, first["id"], assets[0]["id"], assets[1]["id"], "derived_from"
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["detail"]["code"] == "relationship_duplicate"

            self_link = _relationship(
                client, headers, first["id"], assets[0]["id"], assets[0]["id"], "component_of"
            )
            assert self_link.status_code == 422
            assert self_link.json()["detail"]["code"] == "relationship_self_link"

            invalid_kind = _relationship(
                client, headers, first["id"], assets[0]["id"], assets[1]["id"], "source_of"
            )
            assert invalid_kind.status_code == 422

            cross_project = _relationship(
                client, headers, first["id"], assets[0]["id"], assets[3]["id"], "documentation_for"
            )
            assert cross_project.status_code == 409
            assert cross_project.json()["detail"]["code"] == "endpoint_not_project_member"

            second_relation = _relationship(
                client,
                headers,
                first["id"],
                assets[2]["id"],
                assets[1]["id"],
                "component_of",
            )
            assert second_relation.status_code == 201
            page = client.get(
                f"/project/{first['id']}/relationships?limit=1&offset=0",
                headers=headers,
            )
            assert page.status_code == 200
            assert len(page.json()) == 1
            assert page.headers["x-has-more"] == "true"
            assert page.headers["x-next-offset"] == "1"
            final_page = client.get(
                f"/project/{first['id']}/relationships?limit=1&offset=1",
                headers=headers,
            )
            assert final_page.headers["x-has-more"] == "false"

            deleted = client.delete(
                f"/project/{first['id']}/relationships/{second_relation.json()['id']}",
                headers=headers,
            )
            assert deleted.status_code == 200
            remaining = client.get(
                f"/project/{first['id']}/relationships", headers=headers
            )
            assert remaining.status_code == 200
            assert [relationship["id"] for relationship in remaining.json()] == [
                body["id"]
            ]
            for asset in assets[:3]:
                downloaded = client.get(asset["url"], headers=headers)
                assert downloaded.status_code == 200
                assert downloaded.content == b"cube([21, 22, 23]);\n"
        finally:
            _purge_assets(client, headers, asset_ids)
            _remove_projects(project_ids)


def test_relationship_cycle_rules_are_scoped_by_project_and_kind() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    asset_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Cycle Rules {suffix}")
        project_ids.append(project["id"])
        assets = [_asset(client, headers, f"cycle-{suffix}-{i}.scad") for i in range(3)]
        asset_ids.extend(asset["id"] for asset in assets)
        for asset in assets:
            _join(client, headers, project["id"], asset["id"])
        try:
            for kind in ("derived_from", "component_of"):
                assert _relationship(
                    client, headers, project["id"], assets[0]["id"], assets[1]["id"], kind
                ).status_code == 201
                assert _relationship(
                    client, headers, project["id"], assets[1]["id"], assets[2]["id"], kind
                ).status_code == 201
                cycle = _relationship(
                    client, headers, project["id"], assets[2]["id"], assets[0]["id"], kind
                )
                assert cycle.status_code == 409
                assert cycle.json()["detail"]["code"] == "relationship_cycle"

            assert _relationship(
                client,
                headers,
                project["id"],
                assets[0]["id"],
                assets[1]["id"],
                "documentation_for",
            ).status_code == 201
            assert _relationship(
                client,
                headers,
                project["id"],
                assets[1]["id"],
                assets[0]["id"],
                "documentation_for",
            ).status_code == 201
        finally:
            _purge_assets(client, headers, asset_ids)
            _remove_projects(project_ids)


def test_membership_removal_requires_relationship_cleanup_confirmation() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    asset_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Membership Cleanup {suffix}")
        project_ids.append(project["id"])
        assets = [_asset(client, headers, f"member-cleanup-{suffix}-{i}.scad") for i in range(2)]
        asset_ids.extend(asset["id"] for asset in assets)
        for asset in assets:
            _join(client, headers, project["id"], asset["id"])
        before = client.get(f"/assets?q=member-cleanup-{suffix}", headers=headers).json()
        try:
            assert _relationship(
                client,
                headers,
                project["id"],
                assets[0]["id"],
                assets[1]["id"],
                "component_of",
            ).status_code == 201
            refused = client.delete(
                f"/project/{project['id']}/items/{assets[0]['id']}", headers=headers
            )
            assert refused.status_code == 409
            assert refused.json()["detail"] == {
                "code": "relationship_cleanup_confirmation_required",
                "relationship_count": 1,
                "message": "Removing this Project item will also remove 1 relationship",
            }
            assert len(client.get(
                f"/project/{project['id']}/relationships", headers=headers
            ).json()) == 1

            confirmed = client.delete(
                f"/project/{project['id']}/items/{assets[0]['id']}?confirm_relationship_cleanup=true",
                headers=headers,
            )
            assert confirmed.status_code == 200
            assert client.get(
                f"/project/{project['id']}/relationships", headers=headers
            ).json() == []
            assert [row["id"] for row in client.get(
                f"/project/{project['id']}/items", headers=headers
            ).json()] == [assets[1]["id"]]
            after = client.get(f"/assets?q=member-cleanup-{suffix}", headers=headers).json()
            assert [(row["id"], row["folder_id"], row["storage_path"], row["current_revision_id"]) for row in after] == [
                (row["id"], row["folder_id"], row["storage_path"], row["current_revision_id"])
                for row in before
            ]
            for asset in assets:
                assert client.get(asset["url"], headers=headers).content == b"cube([21, 22, 23]);\n"
        finally:
            _purge_assets(client, headers, asset_ids)
            _remove_projects(project_ids)


def test_relationship_trash_restore_project_retention_and_artifact_purge() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    asset_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Relationship Lifecycle {suffix}")
        project_ids.append(project["id"])
        assets = [_asset(client, headers, f"relationship-life-{suffix}-{i}.scad") for i in range(2)]
        asset_ids.extend(asset["id"] for asset in assets)
        for asset in assets:
            _join(client, headers, project["id"], asset["id"])
        try:
            created = _relationship(
                client,
                headers,
                project["id"],
                assets[0]["id"],
                assets[1]["id"],
                "documentation_for",
            ).json()
            assert client.delete(f"/asset/{assets[0]['id']}", headers=headers).status_code == 200
            assert client.get(
                f"/project/{project['id']}/relationships", headers=headers
            ).json() == []
            with Session(engine) as session:
                assert session.get(ProjectRelationship, created["id"]) is not None

            assert client.post(
                f"/trash/{assets[0]['id']}/restore", headers=headers, json={}
            ).status_code == 200
            assert [row["id"] for row in client.get(
                f"/project/{project['id']}/relationships", headers=headers
            ).json()] == [created["id"]]

            assert client.delete(f"/project/{project['id']}", headers=headers).status_code == 200
            with Session(engine) as session:
                assert session.get(ProjectRelationship, created["id"]) is not None

            assert client.delete(f"/asset/{assets[0]['id']}", headers=headers).status_code == 200
            purged = client.post(
                "/trash/permanent",
                headers=headers,
                json={
                    "asset_ids": [assets[0]["id"]],
                    "confirmation": "PERMANENTLY DELETE",
                },
            )
            assert purged.status_code == 200
            asset_ids.remove(assets[0]["id"])
            with Session(engine) as session:
                assert session.get(ProjectRelationship, created["id"]) is None
                assert session.get(
                    ProjectMembership, (project["id"], assets[0]["id"])
                ) is None
                assert session.get(Asset, assets[1]["id"]) is not None
        finally:
            _purge_assets(client, headers, asset_ids)
            _remove_projects(project_ids)
