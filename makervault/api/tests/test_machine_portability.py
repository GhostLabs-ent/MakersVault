from io import BytesIO
import json
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlmodel import Session

from db import engine
from main import app
from models import Asset, MachineProfile, Project


MACHINE_CONFIRMATION = "PERMANENTLY DELETE MACHINE"


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert response.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


def _asset(
    client: TestClient,
    headers: dict[str, str],
    filename: str,
    content: bytes = b"solid portable machine context",
) -> dict:
    response = client.post(
        "/upload",
        headers=headers,
        files={"file": (filename, content, "model/stl")},
    )
    assert response.status_code == 200
    return response.json()


def _machine(
    client: TestClient,
    headers: dict[str, str],
    name: str,
    category: str,
) -> dict:
    response = client.post(
        "/machines",
        headers=headers,
        json={
            "name": name,
            "category": category,
            "manufacturer": "MakersVault Tests",
            "model": "Portable Context",
            "location": "Test bench",
            "notes": "Descriptive only",
        },
    )
    assert response.status_code == 201
    return response.json()


def _associate(
    client: TestClient,
    headers: dict[str, str],
    asset_id: str,
    machine_id: str,
) -> dict:
    response = client.post(
        f"/asset/{asset_id}/machines/{machine_id}", headers=headers
    )
    assert response.status_code == 201
    return response.json()


def _purge_asset(client: TestClient, headers: dict[str, str], asset_id: str) -> None:
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if not asset:
            return
        trashed = bool(asset.deleted_at)
    if not trashed:
        client.delete(f"/asset/{asset_id}", headers=headers)
    client.post(
        "/trash/permanent",
        headers=headers,
        json={"asset_ids": [asset_id], "confirmation": "PERMANENTLY DELETE"},
    )


def _remove_machine(client: TestClient, headers: dict[str, str], machine_id: str) -> None:
    response = client.get(f"/machine/{machine_id}", headers=headers)
    if response.status_code != 200:
        return
    if response.json()["archived_at"] is None:
        client.post(f"/machine/{machine_id}/archive", headers=headers)
    client.post(
        f"/machine/{machine_id}/permanent",
        headers=headers,
        json={"confirmation": MACHINE_CONFIRMATION},
    )


def _remove_project(project_id: str) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "DELETE FROM projectrelationship WHERE project_id = ?", (project_id,)
        )
        conn.exec_driver_sql(
            "DELETE FROM projectmembership WHERE project_id = ?", (project_id,)
        )
        conn.exec_driver_sql("DELETE FROM project WHERE id = ?", (project_id,))


def _manifest(response) -> tuple[dict, dict[str, bytes]]:
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        return (
            json.loads(archive.read("manifest.json")),
            {name: archive.read(name) for name in archive.namelist()},
        )


def test_artifact_history_format2_preserves_machine_snapshots_and_exact_history() -> None:
    suffix = uuid4().hex[:8]
    asset_id = ""
    machine_ids: list[str] = []
    original = b"solid portable revision one"
    replacement = b"solid portable revision two"
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _asset(client, headers, f"portable-{suffix}.stl", original)
        asset_id = asset["id"]
        printer = _machine(client, headers, f"Printer {suffix}", "fdm_printer")
        laser = _machine(client, headers, f"Laser {suffix}", "laser")
        machine_ids.extend([printer["id"], laser["id"]])
        try:
            printer_context = _associate(
                client, headers, asset_id, printer["id"]
            )
            laser_context = _associate(client, headers, asset_id, laser["id"])
            association_times = {
                row["machine"]["id"]: row["created_at"]
                for row in laser_context["associations"]
            }
            gcode = f"; printer_model = {printer['name']}\nG28\n".encode()
            assert client.post(
                f"/asset/{asset_id}/files",
                headers=headers,
                files={"file": ("portable.gcode", gcode, "text/plain")},
            ).status_code == 200
            assert client.put(
                f"/asset/{asset_id}/prepared-machine",
                headers=headers,
                json={"machine_id": printer["id"]},
            ).status_code == 200
            revision_one = client.get(
                f"/asset/{asset_id}/revisions", headers=headers
            ).json()[0]
            replaced = client.post(
                f"/asset/{asset_id}/revisions",
                headers=headers,
                files={"file": ("replacement.stl", replacement, "model/stl")},
            )
            assert replaced.status_code == 200
            revision_two = replaced.json()["revision"]
            assert client.post(
                f"/machine/{laser['id']}/archive", headers=headers
            ).status_code == 200

            missing_id = f"missing-{suffix}"
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    "INSERT INTO artifactmachine(asset_id, machine_id, created_at) "
                    "VALUES (?, ?, 'corrupt-fixture')",
                    (asset_id, missing_id),
                )

            manifest, entries = _manifest(client.get(
                f"/asset/{asset_id}/revisions/export", headers=headers
            ))
            assert manifest["format"] == "makersvault-artifact-history"
            assert manifest["version"] == 2
            assert manifest["artifact"]["prepared_machine_id"] is None
            assert manifest["machine_associations"] == [
                {
                    "machine_id": machine_id,
                    "created_at": (
                        "corrupt-fixture"
                        if machine_id == missing_id
                        else association_times[machine_id]
                    ),
                }
                for machine_id in sorted([printer["id"], laser["id"], missing_id])
            ]
            assert manifest["unresolved_machine_ids"] == [missing_id]
            assert [row["id"] for row in manifest["machines"]] == sorted(
                [printer["id"], laser["id"]]
            )
            snapshots = {row["id"]: row for row in manifest["machines"]}
            assert snapshots[printer["id"]] == printer
            assert snapshots[laser["id"]]["archived_at"] is not None
            revisions = {row["id"]: row for row in manifest["revisions"]}
            assert revisions[revision_one["id"]]["prepared_machine_id"] == printer["id"]
            assert revisions[revision_one["id"]]["prepared_metadata"]["printer"] == (
                printer["name"]
            )
            assert revisions[revision_two["id"]]["prepared_machine_id"] is None
            assert entries[f"revisions/1/{asset['filename']}"] == original
            assert entries[f"revisions/2/{replaced.json()['asset']['filename']}"] == replacement
            assert any(name.startswith("revisions/1/prepared/") for name in entries)
            assert printer_context["notice"] == (
                "Descriptive context only. No job was sent."
            )
        finally:
            if asset_id:
                _purge_asset(client, headers, asset_id)
            for machine_id in machine_ids:
                _remove_machine(client, headers, machine_id)


