"""Supporting-file polish: order, rename, inline preview and the caps (Mf-k7hb).

A supporting file is a visible attachment on a model. This ticket gives that
list a user-visible order (upload appends, `PUT .../order` rewrites it), a
display-only rename (`PATCH .../{file_id}` - the stored bytes never move),
inline previews for a small allow-list of types, and three ceilings per model:
per-file bytes, total bytes and count. The byte caps are enforced inside the
write transaction that stores the row, so a rejected upload leaves neither a row
nor bytes behind.

Every test works in a temporary storage root (the shared session database is
restored at teardown, exactly like `test_upload_streaming.py`). Audit rows are
looked up by the `X-Request-ID` the client sent, because the append-only table
cannot be cleaned up.
"""

import json
from io import BytesIO
from pathlib import Path
from typing import List
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, select

import asset_file_service
import asset_service
import audit
import db
import library_scan
import main
import settings_service
import zip_service
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, AuditEvent, Folder

STL_BYTES = b"solid cube\nendsolid cube\n"
REQUEST_ID_HEADER = "X-Request-ID"
TEXT_PAYLOAD = b"layer notes\n"


# --- infrastructure ---------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every storage binding at a temp root and undo every row made here."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(main, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    run_migrations(engine)
    template_before = settings_service.get_storage_template()
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        files_before = {row.id for row in session.exec(select(AssetFile))}
    yield storage
    settings_service.set_storage_template(template_before)
    with Session(engine) as session:
        for row in list(session.exec(select(AssetFile))):
            if row.id not in files_before:
                session.delete(row)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        session.commit()


@pytest.fixture()
def client():
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture()
def headers(client: TestClient) -> dict:
    return auth_header(client)


