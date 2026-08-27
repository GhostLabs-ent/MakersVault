from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from db import STORAGE, engine
from main import app
from models import ArtifactRevision, Asset


NOTICE = "Descriptive context only. No job was sent."
MACHINE_CONFIRMATION = "PERMANENTLY DELETE MACHINE"


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _upload(
    client: TestClient,
    headers: dict[str, str],
    filename: str,
    content: bytes = b"solid machine context",
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
        json={"name": name, "category": category},
    )
    assert response.status_code == 201
    return response.json()


def _purge_asset(client: TestClient, headers: dict[str, str], asset_id: str) -> None:
    client.delete(f"/asset/{asset_id}", headers=headers)
    client.post(
        "/trash/permanent",
        headers=headers,
        json={
            "asset_ids": [asset_id],
            "confirmation": "PERMANENTLY DELETE",
        },
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


def test_machine_context_routes_require_authentication() -> None:
    asset_id = str(uuid4())
    machine_id = str(uuid4())
    with TestClient(app) as client:
        assert client.get(f"/asset/{asset_id}/machines").status_code == 401
        assert client.post(
            f"/asset/{asset_id}/machines/{machine_id}"
        ).status_code == 401
        assert client.delete(
            f"/asset/{asset_id}/machines/{machine_id}"
        ).status_code == 401
        assert client.put(
            f"/asset/{asset_id}/prepared-machine",
            json={"machine_id": machine_id},
        ).status_code == 401


def test_explicit_associations_are_neutral_deterministic_and_trash_safe() -> None:
    suffix = uuid4().hex[:8]
    asset_id = ""
    machine_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, f"association-{suffix}.stl")
        asset_id = asset["id"]
        laser = _machine(client, headers, f"Laser {suffix}", "laser")
        printer = _machine(client, headers, f"Printer {suffix}", "fdm_printer")
        machine_ids.extend([laser["id"], printer["id"]])
        try:
            with Session(engine) as session:
                original_row = session.get(Asset, asset_id)
                projection_before = (
                    original_row.storage_path,
                    original_row.current_revision_id,
                    original_row.prepared_metadata_json,
                )
            empty = client.get(f"/asset/{asset_id}/machines", headers=headers)
            assert empty.status_code == 200
            assert empty.json() == {
                "asset_id": asset_id,
                "associations": [],
                "prepared_machine": None,
                "prepared_revision_id": None,
                "notice": NOTICE,
            }

            first = client.post(
                f"/asset/{asset_id}/machines/{printer['id']}", headers=headers
            )
            assert first.status_code == 201
            second = client.post(
                f"/asset/{asset_id}/machines/{laser['id']}", headers=headers
            )
            assert second.status_code == 201
            assert [
                row["machine"]["name"] for row in second.json()["associations"]
            ] == [laser["name"], printer["name"]]
            assert second.json()["notice"] == NOTICE
            with Session(engine) as session:
                linked_row = session.get(Asset, asset_id)
                assert (
                    linked_row.storage_path,
                    linked_row.current_revision_id,
                    linked_row.prepared_metadata_json,
                ) == projection_before
            assert client.get(asset["url"], headers=headers).content == (
                b"solid machine context"
            )
            assert client.post(
                f"/asset/{asset_id}/machines/{printer['id']}", headers=headers
            ).status_code == 409

            archived = client.post(
                f"/machine/{laser['id']}/archive", headers=headers
            )
            assert archived.status_code == 200
            removed = client.delete(
                f"/asset/{asset_id}/machines/{laser['id']}", headers=headers
            )
            assert removed.status_code == 200
            assert client.post(
                f"/asset/{asset_id}/machines/{laser['id']}", headers=headers
            ).status_code == 404

            assert client.delete(f"/asset/{asset_id}", headers=headers).status_code == 200
            with engine.connect() as conn:
                assert conn.exec_driver_sql(
                    "SELECT machine_id FROM artifactmachine WHERE asset_id = ?",
                    (asset_id,),
                ).fetchall() == [(printer["id"],)]
            restored = client.post(
                f"/trash/{asset_id}/restore",
                headers=headers,
                json={"restore_unassigned": False},
            )
            assert restored.status_code == 200
            context = client.get(f"/asset/{asset_id}/machines", headers=headers).json()
            assert [row["machine"]["id"] for row in context["associations"]] == [
                printer["id"]
            ]

            assert client.delete(f"/asset/{asset_id}", headers=headers).status_code == 200
            purged = client.post(
                "/trash/permanent",
                headers=headers,
                json={
                    "asset_ids": [asset_id],
                    "confirmation": "PERMANENTLY DELETE",
                },
            )
            assert purged.status_code == 200
            with engine.connect() as conn:
                assert conn.exec_driver_sql(
                    "SELECT COUNT(*) FROM artifactmachine WHERE asset_id = ?",
                    (asset_id,),
                ).scalar_one() == 0
            asset_id = ""
        finally:
            if asset_id:
                _purge_asset(client, headers, asset_id)
            for machine_id in machine_ids:
                _remove_machine(client, headers, machine_id)


