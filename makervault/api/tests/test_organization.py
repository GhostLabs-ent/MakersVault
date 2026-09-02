from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from main import app


def _headers(client: TestClient) -> dict[str, str]:
    login = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert login.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}


def _folder(client: TestClient, headers: dict[str, str], name: str, parent_id: str | None = None) -> dict:
    response = client.post(
        "/folders",
        headers=headers,
        json={"name": name, "tags": [], "parent_id": parent_id},
    )
    assert response.status_code == 200
    return response.json()


def _asset(client: TestClient, headers: dict[str, str], filename: str, folder_id: str | None = None) -> dict:
    data = {"folder_id": folder_id} if folder_id else None
    response = client.post(
        "/upload",
        headers=headers,
        data=data,
        files={"file": (filename, b"cube([1, 2, 3]);\n", "text/plain")},
    )
    assert response.status_code == 200
    return response.json()


def test_nested_navigation_pagination_and_search_are_deterministic() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        root = _folder(client, headers, "Organization Root")
        leaf = _folder(client, headers, "Organization Leaf", root["id"])
        assets = [_asset(client, headers, f"ordered-{index:02d}.scad", leaf["id"]) for index in range(7)]
        try:
            first = client.get(f"/assets?folder_id={leaf['id']}&limit=3&offset=0", headers=headers)
            second = client.get(f"/assets?folder_id={leaf['id']}&limit=3&offset=3", headers=headers)
            exact = client.get("/assets?q=ordered-06&limit=25", headers=headers)

            assert first.status_code == 200
            assert first.headers["x-has-more"] == "true"
            assert first.headers["x-next-offset"] == "3"
            assert [item["name"] for item in first.json()] == ["ordered-00", "ordered-01", "ordered-02"]
            assert [item["name"] for item in second.json()] == ["ordered-03", "ordered-04", "ordered-05"]
            assert [item["id"] for item in exact.json()] == [assets[-1]["id"]]
        finally:
            for asset in assets:
                client.delete(f"/asset/{asset['id']}", headers=headers)
            client.delete(f"/folder/{leaf['id']}", headers=headers)
            client.delete(f"/folder/{root['id']}", headers=headers)


def test_move_conflict_is_409_and_preserves_the_source_asset() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        source = _folder(client, headers, "Move Source")
        destination = _folder(client, headers, "Move Destination")
        source_asset = _asset(client, headers, "same-name.scad", source["id"])
        destination_asset = _asset(client, headers, "same-name.scad", destination["id"])
        try:
            conflict = client.post(
                f"/asset/{source_asset['id']}/folder",
                headers=headers,
                json={"folder_id": destination["id"]},
            )
            assert conflict.status_code == 409
            assert "already exists" in conflict.json()["detail"]
            source_rows = client.get(f"/assets?folder_id={source['id']}", headers=headers).json()
            assert [row["id"] for row in source_rows] == [source_asset["id"]]
            persisted = source_rows[0]
            assert client.get(persisted["url"], headers=headers).status_code == 200
        finally:
            client.delete(f"/asset/{source_asset['id']}", headers=headers)
            client.delete(f"/asset/{destination_asset['id']}", headers=headers)
            client.delete(f"/folder/{source['id']}", headers=headers)
            client.delete(f"/folder/{destination['id']}", headers=headers)


def test_concurrent_rename_has_one_winner_and_returns_409_for_the_conflict() -> None:
    with TestClient(app) as client:
        headers = _headers(client)
        folder = _folder(client, headers, "Rename Race")
        assets = [
            _asset(client, headers, "race-a.scad", folder["id"]),
            _asset(client, headers, "race-b.scad", folder["id"]),
        ]
        try:
            def rename(asset_id: str):
                return client.post(
                    f"/asset/{asset_id}/meta",
                    headers=headers,
                    json={"name": "Shared Result"},
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(rename, [asset["id"] for asset in assets]))

            assert sorted(response.status_code for response in responses) == [200, 409]
            rows = client.get(f"/assets?folder_id={folder['id']}", headers=headers).json()
            assert sum(row["name"] == "Shared Result" for row in rows) == 1
            assert len({row["name"].casefold() for row in rows}) == 2
            for row in rows:
                assert client.get(row["url"], headers=headers).status_code == 200
        finally:
            for asset in assets:
                client.delete(f"/asset/{asset['id']}", headers=headers)
            client.delete(f"/folder/{folder['id']}", headers=headers)