def test_project_format2_deduplicates_machines_and_keeps_trashed_context() -> None:
    suffix = uuid4().hex[:8]
    asset_ids: list[str] = []
    machine_ids: list[str] = []
    project_id = ""
    with TestClient(app) as client:
        headers = _headers(client)
        project_response = client.post(
            "/projects",
            headers=headers,
            json={"name": f"Portable Project {suffix}"},
        )
        assert project_response.status_code == 201
        project = project_response.json()
        project_id = project["id"]
        first = _asset(client, headers, f"first-{suffix}.stl")
        second = _asset(client, headers, f"second-{suffix}.stl")
        asset_ids.extend([first["id"], second["id"]])
        shared = _machine(client, headers, f"Shared {suffix}", "cnc")
        extra = _machine(client, headers, f"Extra {suffix}", "other")
        machine_ids.extend([shared["id"], extra["id"]])
        try:
            for asset_id in asset_ids:
                assert client.post(
                    f"/project/{project_id}/items/{asset_id}", headers=headers
                ).status_code == 201
                _associate(client, headers, asset_id, shared["id"])
            _associate(client, headers, second["id"], extra["id"])
            assert client.post(
                f"/machine/{shared['id']}/archive", headers=headers
            ).status_code == 200
            assert client.delete(
                f"/asset/{second['id']}", headers=headers
            ).status_code == 200

            first_manifest, first_entries = _manifest(client.get(
                f"/project/{project_id}/export", headers=headers
            ))
            second_manifest, second_entries = _manifest(client.get(
                f"/project/{project_id}/export", headers=headers
            ))
            assert first_manifest == second_manifest
            assert first_manifest["version"] == 2
            assert [row["id"] for row in first_manifest["machines"]] == sorted(
                machine_ids
            )
            assert len(first_manifest["machines"]) == 2
            artifacts = {row["id"]: row for row in first_manifest["artifacts"]}
            assert artifacts[first["id"]]["machine_ids"] == [shared["id"]]
            assert artifacts[second["id"]]["machine_ids"] == sorted(machine_ids)
            assert artifacts[second["id"]]["state"] == "trashed"
            for asset_id in asset_ids:
                nested = json.loads(first_entries[f"artifacts/{asset_id}/manifest.json"])
                assert nested["version"] == 2
            assert set(first_entries) == set(second_entries)
        finally:
            if project_id:
                _remove_project(project_id)
            for asset_id in asset_ids:
                _purge_asset(client, headers, asset_id)
            for machine_id in machine_ids:
                _remove_machine(client, headers, machine_id)