def auth_header(client: TestClient) -> dict:
    """Bearer token, or empty when the app is running with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


# --- helpers ----------------------------------------------------------------


def upload_asset(client: TestClient, headers: dict) -> dict:
    """A fresh model; the name is unique because a folder holds one name only."""
    filename = f"{uuid4().hex}.stl"
    response = client.post("/upload", files={"file": (filename, STL_BYTES, "model/stl")}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def upload_supporting(
    client: TestClient,
    headers: dict,
    asset_id: str,
    filename: str,
    payload: bytes = TEXT_PAYLOAD,
    content_type: str = "text/plain",
) -> Response:
    return client.post(
        f"/asset/{asset_id}/files",
        files={"file": (filename, payload, content_type)},
        headers=headers,
    )


def add_supporting(
    client: TestClient,
    headers: dict,
    asset_id: str,
    filename: str,
    payload: bytes = TEXT_PAYLOAD,
    content_type: str = "text/plain",
) -> dict:
    """Upload a supporting file and return its `AssetFileOut`.

    The upload and delete routes answer with the parent `AssetOut` (unchanged
    contract), so the new row is read back from the list by its name.
    """
    response = upload_supporting(client, headers, asset_id, filename, payload, content_type)
    assert response.status_code == 200, response.text
    return by_name(client, headers, asset_id, filename)


def supporting_rows(client: TestClient, headers: dict, asset_id: str) -> List[dict]:
    response = client.get(f"/asset/{asset_id}/files", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def filenames(client: TestClient, headers: dict, asset_id: str) -> List[str]:
    return [row["filename"] for row in supporting_rows(client, headers, asset_id)]


def by_name(client: TestClient, headers: dict, asset_id: str, filename: str) -> dict:
    for row in supporting_rows(client, headers, asset_id):
        if row["filename"] == filename:
            return row
    raise AssertionError(f"{filename!r} is not in the supporting list: {filenames(client, headers, asset_id)}")


def zip_entries(response: Response) -> List[str]:
    with ZipFile(BytesIO(response.content)) as archive:
        return archive.namelist()


def stored_files(storage: Path) -> List[Path]:
    return [path for path in storage.rglob("*") if path.is_file()]


def incoming_files(storage: Path) -> List[Path]:
    incoming = storage / asset_service.STAGING_DIRNAME
    return [path for path in incoming.iterdir()] if incoming.is_dir() else []


def asset_file_record(file_id: str) -> AssetFile:
    with Session(engine) as session:
        record = session.get(AssetFile, file_id)
        assert record is not None
        return record


def audit_rows(request_id: str) -> List[AuditEvent]:
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.request_id == request_id)))


def request_id_for(test_name: str) -> str:
    return f"{test_name}-{uuid4().hex}"


# --- order ------------------------------------------------------------------


def test_uploads_append_to_the_list_in_upload_order(client, headers) -> None:
    asset = upload_asset(client, headers)
    for name in ("bravo.txt", "alpha.txt", "charlie.txt"):
        add_supporting(client, headers, asset["id"], name)

    rows = supporting_rows(client, headers, asset["id"])

    assert [row["filename"] for row in rows] == ["bravo.txt", "alpha.txt", "charlie.txt"]
    assert [row["position"] for row in rows] == [0, 1, 2]
    assert {row["url"] for row in rows} == {f"/asset/{asset['id']}/files/{row['id']}" for row in rows}
    assert [row["size"] for row in rows] == [len(TEXT_PAYLOAD)] * 3


def test_reorder_rewrites_the_list_the_zip_and_the_positions(client, headers) -> None:
    asset = upload_asset(client, headers)
    first = add_supporting(client, headers, asset["id"], "bravo.txt")
    second = add_supporting(client, headers, asset["id"], "alpha.txt")
    assert filenames(client, headers, asset["id"]) == ["bravo.txt", "alpha.txt"]

    response = client.put(
        f"/asset/{asset['id']}/files/order",
        json={"file_ids": [second["id"], first["id"]]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert [(row["filename"], row["position"]) for row in response.json()] == [("alpha.txt", 0), ("bravo.txt", 1)]
    assert filenames(client, headers, asset["id"]) == ["alpha.txt", "bravo.txt"]

    download = client.post("/download/zip", json={"asset_ids": [asset["id"]]}, headers=headers)
    assert download.status_code == 200, download.text
    assert zip_entries(download) == [
        f"unassigned/{asset['filename']}",
        f"unassigned/{asset['name']}/supporting/alpha.txt",
        f"unassigned/{asset['name']}/supporting/bravo.txt",
    ]


def test_rename_shows_the_new_name_in_the_zip(client, headers) -> None:
    asset = upload_asset(client, headers)
    row = add_supporting(client, headers, asset["id"], "alpha.txt")

    renamed = client.patch(
        f"/asset/{asset['id']}/files/{row['id']}",
        json={"filename": "layers.txt"},
        headers=headers,
    )

    assert renamed.status_code == 200, renamed.text
    download = client.post("/download/zip", json={"asset_ids": [asset["id"]]}, headers=headers)
    assert download.status_code == 200, download.text
    assert zip_entries(download) == [
        f"unassigned/{asset['filename']}",
        f"unassigned/{asset['name']}/supporting/layers.txt",
    ]


def test_zip_dedupes_duplicate_member_names_in_input_order(client, headers) -> None:
    asset = upload_asset(client, headers)
    add_supporting(client, headers, asset["id"], "notes.txt", b"first\n")
    add_supporting(client, headers, asset["id"], "notes.txt", b"second\n")

    response = client.post("/download/zip", json={"asset_ids": [asset["id"]]}, headers=headers)

    assert response.status_code == 200, response.text
    assert zip_entries(response) == [
        f"unassigned/{asset['filename']}",
        f"unassigned/{asset['name']}/supporting/notes.txt",
        f"unassigned/{asset['name']}/supporting/notes (2).txt",
    ]


def test_dedupe_arcnames_keeps_the_first_occurrence(tmp_path: Path) -> None:
    entries = [
        ("Model/part.stl", tmp_path / "one"),
        ("Model/notes", tmp_path / "two"),
        ("Model/part.stl", tmp_path / "three"),
        ("Model/part.stl", tmp_path / "four"),
        ("Model/notes", tmp_path / "five"),
    ]

    deduped = zip_service.dedupe_arcnames(entries)

    assert [arcname for arcname, _ in deduped] == [
        "Model/part.stl",
        "Model/notes",
        "Model/part (2).stl",
        "Model/part (3).stl",
        "Model/notes (2)",
    ]
    assert [path.name for _, path in deduped] == ["one", "two", "three", "four", "five"]


def test_reorder_rejects_stale_duplicate_and_unknown_requests(client, headers) -> None:
    asset = upload_asset(client, headers)
    first = add_supporting(client, headers, asset["id"], "one.txt")
    second = add_supporting(client, headers, asset["id"], "two.txt")

    missing = client.put(
        "/asset/does-not-exist/files/order",
        json={"file_ids": [first["id"], second["id"]]},
        headers=headers,
    )
    assert missing.status_code == 404, missing.text

    duplicate = client.put(
        f"/asset/{asset['id']}/files/order",
        json={"file_ids": [first["id"], first["id"]]},
        headers=headers,
    )
    assert duplicate.status_code == 400, duplicate.text

    stale = client.put(
        f"/asset/{asset['id']}/files/order",
        json={"file_ids": [first["id"]]},
        headers=headers,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"] == "Supporting file list changed; reload and try again"

    unknown = client.put(
        f"/asset/{asset['id']}/files/order",
        json={"file_ids": [first["id"], "00000000-0000-0000-0000-000000000000"]},
        headers=headers,
    )
    assert unknown.status_code == 409, unknown.text
    assert filenames(client, headers, asset["id"]) == ["one.txt", "two.txt"]


def test_unchanged_order_and_unchanged_rename_write_no_audit_row(client, headers) -> None:
    asset = upload_asset(client, headers)
    first = add_supporting(client, headers, asset["id"], "one.txt")
    second = add_supporting(client, headers, asset["id"], "two.txt")

    order_value = request_id_for("order-noop")
    response = client.put(
        f"/asset/{asset['id']}/files/order",
        json={"file_ids": [first["id"], second["id"]]},
        headers={**headers, REQUEST_ID_HEADER: order_value},
    )
    assert response.status_code == 200, response.text
    assert audit_rows(order_value) == []

    rename_value = request_id_for("rename-noop")
    response = client.patch(
        f"/asset/{asset['id']}/files/{first['id']}",
        json={"filename": "one.txt"},
        headers={**headers, REQUEST_ID_HEADER: rename_value},
    )
    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "one.txt"
    assert audit_rows(rename_value) == []


# --- rename -----------------------------------------------------------------


def test_rename_changes_the_display_name_and_leaves_the_bytes_alone(client, headers, isolated_storage) -> None:
    asset = upload_asset(client, headers)
    row = add_supporting(client, headers, asset["id"], "notes.txt")
    before = asset_file_record(row["id"])
    original_path = isolated_storage / before.storage_path
    assert original_path.read_bytes() == TEXT_PAYLOAD

    response = client.patch(
        f"/asset/{asset['id']}/files/{row['id']}",
        json={"filename": "  Layer Notes.txt  "},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"] == "Layer Notes.txt"
    assert body["position"] == row["position"]
    assert body["size"] == len(TEXT_PAYLOAD)
    assert filenames(client, headers, asset["id"]) == ["Layer Notes.txt"]

    after = asset_file_record(row["id"])
    assert after.storage_path == before.storage_path
    assert after.size == before.size
    assert after.mime == before.mime
    assert original_path.read_bytes() == TEXT_PAYLOAD
    assert not any(path.name == "Layer Notes.txt" for path in stored_files(isolated_storage))

    download = client.get(f"/asset/{asset['id']}/files/{row['id']}", headers=headers)
    assert download.status_code == 200, download.text
    assert download.content == TEXT_PAYLOAD
    # Starlette encodes the name as `filename*=utf-8''...` when it is not plain.
    assert download.headers["content-disposition"].startswith("attachment")
    assert "Layer%20Notes.txt" in download.headers["content-disposition"]


def test_rename_validation_duplicates_and_missing_rows(client, headers) -> None:
    asset = upload_asset(client, headers)
    row = add_supporting(client, headers, asset["id"], "notes.txt")
    add_supporting(client, headers, asset["id"], "other.txt")
    url = f"/asset/{asset['id']}/files/{row['id']}"

    for bad_name in ("", "   ", "sub/notes.txt", "sub\\notes.txt", "..", ".", "x" * 201, "nul\x00byte.txt"):
        response = client.patch(url, json={"filename": bad_name}, headers=headers)
        assert response.status_code == 400, (bad_name, response.status_code, response.text)
        assert response.json()["detail"]

    duplicate = client.patch(url, json={"filename": "OTHER.txt"}, headers=headers)
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"] == "A supporting file with that name already exists on this model"

    assert client.patch("/asset/nope/files/" + row["id"], json={"filename": "x.txt"}, headers=headers).status_code == 404
    assert client.patch(url.replace(row["id"], "does-not-exist"), json={"filename": "x.txt"}, headers=headers).status_code == 404

    other_asset = upload_asset(client, headers)
    wrong_asset = client.patch(
        f"/asset/{other_asset['id']}/files/{row['id']}",
        json={"filename": "moved.txt"},
        headers=headers,
    )
    assert wrong_asset.status_code == 404, wrong_asset.text
    assert filenames(client, headers, asset["id"]) == ["notes.txt", "other.txt"]


def test_rename_and_reorder_are_audited(client, headers) -> None:
    asset = upload_asset(client, headers)
    first = add_supporting(client, headers, asset["id"], "one.txt")
    second = add_supporting(client, headers, asset["id"], "two.txt")

    rename_value = request_id_for("file-rename")
    renamed = client.patch(
        f"/asset/{asset['id']}/files/{first['id']}",
        json={"filename": "renamed.txt"},
        headers={**headers, REQUEST_ID_HEADER: rename_value},
    )
    assert renamed.status_code == 200, renamed.text
    rows = audit_rows(rename_value)
    assert [row.action for row in rows] == [audit.ASSET_FILE_RENAME]
    assert rows[0].target == asset["id"]
    assert json.loads(rows[0].detail_json or "{}") == {
        "file_id": first["id"],
        "from": "one.txt",
        "to": "renamed.txt",
    }

    order_value = request_id_for("file-reorder")
    reordered = client.put(
        f"/asset/{asset['id']}/files/order",
        json={"file_ids": [second["id"], first["id"]]},
        headers={**headers, REQUEST_ID_HEADER: order_value},
    )
    assert reordered.status_code == 200, reordered.text
    rows = audit_rows(order_value)
    assert [row.action for row in rows] == [audit.ASSET_FILE_REORDER]
    assert rows[0].target == asset["id"]
    assert json.loads(rows[0].detail_json or "{}") == {"order": [second["id"], first["id"]]}


# --- inline preview ---------------------------------------------------------


def test_inline_preview_headers_for_each_supported_type(client, headers) -> None:
    asset = upload_asset(client, headers)
    pdf = add_supporting(client, headers, asset["id"], "brief.pdf", b"%PDF-1.4\n", "application/pdf")
    png = add_supporting(client, headers, asset["id"], "preview.png", b"\x89PNG\r\n\x1a\n", "image/png")
    text = add_supporting(client, headers, asset["id"], "notes.txt", TEXT_PAYLOAD, "text/plain")

    pdf_response = client.get(f"/asset/{asset['id']}/files/{pdf['id']}", params={"inline": 1}, headers=headers)
    assert pdf_response.status_code == 200, pdf_response.text
    assert pdf_response.headers["content-type"] == "application/pdf"
    assert pdf_response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in pdf_response.headers
    assert pdf_response.headers["content-disposition"].startswith("inline")
    assert pdf_response.content == b"%PDF-1.4\n"

    png_response = client.get(f"/asset/{asset['id']}/files/{png['id']}", params={"inline": 1}, headers=headers)
    assert png_response.status_code == 200, png_response.text
    assert png_response.headers["content-type"] == "image/png"
    assert png_response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in png_response.headers

    text_response = client.get(f"/asset/{asset['id']}/files/{text['id']}", params={"inline": 1}, headers=headers)
    assert text_response.status_code == 200, text_response.text
    assert text_response.headers["content-type"] == "text/plain; charset=utf-8"
    assert text_response.headers["x-content-type-options"] == "nosniff"
    assert text_response.headers["content-security-policy"] == "sandbox"
    assert text_response.content == TEXT_PAYLOAD

    # The default stays an attachment download, unchanged by this ticket.
    download = client.get(f"/asset/{asset['id']}/files/{pdf['id']}", headers=headers)
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment")


def test_inline_preview_refuses_svg_and_unknown_types(client, headers) -> None:
    asset = upload_asset(client, headers)
    svg = add_supporting(client, headers, asset["id"], "logo.svg", b"<svg></svg>", "image/svg+xml")
    stl = add_supporting(client, headers, asset["id"], "part.stl", STL_BYTES, "model/stl")

    for row in (svg, stl):
        response = client.get(f"/asset/{asset['id']}/files/{row['id']}", params={"inline": 1}, headers=headers)
        assert response.status_code == 415, (row["filename"], response.text)
        assert response.json()["detail"] == "This file type cannot be previewed"

    # A disguised SVG (declared as text) is served as plain text, never as markup.
    html = add_supporting(client, headers, asset["id"], "page.html", b"<script>alert(1)</script>", "text/html")
    response = client.get(f"/asset/{asset['id']}/files/{html['id']}", params={"inline": 1}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-security-policy"] == "sandbox"


def test_octet_stream_falls_back_to_the_extension_and_svg_stays_refused() -> None:
    pdf = AssetFile(asset_id="a", filename="brief.pdf", mime="application/octet-stream", storage_path="x")
    svg = AssetFile(asset_id="a", filename="logo.svg", mime="application/octet-stream", storage_path="x")
    unknown = AssetFile(asset_id="a", filename="part.stl", mime="model/stl", storage_path="x")

    assert asset_file_service.preview_media_type(pdf) == "application/pdf"
    assert asset_file_service.preview_media_type(svg) is None
    assert asset_file_service.preview_media_type(unknown) is None


# --- limits -----------------------------------------------------------------


def test_limits_endpoint_reports_the_counts_and_the_caps(client, headers, monkeypatch) -> None:
    asset = upload_asset(client, headers)
    add_supporting(client, headers, asset["id"], "one.txt", b"12345")
    add_supporting(client, headers, asset["id"], "two.txt", b"678")

    response = client.get(f"/asset/{asset['id']}/files/limits", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "count": 2,
        "total_bytes": 8,
        "max_count": main.ASSET_FILE_MAX_COUNT,
        "max_file_bytes": main.ASSET_FILE_MAX_BYTES,
        "max_total_bytes": main.ASSET_FILE_TOTAL_MAX_BYTES,
    }
    assert client.get("/asset/does-not-exist/files/limits", headers=headers).status_code == 404

    monkeypatch.setattr(main, "ASSET_FILE_MAX_COUNT", 0)
    disabled = client.get(f"/asset/{asset['id']}/files/limits", headers=headers)
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["max_count"] == 0


def test_count_limit_rejects_the_third_file_and_leaves_nothing_behind(client, headers, isolated_storage, monkeypatch) -> None:
    monkeypatch.setattr(main, "ASSET_FILE_MAX_COUNT", 2)
    asset = upload_asset(client, headers)
    add_supporting(client, headers, asset["id"], "one.txt")
    add_supporting(client, headers, asset["id"], "two.txt")
    files_before = set(stored_files(isolated_storage))

    response = upload_supporting(client, headers, asset["id"], "three.txt")

    assert response.status_code == 413, response.text
    assert response.json()["detail"] == "This model already has the maximum 2 supporting files"
    assert filenames(client, headers, asset["id"]) == ["one.txt", "two.txt"]
    assert set(stored_files(isolated_storage)) == files_before
    assert incoming_files(isolated_storage) == []
    assert client.get(f"/asset/{asset['id']}/files/limits", headers=headers).json()["count"] == 2


def test_total_limit_rejects_the_upload_that_would_cross_it(client, headers, isolated_storage, monkeypatch) -> None:
    monkeypatch.setattr(main, "ASSET_FILE_TOTAL_MAX_BYTES", 10)
    asset = upload_asset(client, headers)
    add_supporting(client, headers, asset["id"], "one.txt", b"123456")
    files_before = set(stored_files(isolated_storage))

    response = upload_supporting(client, headers, asset["id"], "two.txt", b"123456")

    assert response.status_code == 413, response.text
    assert response.json()["detail"] == "Supporting files for this model would exceed the 10 bytes total limit"
    assert filenames(client, headers, asset["id"]) == ["one.txt"]
    assert set(stored_files(isolated_storage)) == files_before
    assert incoming_files(isolated_storage) == []
    limits = client.get(f"/asset/{asset['id']}/files/limits", headers=headers).json()
    assert limits["count"] == 1
    assert limits["total_bytes"] == 6


def test_per_file_limit_rejects_before_the_row_is_stored(client, headers, isolated_storage, monkeypatch) -> None:
    monkeypatch.setattr(main, "ASSET_FILE_MAX_BYTES", 4)
    asset = upload_asset(client, headers)
    files_before = set(stored_files(isolated_storage))

    response = upload_supporting(client, headers, asset["id"], "too-big.txt", b"0123456789")

    assert response.status_code == 413, response.text
    assert response.json()["detail"] == "Supporting file exceeds the 4 bytes limit"
    assert filenames(client, headers, asset["id"]) == []
    assert set(stored_files(isolated_storage)) == files_before
    assert incoming_files(isolated_storage) == []
    assert client.get(f"/asset/{asset['id']}/files/limits", headers=headers).json()["count"] == 0
