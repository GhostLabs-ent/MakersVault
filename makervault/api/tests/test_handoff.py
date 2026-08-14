from fastapi import HTTPException
from fastapi.testclient import TestClient
import jwt
import pytest

import auth
from main import app


def authenticated_client() -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    login = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert login.status_code == 200
    return client, {"Authorization": f"Bearer {login.json()['token']}"}


def upload_asset(client: TestClient, headers: dict[str, str], name: str, data: bytes) -> dict:
    response = client.post(
        "/upload",
        headers=headers,
        files={"file": (name, data, "application/octet-stream")},
    )
    assert response.status_code == 200
    return response.json()


def test_file_scoped_grant_redeems_but_cannot_authenticate_api() -> None:
    client, headers = authenticated_client()
    with client:
        asset = upload_asset(client, headers, "handoff-model.stl", b"solid handoff")
        try:
            issued = client.post(
                f"/asset/{asset['id']}/handoff",
                headers=headers,
                json={"tool": "slicer"},
            )
            assert issued.status_code == 200
            body = issued.json()
            grant = body["grant"]
            assert body["redeem_url"] == "/handoff/redeem"
            assert body["expires_in"] == 90
            assert issued.headers["cache-control"] == "private, no-store"

            assert client.get("/assets", params={"token": grant}).status_code == 401
            assert client.get(
                "/assets", headers={"Authorization": f"Bearer {grant}"}
            ).status_code == 401
            assert client.get(body["redeem_url"], params={"token": grant}).status_code == 401
            assert client.get(
                body["redeem_url"],
                headers={
                    "Authorization": f"MakerVault-Handoff {grant}",
                    "X-MakerVault-Handoff-Tool": "engraver",
                },
            ).status_code == 403

            redeemed = client.get(
                body["redeem_url"],
                headers={
                    "Authorization": f"MakerVault-Handoff {grant}",
                    "X-MakerVault-Handoff-Tool": "slicer",
                },
            )
            assert redeemed.status_code == 200
            assert redeemed.content == b"solid handoff"
            assert redeemed.headers["cache-control"] == "private, no-store"
            assert "handoff-model.stl" in redeemed.headers["content-disposition"]

            retried = client.get(
                body["redeem_url"],
                headers={
                    "Authorization": f"MakerVault-Handoff {grant}",
                    "X-MakerVault-Handoff-Tool": "slicer",
                },
            )
            assert retried.status_code == 200
            assert retried.content == b"solid handoff"
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_slicer_handoff_prefers_attached_prepared_file() -> None:
    client, headers = authenticated_client()
    with client:
        asset = upload_asset(client, headers, "primary-model.stl", b"solid primary")
        try:
            attached = client.post(
                f"/asset/{asset['id']}/files",
                headers=headers,
                files={"file": ("plate.gcode", b"G1 X10 Y10", "text/plain")},
            )
            assert attached.status_code == 200

            issued = client.post(
                f"/asset/{asset['id']}/handoff",
                headers=headers,
                json={"tool": "slicer"},
            )
            assert issued.status_code == 200
            body = issued.json()
            assert body["filename"] == "plate.gcode"

            redeemed = client.get(
                body["redeem_url"],
                headers={
                    "Authorization": f"MakerVault-Handoff {body['grant']}",
                    "X-MakerVault-Handoff-Tool": "slicer",
                },
            )
            assert redeemed.status_code == 200
            assert redeemed.content == b"G1 X10 Y10"
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_expired_and_tampered_handoff_grants_fail(monkeypatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(auth.time, "time", lambda: 1)
        expired = auth.create_handoff_token(
            "asset", "primary", "asset", "slicer", "model.stl", 5
        )
    with pytest.raises(HTTPException, match="expired"):
        auth.decode_handoff_token(expired)

    valid = auth.create_handoff_token(
        "asset", "primary", "asset", "slicer", "model.stl", 5
    )
    altered = f"{valid[:-1]}{'a' if valid[-1] != 'a' else 'b'}"
    with pytest.raises(HTTPException, match="Invalid"):
        auth.decode_handoff_token(altered)

    payload = jwt.decode(valid, options={"verify_signature": False})
    payload["aud"] = "another-client"
    wrong_audience = jwt.encode(
        payload,
        auth._handoff_signing_key(),
        algorithm=auth.AUTH_ALGO,
    )
    with pytest.raises(HTTPException, match="Invalid"):
        auth.decode_handoff_token(wrong_audience)


def test_grant_for_unknown_file_cannot_redeem() -> None:
    grant = auth.create_handoff_token(
        "missing-asset", "primary", "missing-asset", "slicer", "model.stl", 5
    )
    with TestClient(app) as client:
        response = client.get(
            "/handoff/redeem",
            headers={
                "Authorization": f"MakerVault-Handoff {grant}",
                "X-MakerVault-Handoff-Tool": "slicer",
            },
        )
    assert response.status_code == 404
