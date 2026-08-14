import io
import warnings
from zipfile import ZipFile, ZipInfo

import pytest
from fastapi import HTTPException
from PIL import Image

import archive_limits
from asset_service import save_thumb_bytes
from zip_service import list_zip_entries, normalize_zip_entry_path


def zip_info(name: str, size: int, compressed: int) -> ZipInfo:
    info = ZipInfo(name)
    info.file_size = size
    info.compress_size = compressed
    return info


def test_archive_selected_expansion_and_count_are_bounded(monkeypatch) -> None:
    infos = [zip_info("one.stl", 4, 4), zip_info("two.stl", 4, 4)]
    monkeypatch.setattr(archive_limits, "ARCHIVE_MAX_SELECTED", 1)
    with pytest.raises(archive_limits.ArchiveLimitError, match="Select no more"):
        archive_limits.validate_selected_members(infos)

    monkeypatch.setattr(archive_limits, "ARCHIVE_MAX_SELECTED", 10)
    monkeypatch.setattr(archive_limits, "ARCHIVE_MAX_EXPANDED_BYTES", 7)
    with pytest.raises(archive_limits.ArchiveLimitError, match="expansion limit"):
        archive_limits.validate_selected_members(infos)


def test_archive_member_scan_count_is_bounded(monkeypatch) -> None:
    class FakeArchive:
        def infolist(self):
            return [zip_info("one.stl", 1, 1), zip_info("two.stl", 1, 1)]

    monkeypatch.setattr(archive_limits, "ARCHIVE_MAX_ENTRIES", 1)
    with pytest.raises(archive_limits.ArchiveLimitError, match="more than"):
        archive_limits.bounded_archive_infos(FakeArchive())

def test_extreme_compression_ratio_is_rejected() -> None:
    info = zip_info("bomb.stl", 10_000, 1)

    with pytest.raises(archive_limits.ArchiveLimitError, match="compression ratio"):
        archive_limits.validate_archive_member(info)


def test_zip_listing_rejects_normalized_duplicate_paths(tmp_path) -> None:
    archive_path = tmp_path / "duplicates.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with ZipFile(archive_path, "w") as archive:
            archive.writestr("models/part.stl", b"one")
            archive.writestr("models\\part.stl", b"two")

    with pytest.raises(HTTPException) as exc:
        list_zip_entries(archive_path)

    assert exc.value.status_code == 400


def test_zip_path_normalization_rejects_traversal() -> None:
    assert normalize_zip_entry_path("../../outside.stl") is None
    assert normalize_zip_entry_path("/safe/model.stl") == "safe/model.stl"
    assert normalize_zip_entry_path("safe\\model.stl") == "safe/model.stl"


def test_decoded_image_pixel_budget_fails_thumbnail(tmp_path, monkeypatch) -> None:
    source = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(source, format="PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 4)

    assert save_thumb_bytes("pixel-budget", source.getvalue()) is None
