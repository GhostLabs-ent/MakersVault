"""Thumbnail cache-busting versions (Mf-qjxa): AC-1 and AC-2 proofs.

`asset.thumb_version` (migration 013) is a monotonic counter bumped on every
thumbnail write, so the serializer can build `?v=` from the row alone. The
first half proves the listing therefore performs no filesystem work at all on
`THUMBS`; the second half proves a regeneration visibly changes the URL and
that each URL serves its own bytes.
"""

import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select
from test_projects_api import auth_header, png_bytes, upload

import asset_service
import db
import library_scan
import main
from db import engine
from migrations import run_migrations
from models import Asset

# --- infrastructure ---------------------------------------------------------


@pytest.fixture(autouse=True)
def versioned_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every storage binding at a temp root and delete the rows we made."""
    storage = tmp_path / "storage"
    thumbs = storage / "thumbs"
    thumbs.mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", thumbs)
    # main, asset_service and library_scan bind THUMBS at import time.
    monkeypatch.setattr(main, "THUMBS", thumbs)
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "THUMBS", thumbs)
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    run_migrations(engine)
    with Session(engine) as session:
        assets_before = {asset.id for asset in session.exec(select(Asset))}
    yield thumbs
    with Session(engine) as session:
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        session.commit()


def seed_assets(count: int, prefix: str) -> list[str]:
    """Insert `count` thumbnail-less rows; the caller writes the thumbnail files."""
    with Session(engine) as session:
        ids = []
        for index in range(count):
            asset = Asset(
                name=f"{prefix}-{index}",
                filename=f"{prefix}-{index}.stl",
                mime="model/stl",
                size=1,
            )
            session.add(asset)
            ids.append(asset.id)
        session.commit()
    return ids


# --- AC-1 -------------------------------------------------------------------


def test_listing_1000_assets_never_stats_the_thumbnail_directory(versioned_storage: Path) -> None:
    """The listing reads `thumb_version`; it must not stat the CephFS thumbs tree.

    Before migration 013 `thumb_url_for` did `exists()` plus `st_mtime_ns` per
    asset, so this page cost 2000 network-filesystem stats.
    """
    prefix = f"mvqjxa-{uuid4().hex}"
    ids = seed_assets(1000, prefix)
    for asset_id in ids:
        (versioned_storage / f"{asset_id}.jpg").write_bytes(b"jpg")

    recorded: list[str] = []
    real_stat = os.stat

    def recording_stat(path, *args, **kwargs):
        recorded.append(os.fspath(path))
        return real_stat(path, *args, **kwargs)

    with TestClient(main.app) as client:
        headers = auth_header(client)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(os, "stat", recording_stat)
            response = client.get("/assets", params={"q": prefix, "limit": 1000}, headers=headers)
            assert response.status_code == 200, response.text

    body = response.json()
    assert len(body) == 1000, len(body)
    thumbs_stats = [path for path in recorded if Path(path).parent == versioned_storage]
    assert not thumbs_stats, f"the listing stat()ed {len(thumbs_stats)} THUMBS paths: {thumbs_stats[:5]}"


# --- AC-2 -------------------------------------------------------------------


def thumbnail_version(thumb_url: str) -> int:
    return int(thumb_url.rsplit("?v=", 1)[1])


def upload_thumbnail(client: TestClient, headers: dict, asset_id: str, payload: bytes | None = None) -> dict:
    response = client.post(
        f"/asset/{asset_id}/thumbnail-generated",
        files={"file": ("thumb.png", payload or png_bytes(), "image/png")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def solid_png(colour: tuple[int, int, int], size: tuple[int, int]) -> bytes:
    """A PNG whose pixels differ from `png_bytes()`, so the JPEG bytes must too."""
    buffer = BytesIO()
    Image.new("RGB", size, colour).save(buffer, "PNG")
    return buffer.getvalue()


def test_second_regeneration_returns_a_new_version_without_an_intermediate_get() -> None:
    """AC-2: two regenerations hand back distinct `?v=` with no GET in between.

    The `?v=` token is the client's only cache-busting mechanism, so a second
    regeneration that repeated the first version would leave the new image
    behind a URL the browser already holds (see the year-immutable
    Cache-Control on `/thumb/`).

    This is a contract proof, not a pin on `s.rollback()`: on the current
    engine a SELECT runs in autocommit, so the rollback is inert here and this
    test stays green without it. It becomes a genuine pin under exactly the
    configurations where the rollback matters - a read snapshot spanning the
    bump (sqlite with begin-on-read, or a non-sqlite `DB_URL` at REPEATABLE
    READ or stricter) - so it self-heals under the change that would otherwise
    break it.
    """
    with TestClient(main.app) as client:
        headers = auth_header(client)
        asset = upload(client, headers, "regenerated.stl")
        calls: list[str] = []
        real_request = client.request

        def recording_request(method: str, url, *args, **kwargs):
            calls.append(method.upper())
            return real_request(method, url, *args, **kwargs)

        client.request = recording_request
        try:
            first = upload_thumbnail(client, headers, asset["id"])
            second = upload_thumbnail(client, headers, asset["id"])
        finally:
            client.request = real_request

    assert thumbnail_version(second["thumb_url"]) != thumbnail_version(first["thumb_url"]), (first, second)
    assert "GET" not in calls, f"the second version needed a refresh GET: {calls}"


def test_each_regenerated_thumbnail_url_serves_distinct_bytes() -> None:
    """The URL handed to the client addresses the image written in that request.

    Each fetch happens before the next write, because the route serves the one
    `THUMBS/<id>.jpg` - the version token is what makes a browser ask again,
    not what makes the server keep old bytes.
    """
    with TestClient(main.app) as client:
        headers = auth_header(client)
        asset = upload(client, headers, "bytes.stl")

        first = upload_thumbnail(client, headers, asset["id"], solid_png((200, 30, 30), (4, 4)))
        first_bytes = client.get(first["thumb_url"], headers=headers).content
        second = upload_thumbnail(client, headers, asset["id"], solid_png((30, 30, 200), (32, 32)))
        second_bytes = client.get(second["thumb_url"], headers=headers).content

    assert first["thumb_url"] != second["thumb_url"]
    assert first_bytes != second_bytes, "the new URL served the old bytes"

