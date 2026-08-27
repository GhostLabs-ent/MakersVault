from fastapi import HTTPException
from fastapi.testclient import TestClient
import jwt
import pytest

import auth
from db import THUMBS
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
            primary = client.get(asset["url"], headers=headers)
            assert primary.status_code == 200
            assert primary.headers["cache-control"] == "private, no-store"

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

            prepared_download = client.get(
                f"/asset/{asset['id']}/prepared-print",
                headers=headers,
            )
            assert prepared_download.status_code == 200
            assert prepared_download.headers["cache-control"] == "private, no-store"

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


def redeem_general(
    client: TestClient,
    grant: dict,
    *,
    adapter_id: str,
    content_role: str,
):
    return client.get(
        grant["redeem_url"],
        headers={
            "Authorization": f"MakerVault-Handoff {grant['grant']}",
            "X-MakerVault-Handoff-Tool": "open",
            "X-MakerVault-Handoff-Adapter": adapter_id,
            "X-MakerVault-Handoff-Role": content_role,
        },
    )


def test_general_handoff_binds_adapter_role_and_exact_primary_file() -> None:
    client, headers = authenticated_client()
    with client:
        asset = upload_asset(client, headers, "editable.step", b"STEP primary")
        try:
            issued = client.post(
                f"/asset/{asset['id']}/handoff",
                headers=headers,
                json={"adapter_id": "freecad", "content_role": "primary"},
            )
            assert issued.status_code == 200
            body = issued.json()
            assert body["adapter_id"] == "freecad"
            assert body["content_role"] == "primary"

            assert redeem_general(
                client, body, adapter_id="inkscape", content_role="primary"
            ).status_code == 403
            assert redeem_general(
                client, body, adapter_id="freecad", content_role="supporting"
            ).status_code == 403
            redeemed = redeem_general(
                client, body, adapter_id="freecad", content_role="primary"
            )
            assert redeemed.status_code == 200
            assert redeemed.content == b"STEP primary"
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_general_handoff_selects_historical_supporting_and_prepared_files() -> None:
    client, headers = authenticated_client()
    with client:
        asset = upload_asset(client, headers, "versioned.stl", b"first revision")
        try:
            first_revision = client.get(
                f"/asset/{asset['id']}/revisions", headers=headers
            ).json()[0]
            replaced = client.post(
                f"/asset/{asset['id']}/revisions",
                headers=headers,
                files={"file": ("versioned.stl", b"second revision", "model/stl")},
            )
            assert replaced.status_code == 200

            historical = client.post(
                f"/asset/{asset['id']}/handoff",
                headers=headers,
                json={
                    "adapter_id": "freecad",
                    "content_role": "revision_primary",
                    "revision_id": first_revision["id"],
                },
            )
            assert historical.status_code == 200
            assert redeem_general(
                client,
                historical.json(),
                adapter_id="freecad",
                content_role="revision_primary",
            ).content == b"first revision"

            supporting_upload = client.post(
                f"/asset/{asset['id']}/files",
                headers=headers,
                files={"file": ("drawing.svg", b"<svg/>", "image/svg+xml")},
            )
            assert supporting_upload.status_code == 200
            supporting_id = client.get(
                f"/asset/{asset['id']}/files", headers=headers
            ).json()[0]["id"]
            supporting = client.post(
                f"/asset/{asset['id']}/handoff",
                headers=headers,
                json={
                    "adapter_id": "inkscape",
                    "content_role": "supporting",
                    "file_id": supporting_id,
                },
            )
            assert supporting.status_code == 200
            assert redeem_general(
                client,
                supporting.json(),
                adapter_id="inkscape",
                content_role="supporting",
            ).content == b"<svg/>"

            prepared_upload = client.post(
                f"/asset/{asset['id']}/files",
                headers=headers,
                files={"file": ("plate.gcode", b"G1 X20", "text/plain")},
            )
            assert prepared_upload.status_code == 200
            prepared = client.post(
                f"/asset/{asset['id']}/handoff",
                headers=headers,
                json={"adapter_id": "orca", "content_role": "prepared"},
            )
            assert prepared.status_code == 200
            assert redeem_general(
                client, prepared.json(), adapter_id="orca", content_role="prepared"
            ).content == b"G1 X20"
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_general_handoff_rejects_ambiguous_or_unbounded_selection() -> None:
    client, headers = authenticated_client()
    with client:
        asset = upload_asset(client, headers, "bounded.step", b"STEP")
        try:
            invalid_bodies = [
                {"tool": "slicer", "adapter_id": "freecad", "content_role": "primary"},
                {"adapter_id": "freecad", "content_role": "revision_primary"},
                {"adapter_id": "inkscape", "content_role": "supporting"},
                {"adapter_id": "freecad", "content_role": "other"},
                {"adapter_id": "other", "content_role": "primary"},
            ]
            for body in invalid_bodies:
                response = client.post(
                    f"/asset/{asset['id']}/handoff", headers=headers, json=body
                )
                assert response.status_code == 422, body
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
    header, payload, signature = valid.split(".")
    altered_signature = f"{'a' if signature[0] != 'a' else 'b'}{signature[1:]}"
    altered = f"{header}.{payload}.{altered_signature}"
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

    unbound_general = auth.create_handoff_token(
        "asset", "primary", "asset", "open", "model.stl", 5
    )
    with pytest.raises(HTTPException, match="Invalid"):
        auth.decode_handoff_token(unbound_general)

    widened_legacy = auth.create_handoff_token(
        "asset",
        "primary",
        "asset",
        "slicer",
        "model.stl",
        5,
        "primary",
        "freecad",
    )
    with pytest.raises(HTTPException, match="Invalid"):
        auth.decode_handoff_token(widened_legacy)


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


def test_thumbnail_and_supporting_files_are_private_no_store() -> None:
    client, headers = authenticated_client()
    with client:
        asset = upload_asset(client, headers, "documented-model.stl", b"solid model")
        thumb_path = THUMBS / f"{asset['id']}.jpg"
        try:
            THUMBS.mkdir(parents=True, exist_ok=True)
            thumb_path.write_bytes(b"thumbnail")
            thumbnail = client.get(f"/thumb/{asset['id']}.jpg", headers=headers)
            assert thumbnail.status_code == 200
            assert thumbnail.headers["cache-control"] == "private, no-store"

            attached = client.post(
                f"/asset/{asset['id']}/files",
                headers=headers,
                files={"file": ("assembly.pdf", b"supporting document", "application/pdf")},
            )
            assert attached.status_code == 200
            files = client.get(f"/asset/{asset['id']}/files", headers=headers).json()
            assert len(files) == 1
            supporting = client.get(files[0]["url"], headers=headers)
            assert supporting.status_code == 200
            assert supporting.headers["cache-control"] == "private, no-store"
        finally:
            client.delete(f"/asset/{asset['id']}", headers=headers)
