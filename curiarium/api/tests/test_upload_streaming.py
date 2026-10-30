"""Large uploads stream into storage instead of being spooled to temp (Mf-ryuf).

Starlette's form parser writes every file part into a ``SpooledTemporaryFile``
before the handler sees it, so a big upload is written twice: once to the OS
temp directory and once to storage. The upload routes now drive python-multipart
themselves and stream each chunk into ``<storage>/.incoming/<uuid>``, which is
then renamed into the rendered destination. These tests pin that behaviour:
the event loop never does file I/O, the byte cap is enforced mid-stream, and no
failure path leaves an orphan row or a partial file behind. The
generated-thumbnail route streams the same way, with a fixed 8 MiB cap and a
content-type gate that runs before any of its bytes are staged.

Every test works in a temporary storage root (the database is shared for the
whole session, so rows and the template are restored at teardown).

Storing a related file does database and filesystem work, so ``save_asset_file``
hands the whole store to a worker thread (Mf-rmfb) while the multipart bytes keep
streaming elsewhere. These tests pin that the write and the prepared-print
inspection never run on the event loop, that ``/health`` stays answerable while a
large supporting file is being stored, and that a failing inspection keeps the
stored bytes instead of unwinding the upload.
"""

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest
import starlette.formparsers
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

import asset_file_service
import asset_service
import db
import library_scan
import main
import multipart_stream
import settings_service
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, Folder
from routers import asset_files

BOUNDARY = "mv-stream-boundary"


