"""Tiny archive fixtures only: prove rejection before opening/decompressing bytes."""
import io
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient
from PIL import Image
import pytest

import archive_limits
import asset_service
import main
from prepared_print import inspect_prepared_print


SUPPORTED = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
UNSUPPORTED = (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA)
MODEL = b"cube([1, 2, 3]);\n"
SETTINGS = b'; printer_model = P1S\n; filament_type = PLA\n; nozzle_diameter = 0.4\n'


def make_archive(path, members, *, zip64=False):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data, method in members:
            info = zipfile.ZipInfo(name)
            info.compress_type = method
            with archive.open(info, "w", force_zip64=zip64) as output:
                output.write(data)
    return path


@pytest.fixture
def guarded_reads(monkeypatch):
    """A regression cannot consume unsupported data even if an outer catch hides it."""
    forbidden = []
    real_open = zipfile.ZipFile.open
    real_decompressor = zipfile._get_decompressor

    def observed_open(archive, name, mode="r", *args, **kwargs):
        if mode == "r":
            info = name if isinstance(name, zipfile.ZipInfo) else archive.getinfo(name)
            if info.compress_type not in SUPPORTED:
                forbidden.append(("open", info.compress_type))
                raise AssertionError("Unsupported member reached ZipFile.open")
        return real_open(archive, name, mode, *args, **kwargs)

    def observed_decompressor(method):
        if method not in SUPPORTED:
            forbidden.append(("decompressor", method))
            raise AssertionError("Unsupported ZIP decompressor initialized")
        return real_decompressor(method)

    monkeypatch.setattr(zipfile.ZipFile, "open", observed_open)
    monkeypatch.setattr(zipfile, "_get_decompressor", observed_decompressor)
    yield forbidden
    assert forbidden == []


@pytest.fixture
def api_session():
    with TestClient(main.app) as client:
        login = client.post("/login", json={"username": "admin", "password": "test-only-password"})
        assert login.status_code == 200
        yield client, {"Origin": "http://testserver", "X-CSRF-Token": login.json()["csrf_token"]}


@pytest.mark.parametrize("method", [12, 14, 20, 93, 99, 65535])
@pytest.mark.parametrize("enforce_size", [False, True])
def test_method_guard_is_independent_of_size_and_ratio(method, enforce_size):
    info = zipfile.ZipInfo("tiny.scad")
    info.file_size = info.compress_size = 1
    info.compress_type = method
    with pytest.raises(archive_limits.UnsupportedArchiveCompression, match="Stored.*Deflate"):
        archive_limits.validate_archive_member(info, enforce_file_size=enforce_size)


@pytest.mark.parametrize("method", UNSUPPORTED)
@pytest.mark.parametrize("endpoint", ["/import/zip/entries", "/import/zip"])
def test_direct_api_rejects_mixed_archive_before_any_import(
    tmp_path, monkeypatch, guarded_reads, api_session, method, endpoint,
):
    path = make_archive(tmp_path / "mixed.zip", [
        ("new-folder/first.scad", MODEL, zipfile.ZIP_DEFLATED),
        ("new-folder/unsupported.scad", MODEL, method),
    ])
    monkeypatch.setattr(main, "download_import_to_temp", lambda *_: (path, path.name, "application/zip"))
    # Any partial write/record/folder creation fails, even for the allowed member.
    def no_mutation(*_args, **_kwargs):
        pytest.fail("Archive validation allowed a partial import")

    import zip_service
    monkeypatch.setattr(zip_service, "create_asset_record", no_mutation)
    monkeypatch.setattr(zip_service, "resolve_zip_folder_id", no_mutation)
    client, headers = api_session
    before_assets = client.get("/assets", headers=headers).json()
    before_folders = client.get("/folders", headers=headers).json()
    response = client.post(endpoint, headers=headers, json={
        "url": "https://example.com/mixed.zip",
        "entries": ["new-folder/first.scad", "new-folder/unsupported.scad"],
    })
    assert response.status_code == 400
    assert "Unsupported ZIP compression" in response.json()["detail"]
    assert "Stored (no compression) or Deflate" in response.json()["detail"]
    assert client.get("/assets", headers=headers).json() == before_assets
    assert client.get("/folders", headers=headers).json() == before_folders
    assert not path.exists()  # Downloaded temporary copy is still cleaned up.


@pytest.mark.parametrize("method", SUPPORTED)
@pytest.mark.parametrize("zip64", [False, True])
def test_api_accepts_supported_methods_including_zip64(tmp_path, monkeypatch, guarded_reads, api_session, method, zip64):
    name = f"allowed-{uuid4().hex}.scad"
    path = make_archive(tmp_path / "allowed.zip", [(name, MODEL, method)], zip64=zip64)
    original = path.read_bytes()
    if zip64:
        assert int.from_bytes(original[18:22], "little") == 0xffffffff
    monkeypatch.setattr(main, "download_import_to_temp", lambda *_: (path, path.name, "application/zip"))
    client, headers = api_session
    listed = client.post("/import/zip/entries", headers=headers, json={"url": "https://example.com/allowed.zip"})
    assert listed.status_code == 200
    assert listed.json()["entries"] == [{"path": name, "size": len(MODEL)}]
    path.write_bytes(original)  # Simulate the next independent, downloaded copy.
    imported = client.post("/import/zip", headers=headers, json={"url": "https://example.com/allowed.zip", "entries": [name]})
    assert imported.status_code == 200
    result = imported.json()
    try:
        assert result["failed"] == []
        assert len(result["assets"]) == 1
        assert client.get(result["assets"][0]["url"], headers=headers).content == MODEL
    finally:
        for asset in result["assets"]:
            asset_service.cleanup_asset(asset["id"])