def test_machine_retrieval_scopes_compose_without_duplicates_or_text_inference() -> None:
    suffix = uuid4().hex[:8]
    asset_ids: list[str] = []
    machine_ids: list[str] = []
    project_id = ""
    folder_id = ""
    with TestClient(app) as client:
        headers = _headers(client)
        printer = _machine(client, headers, f"Retrieve Printer {suffix}", "fdm_printer")
        laser = _machine(client, headers, f"Retrieve Laser {suffix}", "laser")
        machine_ids.extend([printer["id"], laser["id"]])
        associated = _asset(client, headers, f"associated-{suffix}.stl")
        prepared = _asset(client, headers, f"prepared-{suffix}.stl")
        supplied_text_only = _asset(client, headers, f"text-{suffix}.stl")
        asset_ids.extend([associated["id"], prepared["id"], supplied_text_only["id"]])
        project_response = client.post(
            "/projects", headers=headers, json={"name": f"Retrieve {suffix}"}
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]
        folder_response = client.post(
            "/folders",
            headers=headers,
            json={"name": f"Machine filter {suffix}", "tags": []},
        )
        assert folder_response.status_code == 200
        folder_id = folder_response.json()["id"]
        try:
            for asset in (associated, prepared):
                assert client.post(
                    f"/project/{project_id}/items/{asset['id']}", headers=headers
                ).status_code == 201
            _associate(client, headers, associated["id"], laser["id"])
            _associate(client, headers, associated["id"], printer["id"])
            assert client.post(
                f"/asset/{associated['id']}/folder",
                headers=headers,
                json={"folder_id": folder_id},
            ).status_code == 200
            for asset, tag in (
                (associated, "association-tag"),
                (prepared, "prepared-tag"),
                (supplied_text_only, "text-only-tag"),
            ):
                assert client.post(
                    f"/asset/{asset['id']}/tags",
                    headers=headers,
                    json={"tags": [tag]},
                ).status_code == 200
            gcode = f"; printer_model = {printer['name']}\nG28\n".encode()
            for asset in (prepared, supplied_text_only):
                assert client.post(
                    f"/asset/{asset['id']}/files",
                    headers=headers,
                    files={"file": ("retrieve.gcode", gcode, "text/plain")},
                ).status_code == 200
            assert client.put(
                f"/asset/{prepared['id']}/prepared-machine",
                headers=headers,
                json={"machine_id": printer["id"]},
            ).status_code == 200

            def ids(path: str) -> list[str]:
                response = client.get(path, headers=headers)
                assert response.status_code == 200
                return [row["id"] for row in response.json()]

            assert ids(
                f"/assets?machine_id={printer['id']}&machine_scope=associated"
            ) == [associated["id"]]
            assert ids(
                f"/assets?machine_id={printer['id']}&machine_scope=prepared"
            ) == [prepared["id"]]
            assert ids(f"/assets?machine_id={printer['id']}") == sorted(
                [associated["id"], prepared["id"]],
                key=lambda asset_id: next(
                    row["name"] for row in (associated, prepared) if row["id"] == asset_id
                ),
            )
            assert supplied_text_only["id"] not in ids(
                f"/assets?machine_id={printer['id']}"
            )
            project_ids = ids(
                f"/project/{project_id}/items?machine_id={printer['id']}&machine_scope=any"
            )
            assert set(project_ids) == {associated["id"], prepared["id"]}
            composed = ids(
                f"/assets?machine_id={printer['id']}"
                f"&machine_scope=associated&folder_id={folder_id}"
                "&q=associated&tags=association-tag"
            )
            assert composed == [associated["id"]]
            paged = client.get(
                f"/assets?machine_id={printer['id']}&limit=1&offset=0",
                headers=headers,
            )
            assert paged.status_code == 200
            assert len(paged.json()) == 1
            assert paged.headers["x-has-more"] == "true"
            tags = client.get(
                f"/tags?machine_id={printer['id']}&machine_scope=prepared",
                headers=headers,
            )
            assert tags.status_code == 200
            assert tags.json() == ["prepared-tag"]

            assert client.get(
                "/assets?machine_scope=associated", headers=headers
            ).status_code == 422
            assert client.get(
                f"/assets?machine_id={printer['id']}&machine_scope=historical",
                headers=headers,
            ).status_code == 422
            assert client.get(
                f"/assets?machine_id=missing-{suffix}", headers=headers
            ).status_code == 404
            assert client.post(
                f"/machine/{laser['id']}/archive", headers=headers
            ).status_code == 200
            assert ids(f"/assets?machine_id={laser['id']}") == [associated["id"]]
        finally:
            if project_id:
                _remove_project(project_id)
            for asset_id in asset_ids:
                _purge_asset(client, headers, asset_id)
            for machine_id in machine_ids:
                _remove_machine(client, headers, machine_id)
            if folder_id:
                client.delete(f"/folder/{folder_id}", headers=headers)