def auth_header(client: TestClient) -> dict:
    """Bearer token, or empty when the app is running with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def multipart_body(parts: List[Tuple[str, Optional[str], Optional[str], bytes]]) -> bytes:
    """Build a multipart body; a filename turns a part into a file part."""
    chunks: List[bytes] = []
    for name, filename, content_type, payload in parts:
        chunks.append(f"--{BOUNDARY}\r\n".encode())
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        chunks.append(f"{disposition}\r\n".encode())
        if content_type:
            chunks.append(f"Content-Type: {content_type}\r\n".encode())
        chunks.append(b"\r\n")
        chunks.append(payload)
        chunks.append(b"\r\n")
    chunks.append(f"--{BOUNDARY}--\r\n".encode())
    return b"".join(chunks)


def multipart_headers(headers: dict) -> dict:
    return {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}", **headers}


def asset_ids() -> set:
    with Session(engine) as session:
        return {asset.id for asset in session.exec(select(Asset))}


def stored_files(storage: Path) -> List[Path]:
    return [path for path in storage.rglob("*") if path.is_file()]


def incoming_files(storage: Path) -> List[Path]:
    incoming = storage / asset_service.STAGING_DIRNAME
    return [path for path in incoming.iterdir()] if incoming.is_dir() else []


@dataclass
class SinkWrite:
    """One ``FileSink.write`` call: which thread ran it and how many bytes it got."""

    thread: str
    size: int
    received_before: int


def record_sink_writes(monkeypatch: pytest.MonkeyPatch, received: List[int]) -> List[SinkWrite]:
    """Spy on the writer so a test can see the thread and the streaming order."""
    writes: List[SinkWrite] = []
    real_write = multipart_stream.FileSink.write

    def spy(sink: multipart_stream.FileSink, data: bytes) -> None:
        writes.append(SinkWrite(threading.current_thread().name, len(data), len(received)))
        real_write(sink, data)

    monkeypatch.setattr(multipart_stream.FileSink, "write", spy)
    return writes


def asgi_scope(headers: List[Tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/upload",
        "raw_path": b"/upload",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }


def bearer_headers(token_headers: Dict[str, str], content_type: str) -> List[Tuple[bytes, bytes]]:
    headers = [(b"content-type", content_type.encode())]
    for name, value in token_headers.items():
        headers.append((name.lower().encode(), value.encode()))
    return headers


async def call_app(scope: dict, receive) -> List[dict]:
    messages: List[dict] = []

    async def send(message: dict) -> None:
        messages.append(message)

    await main.app(scope, receive, send)
    return messages


def response_status(messages: List[dict]) -> int:
    starts = [message for message in messages if message["type"] == "http.response.start"]
    assert starts, messages
    return starts[0]["status"]


def response_json(messages: List[dict]) -> dict:
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return json.loads(body)


def bootstrap_headers() -> Dict[str, str]:
    with TestClient(main.app, raise_server_exceptions=False) as client:
        return auth_header(client)


def png_bytes() -> bytes:
    """A real PNG that Pillow can decode, small enough to inline."""
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (30, 120, 200)).save(buffer, "PNG")
    return buffer.getvalue()


def post_raw(path: str, body: bytes, headers: Dict[str, str], chunk_size: int = 65536) -> Tuple[List[dict], int]:
    """Replay ``body`` through the app in fixed chunks; return the response and bytes pulled."""
    chunks = [body[index : index + chunk_size] for index in range(0, len(body), chunk_size)]
    state = {"index": 0, "consumed": 0}

    async def receive() -> dict:
        if state["index"] >= len(chunks):
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = chunks[state["index"]]
        state["index"] += 1
        state["consumed"] += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": state["index"] < len(chunks)}

    scope = asgi_scope(bearer_headers(headers, f"multipart/form-data; boundary={BOUNDARY}"))
    scope["path"] = path
    scope["raw_path"] = path.encode()
    messages = asyncio.run(call_app(scope, receive))
    return messages, state["consumed"]


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every storage binding at a temp root and undo every row made here."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    # These modules bind STORAGE at import time, so their globals are patched too.
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    # ``main`` re-exports both roots, and a fixture elsewhere patches them there.
    monkeypatch.setattr(main, "THUMBS", storage / "thumbs")
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


def test_aborted_stream_leaves_no_row_and_no_partial_file(isolated_storage: Path) -> None:
    storage = isolated_storage
    before = asset_ids()
    headers = bootstrap_headers()
    head = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="file"; filename="big.stl"\r\n'
        "Content-Type: model/stl\r\n\r\n"
    ).encode()
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": head + b"x" * 65536, "more_body": True}
        return {"type": "http.disconnect"}

    scope = asgi_scope(bearer_headers(headers, f"multipart/form-data; boundary={BOUNDARY}"))
    messages = asyncio.run(call_app(scope, receive))

    assert response_status(messages) < 500
    assert asset_ids() == before
    assert stored_files(storage) == []
    assert incoming_files(storage) == []


def test_oversized_stream_rejected_mid_flight_and_cleaned_up(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = isolated_storage
    before = asset_ids()
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 256 * 1024)
    headers = bootstrap_headers()
    head = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="file"; filename="big.stl"\r\n'
        "Content-Type: model/stl\r\n\r\n"
    ).encode()
    body = head + b"x" * (4 * 1024 * 1024) + f"\r\n--{BOUNDARY}--\r\n".encode()
    chunks = [body[index : index + 65536] for index in range(0, len(body), 65536)]
    consumed = 0
    index = 0

    async def receive() -> dict:
        nonlocal consumed, index
        if index >= len(chunks):
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = chunks[index]
        index += 1
        consumed += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": index < len(chunks)}

    scope = asgi_scope(bearer_headers(headers, f"multipart/form-data; boundary={BOUNDARY}"))
    messages = asyncio.run(call_app(scope, receive))

    assert response_status(messages) == 413
    # Stopped pulling the body once the cap was crossed, rather than buffering 4 MiB.
    assert consumed < len(body)
    assert asset_ids() == before
    assert stored_files(storage) == []
    assert incoming_files(storage) == []


def test_max_upload_mb_still_enforced_mid_stream(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = isolated_storage
    before = asset_ids()
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        response = client.post(
            "/upload",
            files={"file": ("big.stl", b"x" * 4096, "model/stl")},
            headers=headers,
        )
    assert response.status_code == 413, response.text
    assert response.json()["detail"] == "Upload exceeds the 10 bytes limit"
    assert asset_ids() == before
    assert stored_files(storage) == []
    assert incoming_files(storage) == []


def test_upload_never_spools_to_a_temp_file(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = isolated_storage
    payload = b"solid benchy\n" + b"x" * (3 * 1024 * 1024)

    def no_spool(*_args, **_kwargs):
        raise AssertionError("upload must not spool to a temporary file")

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", no_spool)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/upload",
            files={"file": ("benchy.stl", payload, "model/stl")},
            headers=auth_header(client),
        )
    assert response.status_code == 200, response.text
    destination = storage / response.json()["storage_path"]
    assert destination.read_bytes() == payload


def test_file_sink_writes_in_bounded_chunks(tmp_path: Path) -> None:
    """The writer slices a large chunk itself, so one write never blocks a worker for long."""

    class RecordingHandle:
        def __init__(self) -> None:
            self.sizes: List[int] = []
            self.content = bytearray()

        def write(self, piece: bytes) -> int:
            self.sizes.append(len(piece))
            self.content += piece
            return len(piece)

    sink = multipart_stream.FileSink(tmp_path / "written.bin")
    handle = RecordingHandle()
    sink._handle = handle  # stands in for the open file so the slices are observable
    payload = b"x" * (3 * multipart_stream.WRITE_CHUNK_SIZE + 7)

    sink.write(payload)

    assert handle.sizes == [multipart_stream.WRITE_CHUNK_SIZE] * 3 + [7]
    assert bytes(handle.content) == payload


def test_body_reaches_disk_while_it_is_still_streaming(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bytes land in the staging file during the replay, not in one copy at the end."""
    storage = isolated_storage
    payload = b"x" * (3 * 1024 * 1024)
    body = multipart_body([("file", "benchy.stl", "model/stl", payload)])
    chunks = [body[index : index + 256 * 1024] for index in range(0, len(body), 256 * 1024)]
    received: List[int] = []
    writes = record_sink_writes(monkeypatch, received)
    headers = bootstrap_headers()
    state = {"index": 0}

    async def receive() -> dict:
        if state["index"] >= len(chunks):
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = chunks[state["index"]]
        state["index"] += 1
        received.append(len(chunk))
        return {"type": "http.request", "body": chunk, "more_body": state["index"] < len(chunks)}

    scope = asgi_scope(bearer_headers(headers, f"multipart/form-data; boundary={BOUNDARY}"))
    messages = asyncio.run(call_app(scope, receive))

    assert response_status(messages) == 200
    assert sum(write.size for write in writes) == len(payload)
    assert min(write.received_before for write in writes) < len(chunks)
    stored = storage / response_json(messages)["storage_path"]
    assert stored.read_bytes() == payload


