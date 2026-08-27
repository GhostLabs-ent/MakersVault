from uuid import uuid4

from fastapi.testclient import TestClient

from db import engine
from main import app


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _remove_machine_rows(machine_ids: list[str]) -> None:
    if not machine_ids:
        return
    placeholders = ", ".join("?" for _ in machine_ids)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"DELETE FROM machineprofile WHERE id IN ({placeholders})",
            tuple(machine_ids),
        )


def test_machine_routes_require_authentication() -> None:
    machine_id = str(uuid4())
    with TestClient(app) as client:
        assert client.get("/machines").status_code == 401
        assert client.post(
            "/machines", json={"name": "Denied", "category": "other"}
        ).status_code == 401
        assert client.get(f"/machine/{machine_id}").status_code == 401
        assert client.post(f"/machine/{machine_id}/archive").status_code == 401
        assert client.post(f"/machine/{machine_id}/restore").status_code == 401
        assert client.post(
            f"/machine/{machine_id}/permanent",
            json={"confirmation": "PERMANENTLY DELETE MACHINE"},
        ).status_code == 401


def test_machine_crud_is_bounded_and_active_names_are_unique() -> None:
    suffix = uuid4().hex[:8]
    machine_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        created = client.post(
            "/machines",
            headers=headers,
            json={
                "name": f"  Workshop Printer {suffix}  ",
                "category": "fdm_printer",
                "manufacturer": "  Bambu Lab  ",
                "model": "P1S",
                "location": "North bench",
                "notes": "Descriptive context only",
            },
        )
        assert created.status_code == 201
        machine = created.json()
        machine_ids.append(machine["id"])
        try:
            assert machine["name"] == f"Workshop Printer {suffix}"
            assert machine["category"] == "fdm_printer"
            assert machine["manufacturer"] == "Bambu Lab"
            assert machine["archived_at"] is None

            fetched = client.get(f"/machine/{machine['id']}", headers=headers)
            assert fetched.status_code == 200
            assert fetched.json() == machine

            listed = client.get(
                f"/machines?q={suffix}&category=fdm_printer&limit=1&offset=0",
                headers=headers,
            )
            assert listed.status_code == 200
            assert [row["id"] for row in listed.json()] == [machine["id"]]
            assert listed.headers["x-has-more"] == "false"

            duplicate = client.post(
                "/machines",
                headers=headers,
                json={
                    "name": f"workshop printer {suffix.upper()}",
                    "category": "other",
                },
            )
            assert duplicate.status_code == 409

            invalid_category = client.post(
                "/machines",
                headers=headers,
                json={"name": f"Invalid {suffix}", "category": "robot"},
            )
            assert invalid_category.status_code == 422
            forbidden_device_field = client.post(
                "/machines",
                headers=headers,
                json={
                    "name": f"Networked {suffix}",
                    "category": "laser",
                    "hostname": "laser.local",
                },
            )
            assert forbidden_device_field.status_code == 422

            updated = client.patch(
                f"/machine/{machine['id']}",
                headers=headers,
                json={"location": "  South bench  ", "notes": None},
            )
            assert updated.status_code == 200
            assert updated.json()["location"] == "South bench"
            assert updated.json()["notes"] is None
            assert updated.json()["updated_at"] >= machine["updated_at"]
            assert client.patch(
                f"/machine/{machine['id']}", headers=headers, json={}
            ).status_code == 422
            assert client.patch(
                f"/machine/{machine['id']}",
                headers=headers,
                json={"ip_address": "10.0.0.50"},
            ).status_code == 422
        finally:
            _remove_machine_rows(machine_ids)


def test_machine_archive_restore_and_permanent_delete_are_profile_only() -> None:
    suffix = uuid4().hex[:8]
    machine_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        original_response = client.post(
            "/machines",
            headers=headers,
            json={"name": f"Shared Name {suffix}", "category": "resin_printer"},
        )
        assert original_response.status_code == 201
        original = original_response.json()
        machine_ids.append(original["id"])
        try:
            archived = client.post(
                f"/machine/{original['id']}/archive", headers=headers
            )
            assert archived.status_code == 200
            assert archived.json()["archived_at"] is not None
            assert all(
                row["id"] != original["id"]
                for row in client.get("/machines", headers=headers).json()
            )
            archived_list = client.get(
                f"/machines?q={suffix}&include_archived=true", headers=headers
            )
            assert [row["id"] for row in archived_list.json()] == [original["id"]]

            replacement_response = client.post(
                "/machines",
                headers=headers,
                json={"name": f"shared name {suffix}", "category": "other"},
            )
            assert replacement_response.status_code == 201
            replacement = replacement_response.json()
            machine_ids.append(replacement["id"])

            conflict = client.post(
                f"/machine/{original['id']}/restore", headers=headers
            )
            assert conflict.status_code == 409
            assert conflict.json()["detail"]["code"] == "machine_name_conflict"

            active_permanent = client.post(
                f"/machine/{replacement['id']}/permanent",
                headers=headers,
                json={"confirmation": "PERMANENTLY DELETE MACHINE"},
            )
            assert active_permanent.status_code == 404
            assert client.post(
                f"/machine/{replacement['id']}/archive", headers=headers
            ).status_code == 200
            wrong_confirmation = client.post(
                f"/machine/{replacement['id']}/permanent",
                headers=headers,
                json={"confirmation": "delete"},
            )
            assert wrong_confirmation.status_code == 400
            removed = client.post(
                f"/machine/{replacement['id']}/permanent",
                headers=headers,
                json={"confirmation": "PERMANENTLY DELETE MACHINE"},
            )
            assert removed.status_code == 200
            assert removed.json() == {
                "machine_id": replacement["id"],
                "name": replacement["name"],
                "associations_deleted": 0,
                "prepared_references_cleared": 0,
            }
            machine_ids.remove(replacement["id"])
            assert client.get(
                f"/machine/{replacement['id']}", headers=headers
            ).status_code == 404

            restored = client.post(
                f"/machine/{original['id']}/restore", headers=headers
            )
            assert restored.status_code == 200
            assert restored.json()["archived_at"] is None
        finally:
            _remove_machine_rows(machine_ids)