@pytest.mark.parametrize("method", UNSUPPORTED)
@pytest.mark.parametrize("entry", ["Metadata/settings.json", "Metadata/slice.config", "Metadata/plate.gcode"])
def test_prepared_inspection_keeps_role_without_parsing_unsupported_members(tmp_path, guarded_reads, method, entry):
    members = [(entry, SETTINGS, method)]
    if not entry.endswith(".gcode"):
        members.append(("Metadata/plate.gcode", SETTINGS, zipfile.ZIP_STORED))
    path = make_archive(tmp_path / "plate.3mf", members)
    original = path.read_bytes()
    result = inspect_prepared_print(path)
    assert result["format"] == "gcode_3mf"
    assert all(value is None for key, value in result.items() if key != "format")
    assert path.read_bytes() == original


@pytest.mark.parametrize("method", UNSUPPORTED)
@pytest.mark.parametrize("by_path", [False, True])
def test_thumbnail_inspection_skips_unsupported_member(tmp_path, guarded_reads, method, by_path):
    path = make_archive(tmp_path / "thumbnail.3mf", [("Metadata/thumbnail.png", b"not decoded", method)])
    original = path.read_bytes()
    if by_path:
        result = asset_service.extract_3mf_thumbnail_path("unused/thumbnail.jpg", path)
    else:
        result = asset_service.extract_3mf_thumbnail("unused-thumbnail-id", path)
    assert result is None
    assert path.read_bytes() == original


@pytest.mark.parametrize("method", SUPPORTED)
@pytest.mark.parametrize("zip64", [False, True])
def test_supported_3mf_metadata_and_both_thumbnail_paths(tmp_path, monkeypatch, guarded_reads, method, zip64):
    png = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(png, format="PNG")
    path = make_archive(tmp_path / "plate.3mf", [
        ("Metadata/thumbnail.png", png.getvalue(), method),
        ("Metadata/plate.gcode", SETTINGS, method),
    ], zip64=zip64)
    saved = []
    def save(_key, content):
        saved.append(content)
        return "/fixture-thumbnail.jpg"
    monkeypatch.setattr(asset_service, "save_thumb_bytes", save)
    monkeypatch.setattr(asset_service, "save_thumb_bytes_path", save)
    assert asset_service.extract_3mf_thumbnail("fixture", path) == "/fixture-thumbnail.jpg"
    assert asset_service.extract_3mf_thumbnail_path("fixture/path", path) == "/fixture-thumbnail.jpg"
    assert saved == [png.getvalue(), png.getvalue()]
    assert inspect_prepared_print(path)["printer"] == "Bambu Lab P1S"


@pytest.mark.parametrize("method", UNSUPPORTED)
@pytest.mark.parametrize("attached", [False, True])
def test_unsupported_3mf_preserves_original_download_and_slicer_handoff(
    tmp_path, guarded_reads, api_session, method, attached,
):
    # Include a recognized thumbnail and prepared payload; neither may be opened.
    path = make_archive(tmp_path / "plate.3mf", [
        ("Metadata/thumbnail.png", b"not decoded", method),
        ("Metadata/plate.gcode", SETTINGS, method),
    ])
    original = path.read_bytes()
    client, headers = api_session
    filename = f"plate-{uuid4().hex}.3mf"
    upload = client.post("/upload", headers=headers, files={
        "file": ("primary.scad" if attached else filename, MODEL if attached else original, "application/octet-stream"),
    })
    assert upload.status_code == 200
    asset = upload.json()
    try:
        if attached:
            uploaded = client.post(f"/asset/{asset['id']}/files", headers=headers, files={"file": (filename, original, "model/3mf")})
            assert uploaded.status_code == 200
            asset = uploaded.json()
            assert client.get(f"/asset/{asset['id']}/files", headers=headers).json() == []
            download = client.get(f"/asset/{asset['id']}/prepared-print", headers=headers)
        else:
            assert asset["thumb_url"] is None
            download = client.get(asset["url"], headers=headers)
        assert asset["prepared_print"]["format"] == "gcode_3mf"
        assert asset["prepared_print"]["printer"] is None
        assert download.status_code == 200 and download.content == original
        grant = client.post(f"/asset/{asset['id']}/handoff", headers=headers, json={"tool": "slicer"})
        assert grant.status_code == 200
        handoff = grant.json()
        assert handoff["filename"].endswith(".3mf")
        redeemed = client.get(handoff["redeem_url"], headers={
            "Authorization": f"MakerVault-Handoff {handoff['grant']}",
            "X-MakerVault-Handoff-Tool": "slicer",
        })
        assert redeemed.status_code == 200 and redeemed.content == original
    finally:
        asset_service.cleanup_asset(asset["id"])