def test_upload_write_runs_off_the_event_loop(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loop_threads: List[str] = []
    real_new_staging_path = asset_service.new_staging_path

    def recording_new_staging_path() -> Path:
        loop_threads.append(threading.current_thread().name)
        return real_new_staging_path()

    monkeypatch.setattr(asset_service, "new_staging_path", recording_new_staging_path)
    writes = record_sink_writes(monkeypatch, [])
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/upload",
            files={"file": ("benchy.stl", b"solid benchy\n" + b"x" * (2 * 1024 * 1024), "model/stl")},
            headers=auth_header(client),
        )
    assert response.status_code == 200, response.text
    assert writes and loop_threads
    assert {write.thread for write in writes}.isdisjoint(loop_threads)


def test_stray_file_at_destination_is_not_deleted(isolated_storage: Path) -> None:
    storage = isolated_storage
    before = asset_ids()
    stray = storage / "Unassigned/cube/cube.stl"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"existing bytes")
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        assert client.post("/settings/storage", json={"template": "{folder}/{model}/{filename}"}, headers=headers).status_code == 200
        response = client.post(
            "/upload",
            files={"file": ("cube.stl", b"solid cube\n", "model/stl")},
            headers=headers,
        )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Storage path already exists: Unassigned/cube/cube.stl"
    assert stray.read_bytes() == b"existing bytes"
    assert asset_ids() == before
    assert incoming_files(storage) == []