def test_prepared_target_is_exact_revisioned_and_machine_delete_clears_only_links() -> None:
    suffix = uuid4().hex[:8]
    asset_id = ""
    machine_ids: list[str] = []
    original = b"solid exact target"
    replacement = b"solid unprepared replacement"
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, f"exact-{suffix}.stl", original)
        asset_id = asset["id"]
        printer = _machine(client, headers, f"FDM {suffix}", "fdm_printer")
        laser = _machine(client, headers, f"Laser exact {suffix}", "laser")
        machine_ids.extend([printer["id"], laser["id"]])
        gcode = (
            f"; printer_model = {printer['name']}\n;TIME:192\nG28\n".encode()
        )
        try:
            attached = client.post(
                f"/asset/{asset_id}/files",
                headers=headers,
                files={"file": ("exact.gcode", gcode, "text/plain")},
            )
            assert attached.status_code == 200
            assert attached.json()["prepared_machine_id"] is None
            assert attached.json()["prepared_print"]["printer"] == printer["name"]
            revision_one = client.get(
                f"/asset/{asset_id}/revisions", headers=headers
            ).json()[0]
            assert revision_one["prepared_machine_id"] is None

            rejected = client.put(
                f"/asset/{asset_id}/prepared-machine",
                headers=headers,
                json={"machine_id": laser["id"]},
            )
            assert rejected.status_code == 422

            linked = client.post(
                f"/asset/{asset_id}/machines/{printer['id']}", headers=headers
            )
            assert linked.status_code == 201
            assert client.post(
                f"/machine/{printer['id']}/archive", headers=headers
            ).status_code == 200
            assert client.put(
                f"/asset/{asset_id}/prepared-machine",
                headers=headers,
                json={"machine_id": printer["id"]},
            ).status_code == 404
            assert client.post(
                f"/machine/{printer['id']}/restore", headers=headers
            ).status_code == 200
            targeted = client.put(
                f"/asset/{asset_id}/prepared-machine",
                headers=headers,
                json={"machine_id": printer["id"]},
            )
            assert targeted.status_code == 200
            assert targeted.json()["prepared_machine"]["id"] == printer["id"]
            assert targeted.json()["prepared_revision_id"] == revision_one["id"]
            cleared = client.put(
                f"/asset/{asset_id}/prepared-machine",
                headers=headers,
                json={"machine_id": None},
            )
            assert cleared.status_code == 200
            assert cleared.json()["prepared_machine"] is None
            targeted = client.put(
                f"/asset/{asset_id}/prepared-machine",
                headers=headers,
                json={"machine_id": printer["id"]},
            )
            assert targeted.status_code == 200

            with Session(engine) as session:
                asset_row = session.get(Asset, asset_id)
                revision_row = session.get(ArtifactRevision, revision_one["id"])
                prepared_metadata = asset_row.prepared_metadata_json
                primary_path = (STORAGE / asset_row.storage_path).resolve()
                assert asset_row.prepared_machine_id == printer["id"]
                assert revision_row.prepared_machine_id == printer["id"]
            assert primary_path.read_bytes() == original
            assert client.get(
                f"/asset/{asset_id}/prepared-print", headers=headers
            ).content == gcode

            replaced = client.post(
                f"/asset/{asset_id}/revisions",
                headers=headers,
                files={"file": ("replacement.stl", replacement, "model/stl")},
            )
            assert replaced.status_code == 200
            assert replaced.json()["asset"]["prepared_machine_id"] is None
            assert replaced.json()["revision"]["prepared_machine_id"] is None
            revision_two = replaced.json()["revision"]

            restored = client.post(
                f"/asset/{asset_id}/revisions/{revision_one['id']}/restore",
                headers=headers,
                json={},
            )
            assert restored.status_code == 200
            assert restored.json()["asset"]["prepared_machine_id"] == printer["id"]
            assert restored.json()["revision"]["prepared_machine_id"] == printer["id"]
            revision_three = restored.json()["revision"]

            assert client.delete(f"/asset/{asset_id}", headers=headers).status_code == 200
            with Session(engine) as session:
                trashed = session.get(Asset, asset_id)
                assert trashed.prepared_machine_id == printer["id"]
                assert session.get(
                    ArtifactRevision, revision_one["id"]
                ).prepared_machine_id == printer["id"]
            assert client.post(
                f"/trash/{asset_id}/restore",
                headers=headers,
                json={"restore_unassigned": False},
            ).status_code == 200

            assert client.post(
                f"/machine/{printer['id']}/archive", headers=headers
            ).status_code == 200
            archived_context = client.get(
                f"/asset/{asset_id}/machines", headers=headers
            ).json()
            assert archived_context["prepared_machine"]["archived_at"] is not None
            removed = client.post(
                f"/machine/{printer['id']}/permanent",
                headers=headers,
                json={"confirmation": MACHINE_CONFIRMATION},
            )
            assert removed.status_code == 200
            assert removed.json()["associations_deleted"] == 1
            assert removed.json()["prepared_references_cleared"] == 3
            machine_ids.remove(printer["id"])

            with Session(engine) as session:
                final_asset = session.get(Asset, asset_id)
                revisions = list(session.exec(
                    select(ArtifactRevision).where(ArtifactRevision.asset_id == asset_id)
                ))
                assert final_asset.prepared_machine_id is None
                assert all(row.prepared_machine_id is None for row in revisions)
                assert final_asset.prepared_metadata_json == prepared_metadata
                assert {row.id for row in revisions} == {
                    revision_one["id"], revision_two["id"], revision_three["id"]
                }
            assert client.get(
                f"/asset/{asset_id}/prepared-print", headers=headers
            ).content == gcode
            assert client.get(
                restored.json()["asset"]["url"], headers=headers
            ).content == original
        finally:
            if asset_id:
                _purge_asset(client, headers, asset_id)
            for machine_id in machine_ids:
                _remove_machine(client, headers, machine_id)


