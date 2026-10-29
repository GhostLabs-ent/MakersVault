"""File grants: the short-lived `?sig=` credential that replaced `?token=`.

A browser cannot put an Authorization header on an `<img>`/`<a download>`, so
the four file-serving routes accept a minted grant in the query instead. These
tests pin both halves of that contract: the mint is read-only and short-lived,
and the grant is accepted only on its own path, only while its session is live,
and only by the four routes that carry `require_file_read` - never by the list,
write or admin routes.

Every test starts from an empty users/sessions pair, an empty library and a
private storage root, so nothing here leaks a row or a file into another file.
"""

import time
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, delete, select

import asset_file_service
import asset_service
import auth
import db
import library_scan
import login_throttle as login_throttle_module
import main
import sessions
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, User, UserSession

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
VIEWER_USERNAME = "viewer"
VIEWER_PASSWORD = "viewer-password-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}
STL_BYTES = b"solid cube\nendsolid cube\n"


@dataclass(frozen=True)
class Seed:
    admin_token: str
    viewer_token: str
    viewer_refresh_token: str
    asset_id: str
    asset_filename: str
    file_id: str
    file_filename: str
    prepared_file_id: str
    prepared_filename: str


def truncate_accounts() -> None:
    with Session(engine) as session:
        session.execute(delete(UserSession))
        session.execute(delete(User))
        session.commit()


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
def isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point every storage binding at a temp root and remove the rows a test made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(main, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_service, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    run_migrations(engine)

    with Session(engine) as session:
        assets_before = {asset.id for asset in session.exec(select(Asset))}

    yield storage

    with Session(engine) as session:
        for asset_file in list(session.exec(select(AssetFile))):
            if asset_file.asset_id not in assets_before:
                session.delete(asset_file)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        session.commit()


@pytest.fixture()
def client():
    with TestClient(main.app) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ok(response):
    assert response.status_code == 200, response.text
    return response


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def create_user(client: TestClient, admin_token: str, username: str, password: str, role: str) -> dict:
    response = client.post(
        "/users",
        json={"username": username, "password": password, "role": role},
        headers=bearer(admin_token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (200, 30, 30)).save(buffer, "PNG")
    return buffer.getvalue()


def seed_library(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    """An asset with one supporting file, one prepared print and a thumbnail."""
    asset = ok(
        client.post("/upload", files={"file": ("cube.stl", STL_BYTES, "model/stl")}, headers=headers)
    ).json()
    ok(
        client.post(
            f"/asset/{asset['id']}/files",
            files={"file": ("notes.txt", b"layer notes\n", "text/plain")},
            headers=headers,
        )
    )
    ok(
        client.post(
            f"/asset/{asset['id']}/files",
            files={"file": ("cube.gcode", b"; cube\nG28\n", "text/plain")},
            headers=headers,
        )
    )
    ok(
        client.post(
            f"/asset/{asset['id']}/thumbnail-generated",
            files={"file": ("thumb.png", png_bytes(), "image/png")},
            headers=headers,
        )
    )
    with Session(engine) as session:
        asset_row = session.get(Asset, asset["id"])
        assert asset_row is not None and asset_row.prepared_file_id is not None
        supporting = session.exec(
            select(AssetFile).where(AssetFile.asset_id == asset["id"], AssetFile.role == "supporting")
        ).one()
        prepared = session.get(AssetFile, asset_row.prepared_file_id)
        assert prepared is not None
        return {
            "asset_id": asset["id"],
            "asset_filename": asset["filename"],
            "file_id": supporting.id,
            "file_filename": supporting.filename,
            "prepared_file_id": prepared.id,
            "prepared_filename": prepared.filename,
        }


@pytest.fixture()
def seed(client: TestClient) -> Seed:
    glass = login(client, **BREAK_GLASS)
    create_user(client, glass["token"], ADMIN_USERNAME, ADMIN_PASSWORD, "admin")
    admin = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    create_user(client, admin["token"], VIEWER_USERNAME, VIEWER_PASSWORD, "viewer")
    viewer = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    library = seed_library(client, bearer(admin["token"]))
    return Seed(
        admin_token=admin["token"],
        viewer_token=viewer["token"],
        viewer_refresh_token=viewer["refresh_token"],
        **library,
    )


def session_row(refresh_token: str) -> UserSession:
    with Session(engine) as session:
        row = sessions.find_by_refresh_hash(session, sessions.hash_refresh_token(refresh_token))
        assert row is not None, "the refresh token has no session row"
        session.expunge(row)
    return row


def sig_from_url(url: str) -> str:
    return parse_qs(urlsplit(url).query)["sig"][0]


def mint(client: TestClient, headers: dict[str, str], paths: list[str]):
    return client.post("/file-grants", json={"paths": paths}, headers=headers)


def grant_payload(path: str, session_id: str | None) -> dict:
    now = int(time.time())
    return {
        "aud": auth.FILE_GRANT_AUDIENCE,
        "typ": auth.FILE_GRANT_TYPE,
        "scope": auth.FILE_GRANT_SCOPE,
        "p": path,
        "sid": session_id,
        "sub": "alice",
        "iat": now,
        "exp": now + auth.FILE_GRANT_TTL_SECONDS,
    }


def test_mint_then_use_every_grantable_template(client: TestClient, seed: Seed) -> None:
    paths = [
        f"/file/{seed.asset_id}/{seed.asset_filename}",
        f"/asset/{seed.asset_id}/files/{seed.file_id}",
        f"/thumb/{seed.asset_id}.jpg",
        f"/asset/{seed.asset_id}/prepared-print",
    ]

    minted = mint(client, bearer(seed.viewer_token), paths)

    assert minted.status_code == 200, minted.text
    grants = minted.json()["grants"]
    assert [grant["path"] for grant in grants] == paths
    assert all(grant["url"].startswith(grant["path"] + "?") for grant in grants)
    assert all("sig=" in grant["url"] for grant in grants)
    assert all(0 < grant["expires_at"] - int(time.time()) <= auth.FILE_GRANT_TTL_SECONDS + 1 for grant in grants)

    for grant in grants:
        served = client.get(grant["url"])
        assert served.status_code == 200, f"{grant['path']} was refused: {served.status_code} {served.text}"


def test_a_viewer_may_mint_and_an_anonymous_caller_may_not(client: TestClient, seed: Seed) -> None:
    path = f"/thumb/{seed.asset_id}.jpg"

    as_viewer = mint(client, bearer(seed.viewer_token), [path])
    anonymous = mint(client, {}, [path])

    assert as_viewer.status_code == 200, as_viewer.text
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"] == "Unauthorized"


def test_the_mint_rejects_ungrantable_paths_and_query_keys(client: TestClient, seed: Seed) -> None:
    headers = bearer(seed.viewer_token)
    unknown = uuid4().hex
    too_many = [f"/thumb/{seed.asset_id}.jpg"] * (51)

    responses = {
        "empty": mint(client, headers, []),
        "non-grantable": mint(client, headers, ["/assets"]),
        "too many": mint(client, headers, too_many),
        "unknown query key": mint(client, headers, [f"/thumb/{seed.asset_id}.jpg?foo=1"]),
        "inline on thumb": mint(client, headers, [f"/thumb/{seed.asset_id}.jpg?inline=1"]),
        "inline is not 1": mint(client, headers, [f"/asset/{seed.asset_id}/files/{seed.file_id}?inline=yes"]),
        "scheme": mint(client, headers, [f"https://evil.example/thumb/{seed.asset_id}.jpg"]),
        "malformed authority": mint(client, headers, ["//["]),
        "fragment": mint(client, headers, [f"/thumb/{seed.asset_id}.jpg#frag"]),
        "unknown asset": mint(client, headers, [f"/thumb/{unknown}.jpg"]),
        "unknown file": mint(client, headers, [f"/asset/{seed.asset_id}/files/{unknown}"]),
        "unknown asset file template": mint(client, headers, [f"/file/{unknown}/cube.stl"]),
    }

    assert {name: response.status_code for name, response in responses.items()} == {
        "empty": 400,
        "non-grantable": 400,
        "too many": 400,
        "unknown query key": 400,
        "inline on thumb": 400,
        "inline is not 1": 400,
        "scheme": 400,
        "malformed authority": 400,
        "fragment": 400,
        "unknown asset": 404,
        "unknown file": 404,
        "unknown asset file template": 404,
    }


def test_expired_and_overlong_grants_are_refused(client: TestClient, seed: Seed) -> None:
    path = f"/thumb/{seed.asset_id}.jpg"
    row = session_row(seed.viewer_refresh_token)
    now = int(time.time())

    expired_payload = grant_payload(path, row.id)
    expired_payload.update({"iat": now - 3600, "exp": now - 1800})
    expired = jwt.encode(expired_payload, auth.file_grant_key(), algorithm=auth.AUTH_ALGO)

    overlong_payload = grant_payload(path, row.id)
    overlong_payload.update({"iat": now, "exp": now + auth.FILE_GRANT_MAX_TTL_SECONDS + 1})
    overlong = jwt.encode(overlong_payload, auth.file_grant_key(), algorithm=auth.AUTH_ALGO)

    assert client.get(f"{path}?sig={expired}").status_code == 401
    assert client.get(f"{path}?sig={overlong}").status_code == 401


def test_tampering_and_path_swapping_are_refused(client: TestClient, seed: Seed) -> None:
    thumb_path = f"/thumb/{seed.asset_id}.jpg"
    prepared_path = f"/asset/{seed.asset_id}/prepared-print"
    minted = mint(client, bearer(seed.viewer_token), [thumb_path])
    token = sig_from_url(minted.json()["grants"][0]["url"])

    header, payload, signature = token.split(".")
    flipped = f"{header}.{payload}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    secret_signed = jwt.encode(auth.decode_file_grant(token), auth.AUTH_SECRET, algorithm=auth.AUTH_ALGO)

    assert client.get(f"{thumb_path}?sig={flipped}").status_code == 401
    assert client.get(f"{thumb_path}?sig={secret_signed}").status_code == 401
    # A grant for path A is not a grant for path B, even with a valid signature.
    assert client.get(f"{prepared_path}?sig={token}").status_code == 401


def test_a_session_token_in_the_query_is_retired_on_every_file_route(client: TestClient, seed: Seed) -> None:
    paths = [
        f"/file/{seed.asset_id}/{seed.asset_filename}",
        f"/asset/{seed.asset_id}/files/{seed.file_id}",
        f"/asset/{seed.asset_id}/prepared-print",
        f"/thumb/{seed.asset_id}.jpg",
    ]

    for path in paths:
        response = client.get(path, params={"token": seed.admin_token})

        assert response.status_code == 401, f"{path} still accepted ?token=: {response.status_code} {response.text}"
        assert response.json()["detail"] == "Unauthorized"


def test_a_grant_is_not_accepted_off_the_file_routes(client: TestClient, seed: Seed) -> None:
    path = f"/thumb/{seed.asset_id}.jpg"
    minted = mint(client, bearer(seed.viewer_token), [path])
    token = sig_from_url(minted.json()["grants"][0]["url"])

    as_header_assets = client.get("/assets", headers=bearer(token))
    as_header_me = client.get("/me", headers=bearer(token))
    as_query_assets = client.get("/assets", params={"sig": token})

    assert as_header_assets.status_code == 401
    assert as_header_me.status_code == 401
    assert as_query_assets.status_code == 401


def test_a_bad_header_does_not_fall_back_to_the_grant(client: TestClient, seed: Seed) -> None:
    path = f"/thumb/{seed.asset_id}.jpg"
    minted = mint(client, bearer(seed.viewer_token), [path])
    token = sig_from_url(minted.json()["grants"][0]["url"])

    for headers in ({"Authorization": "Basic not-bearer"}, bearer("not-a-token")):
        response = client.get(f"{path}?sig={token}", headers=headers)

        assert response.status_code == 401, f"a bad header fell back to the query grant: {headers}"


def test_grants_and_session_tokens_are_cryptographically_isolated(client: TestClient, seed: Seed) -> None:
    path = f"/thumb/{seed.asset_id}.jpg"
    minted = mint(client, bearer(seed.viewer_token), [path])
    grant = sig_from_url(minted.json()["grants"][0]["url"])

    with pytest.raises(jwt.PyJWTError):
        auth.decode_access_token(grant)
    with pytest.raises(jwt.PyJWTError):
        auth.decode_file_grant(seed.admin_token)


def test_signing_out_kills_outstanding_grants(client: TestClient, seed: Seed) -> None:
    path = f"/thumb/{seed.asset_id}.jpg"
    minted = mint(client, bearer(seed.viewer_token), [path])
    url = minted.json()["grants"][0]["url"]

    assert client.get(url).status_code == 200
    assert client.post("/logout", json={"refresh_token": seed.viewer_refresh_token}).status_code == 204

    assert client.get(url).status_code == 401


def test_query_keys_and_inline_must_match_the_grant(client: TestClient, seed: Seed) -> None:
    headers = bearer(seed.viewer_token)
    plain_path = f"/asset/{seed.asset_id}/files/{seed.file_id}"
    plain = mint(client, headers, [plain_path]).json()["grants"][0]
    plain_token = sig_from_url(plain["url"])

    versioned = mint(client, headers, [f"/thumb/{seed.asset_id}.jpg?v=1"]).json()["grants"][0]
    inline = mint(client, headers, [f"{plain_path}?inline=1"]).json()["grants"][0]

    assert client.get(versioned["url"]).status_code == 200
    assert client.get(inline["url"]).status_code == 200
    # `path` echoes the request verbatim, query included, so a client can key its
    # grant cache by the exact rel it holds.
    assert versioned["path"] == f"/thumb/{seed.asset_id}.jpg?v=1"
    assert inline["path"] == f"{plain_path}?inline=1"
    assert client.get(plain["url"] + "&foo=1").status_code == 401
    assert client.get(plain["url"] + "&inline=1").status_code == 401
    assert client.get(f"{plain_path}?sig={plain_token}").status_code == 200
    assert client.get(f"{plain_path}?sig={sig_from_url(inline['url'])}").status_code == 401


def test_a_percent_encoded_path_is_bound_to_the_decoded_request_path(client: TestClient, seed: Seed) -> None:
    """The grant binds the path the *router* sees, not the bytes on the wire.

    A filename with a space arrives percent-encoded and ASGI hands the app the
    decoded path, so a grant bound to the encoded form would 401 on every such
    file even though its mint looked fine.
    """
    encoded = f"/file/{seed.asset_id}/{quote('my model.stl', safe='')}"
    assert encoded.endswith("my%20model.stl")

    minted = mint(client, bearer(seed.viewer_token), [encoded])

    assert minted.status_code == 200, minted.text
    grant = minted.json()["grants"][0]
    assert grant["path"] == encoded, "the mint must echo the path it was asked for"
    served = client.get(grant["url"])
    assert served.status_code == 200, served.text
    assert served.content == STL_BYTES


def test_the_mint_still_answers_200_when_auth_is_disabled(
    client: TestClient, seed: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)

    minted = mint(client, {}, [f"/thumb/{seed.asset_id}.jpg"])

    assert minted.status_code == 200, minted.text
    grant = minted.json()["grants"][0]
    assert "sig=" in grant["url"]
    assert client.get(grant["url"]).status_code == 200