def test_staging_dir_is_reserved_and_invisible_to_scans(isolated_storage: Path) -> None:
    storage = isolated_storage
    assert asset_service.STAGING_DIRNAME in library_scan.RESERVED_DIRS
    leaked = storage / asset_service.STAGING_DIRNAME / "leaked.stl"
    leaked.parent.mkdir(parents=True)
    leaked.write_bytes(b"solid leaked\n")

    status = library_scan.scan_storage_root()

    with Session(engine) as session:
        paths = {asset.storage_path for asset in session.exec(select(Asset))}
    assert leaked.relative_to(storage).as_posix() not in paths
    assert status.registered == 0
    assert leaked.exists()


def test_max_upload_bytes_zero_means_unlimited(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 0)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/upload",
            files={"file": ("unlimited.stl", b"x" * 4096, "model/stl")},
            headers=auth_header(client),
        )
    assert response.status_code == 200, response.text
    assert response.json()["size"] == 4096


def test_truncated_multipart_body_is_rejected(isolated_storage: Path) -> None:
    storage = isolated_storage
    before = asset_ids()
    head = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="file"; filename="truncated.stl"\r\n'
        "Content-Type: model/stl\r\n\r\n"
    ).encode()
    body = head + b"solid truncated\n"
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/upload",
            content=body,
            headers=multipart_headers(auth_header(client)),
        )
    assert 400 <= response.status_code < 500, response.text
    assert asset_ids() == before
    assert stored_files(storage) == []
    assert incoming_files(storage) == []


def test_non_ascii_filename_round_trips(isolated_storage: Path) -> None:
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/upload",
            files={"file": ("Benchy-å.stl", b"solid benchy\n", "model/stl")},
            headers=auth_header(client),
        )
    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "Benchy-å.stl"


def test_missing_file_part_is_422(isolated_storage: Path) -> None:
    storage = isolated_storage
    before = asset_ids()
    body = multipart_body([("title", None, None, b"no file here")])
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/upload",
            content=body,
            headers=multipart_headers(auth_header(client)),
        )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "file: field required"
    assert asset_ids() == before
    assert stored_files(storage) == []
    assert incoming_files(storage) == []


def test_over_cap_field_is_rejected(isolated_storage: Path) -> None:
    storage = isolated_storage
    before = asset_ids()
    body = multipart_body(
        [
            ("file", "field.stl", "model/stl", b"solid field\n"),
            ("notes", None, None, b"x" * (1024 * 1024 + 1)),
        ]
    )
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/upload",
            content=body,
            headers=multipart_headers(auth_header(client)),
        )
    assert response.status_code == 400, response.text
    assert asset_ids() == before
    assert stored_files(storage) == []
    assert incoming_files(storage) == []


def test_zero_byte_upload_succeeds(isolated_storage: Path) -> None:
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/upload",
            files={"file": ("empty.stl", b"", "model/stl")},
            headers=auth_header(client),
        )
    assert response.status_code == 200, response.text
    assert response.json()["size"] == 0


def test_upload_fields_after_file_part_are_applied(isolated_storage: Path) -> None:
    storage = isolated_storage
    payload = b"solid benchy\n"
    body = multipart_body(
        [
            ("file", "Benchy.stl", "model/stl", payload),
            ("title", None, None, b"My Model"),
            ("tags", None, None, b"alpha, beta"),
        ]
    )
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        template = client.post(
            "/settings/storage",
            json={"template": "{folder}/{model}/{tags}/{filename}"},
            headers=headers,
        )
        assert template.status_code == 200, template.text
        response = client.post("/upload", content=body, headers=multipart_headers(headers))
    assert response.status_code == 200, response.text
    asset_id = response.json()["id"]
    assert response.json()["storage_path"] == "Unassigned/My Model/alpha + beta/My Model.stl"
    assert (storage / response.json()["storage_path"]).read_bytes() == payload
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        assert asset.title == "My Model"
        assert asset.tags_json == '["alpha", "beta"]'