def test_replacing_or_removing_prepared_payload_clears_exact_target() -> None:
    suffix = uuid4().hex[:8]
    asset_id = ""
    machine_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        asset = _upload(client, headers, f"prepared-replace-{suffix}.stl")
        asset_id = asset["id"]
        printer = _machine(client, headers, f"Resin {suffix}", "resin_printer")
        machine_ids.append(printer["id"])
        try:
            first = client.post(
                f"/asset/{asset_id}/files",
                headers=headers,
                files={"file": ("first.gcode", b"G28\n", "text/plain")},
            )
            assert first.status_code == 200
            assert client.put(
                f"/asset/{asset_id}/prepared-machine",
                headers=headers,
                json={"machine_id": printer["id"]},
            ).status_code == 200

            replaced = client.post(
                f"/asset/{asset_id}/files",
                headers=headers,
                files={"file": ("second.gcode", b"G29\n", "text/plain")},
            )
            assert replaced.status_code == 200
            assert replaced.json()["prepared_machine_id"] is None
            current = client.get(
                f"/asset/{asset_id}/revisions", headers=headers
            ).json()[0]
            assert current["prepared_machine_id"] is None

            assert client.put(
                f"/asset/{asset_id}/prepared-machine",
                headers=headers,
                json={"machine_id": printer["id"]},
            ).status_code == 200
            removed = client.delete(
                f"/asset/{asset_id}/prepared-print", headers=headers
            )
            assert removed.status_code == 200
            assert removed.json()["prepared_machine_id"] is None
        finally:
            if asset_id:
                _purge_asset(client, headers, asset_id)
            for machine_id in machine_ids:
                _remove_machine(client, headers, machine_id)