def test_upload_blocked_staging_write_leaves_no_orphan_row_or_file(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = isolated_storage
    before = asset_ids()

    def boom(_sink, _data):
        raise OSError("storage went away")

    monkeypatch.setattr(multipart_stream.FileSink, "write", boom)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/upload",
            files={"file": ("cube.stl", b"solid cube\n", "model/stl")},
            headers=auth_header(client),
        )
    assert response.status_code == 500, response.text
    assert asset_ids() == before
    assert stored_files(storage) == []
    assert incoming_files(storage) == []


def test_related_file_streams_off_the_event_loop_and_enforces_limit(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = isolated_storage
    loop_threads: List[str] = []
    real_new_staging_path = asset_service.new_staging_path

    def recording_new_staging_path() -> Path:
        loop_threads.append(threading.current_thread().name)
        return real_new_staging_path()

    def no_spool(*_args, **_kwargs):
        raise AssertionError("related file upload must not spool to a temporary file")

    monkeypatch.setattr(asset_service, "new_staging_path", recording_new_staging_path)
    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", no_spool)
    writes = record_sink_writes(monkeypatch, [])
    payload = b"supporting bytes\n" + b"y" * (2 * 1024 * 1024)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        created = client.post(
            "/upload",
            files={"file": ("cube.stl", b"solid cube\n", "model/stl")},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        asset_id = created.json()["id"]

        response = client.post(
            f"/asset/{asset_id}/files",
            files={"file": ("support.stl", payload, "model/stl")},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert writes and loop_threads
        assert {write.thread for write in writes}.isdisjoint(loop_threads)

        monkeypatch.setattr(main, "IMPORT_MAX_BYTES", 256 * 1024)
        oversized = client.post(
            f"/asset/{asset_id}/files",
            files={"file": ("too-big.stl", b"z" * (1024 * 1024), "model/stl")},
            headers=headers,
        )
        assert oversized.status_code == 413, oversized.text
        # The supporting-file cap is the tighter of IMPORT_MAX_BYTES and
        # ASSET_FILE_MAX_BYTES, and the message says which cap refused it.
        assert oversized.json()["detail"] == "Supporting file exceeds the 262144 bytes limit"

        supporting = client.get(f"/asset/{asset_id}/files", headers=headers).json()

    assert [row["filename"] for row in supporting] == ["support.stl"]
    assert not list(storage.rglob("too-big.stl"))
    assert incoming_files(storage) == []



def test_startup_sweep_removes_stale_staging_files(isolated_storage: Path) -> None:
    """A crash leaves a staging file behind; the next start removes it before serving."""
    storage = isolated_storage
    stale = storage / asset_service.STAGING_DIRNAME / "crashed-upload"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"half a model")

    with TestClient(main.app, raise_server_exceptions=False):
        pass

    assert not stale.exists()

def test_every_streaming_upload_endpoint_documents_a_binary_file_part() -> None:
    """Raw request parsing means FastAPI cannot derive the schema; it is declared instead."""
    paths = main.app.openapi()["paths"]
    for route in ("/upload", "/asset/{asset_id}/files", "/asset/{asset_id}/thumbnail-generated"):
        schema = paths[route]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
        assert schema["required"] == ["file"], route
        assert schema["properties"]["file"] == {"type": "string", "format": "binary"}, route


def created_asset_id(client: TestClient, headers: dict) -> str:
    """Create one asset through the regular upload route and return its id."""
    created = client.post(
        "/upload",
        files={"file": ("probe.stl", b"solid probe\n", "model/stl")},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def probe_payload() -> bytes:
    """About two megabytes of gcode-ish text, so the store is more than a memcpy."""
    return b"; probe print\n" + b"G1 X10 Y10 E1\n" * (2 * 1024 * 1024 // 14)


def test_asset_file_write_and_inspection_run_off_the_event_loop(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop_threads: List[str] = []
    move_threads: List[str] = []
    inspect_threads: List[str] = []
    real_new_staging_path = asset_service.new_staging_path
    real_move_managed_file = asset_service.move_managed_file
    real_inspect_prepared_print = asset_file_service.inspect_prepared_print

    def recording_new_staging_path() -> Path:
        loop_threads.append(threading.current_thread().name)
        return real_new_staging_path()

    def recording_move_managed_file(old_path: Path, new_path: Path) -> bool:
        move_threads.append(threading.current_thread().name)
        return real_move_managed_file(old_path, new_path)

    def recording_inspect_prepared_print(path: Path, filename: Optional[str] = None) -> Optional[dict]:
        inspect_threads.append(threading.current_thread().name)
        return real_inspect_prepared_print(path, filename)

    monkeypatch.setattr(asset_service, "new_staging_path", recording_new_staging_path)
    monkeypatch.setattr(asset_service, "move_managed_file", recording_move_managed_file)
    monkeypatch.setattr(asset_file_service, "inspect_prepared_print", recording_inspect_prepared_print)

    payload = probe_payload()
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        asset_id = created_asset_id(client, headers)
        response = client.post(
            f"/asset/{asset_id}/files",
            files={"file": ("PROBE.gcode.3mf", payload, "model/3mf")},
            headers=headers,
        )
    assert response.status_code == 200, response.text
    assert move_threads and inspect_threads
    assert set(move_threads).isdisjoint(loop_threads)
    assert set(inspect_threads).isdisjoint(loop_threads)


def test_health_answers_while_a_large_supporting_file_is_being_stored(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    finished = threading.Event()
    release = threading.Event()
    real_inspect_prepared_print = asset_file_service.inspect_prepared_print

    def blocking_inspect_prepared_print(path: Path, filename: Optional[str] = None) -> Optional[dict]:
        started.set()
        try:
            release.wait(timeout=2)
        finally:
            finished.set()
        return real_inspect_prepared_print(path, filename)

    monkeypatch.setattr(asset_file_service, "inspect_prepared_print", blocking_inspect_prepared_print)

    body = multipart_body([("file", "PROBE.gcode", "text/x-gcode", probe_payload())])
    content_type = f"multipart/form-data; boundary={BOUNDARY}"
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        asset_id = created_asset_id(client, headers)

    async def upload_task() -> List[dict]:
        scope = asgi_scope(bearer_headers(headers, content_type))
        scope["path"] = f"/asset/{asset_id}/files"
        scope["raw_path"] = scope["path"].encode()
        sent = {"done": False}

        async def receive() -> dict:
            if not sent["done"]:
                sent["done"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        return await call_app(scope, receive)

    async def health_task() -> List[dict]:
        scope = asgi_scope(bearer_headers(headers, "application/json"))
        scope["method"] = "GET"
        scope["path"] = "/health"
        scope["raw_path"] = b"/health"

        async def receive() -> dict:
            return {"type": "http.disconnect"}

        return await call_app(scope, receive)

    async def scenario() -> Tuple[int, int, bool]:
        upload = asyncio.ensure_future(upload_task())
        try:
            # Bounded wait: a broken upload must fail the test, not hang it.
            while not started.is_set() and not upload.done():
                await asyncio.sleep(0.01)
            health_messages = await asyncio.wait_for(health_task(), timeout=10)
            answered_before_release = not finished.is_set() and not upload.done()
        finally:
            release.set()
        upload_messages = await asyncio.wait_for(upload, timeout=10)
        return response_status(health_messages), response_status(upload_messages), answered_before_release

    health_status, upload_status, answered_before_release = asyncio.run(
        asyncio.wait_for(scenario(), timeout=30)
    )

    assert upload_status == 200
    assert health_status == 200
    assert answered_before_release is True


def test_prepared_inspection_failure_keeps_the_stored_file(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def exploding_inspect_prepared_print(path: Path, filename: Optional[str] = None) -> Optional[dict]:
        raise RuntimeError("inspection exploded")

    monkeypatch.setattr(asset_file_service, "inspect_prepared_print", exploding_inspect_prepared_print)
    payload = b"; probe print\nG1 X0 Y0 E1\n" + b"G1 X10 Y10 E1\n" * 500
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        asset_id = created_asset_id(client, headers)
        with caplog.at_level(logging.WARNING):
            response = client.post(
                f"/asset/{asset_id}/files",
                files={"file": ("PROBE.gcode", payload, "text/x-gcode")},
                headers=headers,
            )
        assert response.status_code == 200, response.text
        download = client.get(f"/asset/{asset_id}/prepared-print", headers=headers)

    assert download.status_code == 200
    assert download.content == payload

    with Session(engine) as session:
        rows = list(session.exec(select(AssetFile).where(AssetFile.asset_id == asset_id)))
        assert len(rows) == 1
        row = rows[0]
        stored = asset_file_service.managed_asset_file_path(row)
        assert row.role == "prepared"
        assert row.size == len(payload)
        assert stored.exists()
        assert stored.read_bytes() == payload
        asset = session.get(Asset, asset_id)
        assert asset is not None
        assert asset.prepared_file_id == row.id
        assert json.loads(asset.prepared_metadata_json) == {
            "printer": None,
            "material": None,
            "nozzle_mm": None,
            "layer_height_mm": None,
            "estimated_seconds": None,
            "slicer": "unknown",
            "format": "gcode",
        }
    assert incoming_files(isolated_storage) == []
    assert any("inspection failed" in record.getMessage() for record in caplog.records)


def test_inspection_failure_on_a_plain_3mf_still_stores_it(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def exploding_inspect_prepared_print(path: Path, filename: Optional[str] = None) -> Optional[dict]:
        raise RuntimeError("inspection exploded")

    monkeypatch.setattr(asset_file_service, "inspect_prepared_print", exploding_inspect_prepared_print)
    payload = b"PK\x03\x04 not really a zip\n" + b"x" * 1024
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        asset_id = created_asset_id(client, headers)
        response = client.post(
            f"/asset/{asset_id}/files",
            files={"file": ("model.3mf", payload, "model/3mf")},
            headers=headers,
        )

    assert response.status_code == 200, response.text

    with Session(engine) as session:
        rows = list(session.exec(select(AssetFile).where(AssetFile.asset_id == asset_id)))
        assert len(rows) == 1
        row = rows[0]
        stored = asset_file_service.managed_asset_file_path(row)
        assert row.role == "supporting"
        assert stored.exists()
        assert stored.read_bytes() == payload
        asset = session.get(Asset, asset_id)
        assert asset is not None
        assert asset.supporting_file_count == 1
    assert incoming_files(isolated_storage) == []


def test_generated_thumbnail_streams_into_storage_without_spooling(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real PNG is decoded from the staging file, so the body never reaches a temp file."""
    storage = isolated_storage

    def no_spool(*_args, **_kwargs):
        raise AssertionError("generated thumbnail must not spool to a temporary file")

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", no_spool)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        asset_id = created_asset_id(client, headers)
        response = client.post(
            f"/asset/{asset_id}/thumbnail-generated",
            files={"file": ("thumb.png", png_bytes(), "image/png")},
            headers=headers,
        )

    assert response.status_code == 200, response.text
    assert (storage / "thumbs" / f"{asset_id}.jpg").exists()
    assert incoming_files(storage) == []


def test_generated_thumbnail_cap_is_enforced_mid_stream(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap trips while the body arrives, not after it has been buffered."""
    storage = isolated_storage
    monkeypatch.setattr(asset_files, "GENERATED_THUMBNAIL_MAX_BYTES", 256 * 1024)
    headers = bootstrap_headers()
    with TestClient(main.app, raise_server_exceptions=False) as client:
        asset_id = created_asset_id(client, auth_header(client))
    body = multipart_body([("file", "thumb.png", "image/png", b"x" * (4 * 1024 * 1024))])

    messages, consumed = post_raw(f"/asset/{asset_id}/thumbnail-generated", body, headers)

    assert response_status(messages) == 413
    assert response_json(messages)["detail"] == "Generated thumbnail exceeds 8 MB"
    # Stopped pulling the body once the cap was crossed, rather than buffering 4 MiB.
    assert consumed < len(body) // 4, consumed
    assert incoming_files(storage) == []
    assert list((storage / "thumbs").iterdir()) == []


def test_generated_thumbnail_rejects_other_content_types_mid_stream(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Content-Type gate runs at the part headers, so the bytes are never staged."""
    storage = isolated_storage
    headers = bootstrap_headers()
    with TestClient(main.app, raise_server_exceptions=False) as client:
        asset_id = created_asset_id(client, auth_header(client))
    body = multipart_body([("file", "thumb.zip", "application/zip", b"PK\x03\x04" + b"x" * (4 * 1024 * 1024))])

    messages, consumed = post_raw(f"/asset/{asset_id}/thumbnail-generated", body, headers)

    assert response_status(messages) == 415
    assert response_json(messages)["detail"] == "Generated thumbnail must be PNG, JPEG, or WebP"
    # The verdict came from the part headers alone: only the first chunk was pulled.
    assert consumed <= 64 * 1024, consumed
    assert incoming_files(storage) == []
    assert list((storage / "thumbs").iterdir()) == []


def test_generated_thumbnail_rejects_undecodable_bytes(isolated_storage: Path) -> None:
    """Bytes that pass the content-type gate still have to decode as an image."""
    storage = isolated_storage
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth_header(client)
        asset_id = created_asset_id(client, headers)
        response = client.post(
            f"/asset/{asset_id}/thumbnail-generated",
            files={"file": ("thumb.png", b"not an image at all", "image/png")},
            headers=headers,
        )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Invalid thumbnail image"
    assert incoming_files(storage) == []
    assert list((storage / "thumbs").iterdir()) == []


def test_generated_thumbnail_checks_the_body_before_the_asset(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stream and its cap decide first; a missing row is only looked up afterwards."""
    storage = isolated_storage
    monkeypatch.setattr(asset_files, "GENERATED_THUMBNAIL_MAX_BYTES", 256 * 1024)
    headers = bootstrap_headers()
    oversized = multipart_body([("file", "thumb.png", "image/png", b"x" * (4 * 1024 * 1024))])

    messages, _consumed = post_raw("/asset/does-not-exist/thumbnail-generated", oversized, headers)
    assert response_status(messages) == 413
    assert response_json(messages)["detail"] == "Generated thumbnail exceeds 8 MB"

    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/asset/does-not-exist/thumbnail-generated",
            files={"file": ("thumb.png", png_bytes(), "image/png")},
            headers=auth_header(client),
        )
    assert response.status_code == 404, response.text
    assert incoming_files(storage) == []
    assert list((storage / "thumbs").iterdir()) == []


def test_generated_thumbnail_default_cap_boundary(isolated_storage: Path) -> None:
    """Eight MiB is accepted and then rejected as an image; one byte more is refused by the cap."""
    storage = isolated_storage
    headers = bootstrap_headers()
    with TestClient(main.app, raise_server_exceptions=False) as client:
        asset_id = created_asset_id(client, auth_header(client))
    limit = 8 * 1024 * 1024
    path = f"/asset/{asset_id}/thumbnail-generated"

    at_cap = multipart_body([("file", "thumb.png", "image/png", b"x" * limit)])
    messages, _consumed = post_raw(path, at_cap, headers)
    assert response_status(messages) == 400
    assert response_json(messages)["detail"] == "Invalid thumbnail image"

    over_cap = multipart_body([("file", "thumb.png", "image/png", b"x" * (limit + 1))])
    messages, _consumed = post_raw(path, over_cap, headers)
    assert response_status(messages) == 413
    assert response_json(messages)["detail"] == "Generated thumbnail exceeds 8 MB"

    assert incoming_files(storage) == []
    assert list((storage / "thumbs").iterdir()) == []
