"""Pillow thumbnail contract, pinned across the 10.4 -> 12.3 bump (Mf-xzei).

``asset_service`` is the only runtime PIL importer, and its three thumbnail
entry points (``save_thumb_image``, ``save_thumb_bytes``, ``extract_3mf_thumbnail``
via ``ensure_model_thumbnail``) were previously exercised only indirectly. This
module pins their *contract*: the URL string they return, the JPEG/mode/size of
the file they write, the flatten-onto-canvas behaviour for alpha input, the
"never upscale" bound, the error path that must not leave debris, and the
3MF-embedded-thumbnail success path.

It deliberately asserts invariants only - no image hashes, no byte lengths, no
exact JPEG bytes. Byte-identity between Pillow releases is an artefact of the
wheel that shipped libjpeg/zlib, not of this code, so an identical-bytes
assertion would fail on the very bump this file is meant to gate.

``THUMBS`` is bound into ``asset_service`` by ``from db import ... THUMBS`` at
import time, so every test rebinds it on the module and creates the directory:
``save_thumb_image`` never mkdirs it, and the resulting ``FileNotFoundError``
would be swallowed by its blanket ``except`` and show up as a silent ``None``.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import asset_service

# The canvas colour ``save_thumb_image`` composites alpha onto.
CANVAS = (248, 250, 252)
# A strongly non-canvas red, so a corner that kept its source colour is obvious.
SOURCE_RED = (200, 30, 30)
# JPEG quality 88 is lossy. Measured on Pillow 10.4.0 the flat canvas decodes as
# (249, 250, 252) - one LSB off in the red channel - so +/-4 per channel is the
# tightest tolerance that reliably passes without being kernel-version specific.
CHANNEL_TOLERANCE = 4


@pytest.fixture()
def thumbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Rebind ``asset_service.THUMBS`` to a real, existing directory."""
    directory = tmp_path / "thumbs"
    directory.mkdir(parents=True)
    monkeypatch.setattr(asset_service, "THUMBS", directory)
    return directory


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def assert_corner_is_canvas(path: Path) -> None:
    with Image.open(path) as written:
        written.load()
        assert written.format == "JPEG"
        assert written.mode == "RGB"
        corner = written.getpixel((0, 0))
    for actual, expected in zip(corner, CANVAS, strict=True):
        assert abs(actual - expected) <= CHANNEL_TOLERANCE, f"corner {corner} is not the {CANVAS} canvas"
    # Decisively not the source colour: at least one channel is far from it.
    assert max(abs(actual - source) for actual, source in zip(corner, SOURCE_RED, strict=True)) > 40, (
        f"corner {corner} still looks like the un-flattened source {SOURCE_RED}"
    )


def test_save_thumb_image_downscales_to_512_long_edge(thumbs: Path) -> None:
    asset_id = "asset-downscale"
    source = Image.new("RGB", (900, 700), (60, 120, 180))

    url = asset_service.save_thumb_image(asset_id, source)

    assert url == f"/thumb/{asset_id}.jpg"
    written = thumbs / f"{asset_id}.jpg"
    assert written.is_file()
    with Image.open(written) as thumb:
        assert thumb.format == "JPEG"
        assert thumb.mode == "RGB"
        # Aspect preserved: 700 * 512 / 900 rounds to 398.
        assert thumb.size == (512, 398)


def test_save_thumb_image_never_upscales(thumbs: Path) -> None:
    asset_id = "asset-tiny"
    url = asset_service.save_thumb_image(asset_id, Image.new("RGB", (2, 2), (10, 200, 30)))

    assert url == f"/thumb/{asset_id}.jpg"
    with Image.open(thumbs / f"{asset_id}.jpg") as thumb:
        assert thumb.size == (2, 2)


def test_save_thumb_image_flattens_rgba_onto_canvas(thumbs: Path) -> None:
    asset_id = "asset-rgba"
    source = Image.new("RGBA", (600, 400), (*SOURCE_RED, 0))

    url = asset_service.save_thumb_image(asset_id, source)

    assert url == f"/thumb/{asset_id}.jpg"
    assert_corner_is_canvas(thumbs / f"{asset_id}.jpg")


def test_save_thumb_image_flattens_palette_transparency_onto_canvas(thumbs: Path) -> None:
    asset_id = "asset-palette"
    source = Image.new("P", (600, 400), 0)
    palette = list(SOURCE_RED) + [0, 0, 0] * 255
    source.putpalette(palette)
    source.info["transparency"] = 0
    data = png_bytes(source)

    # The transparency must survive the PNG round trip, otherwise the flatten
    # branch would never be reached and the assertion would be vacuous.
    with Image.open(io.BytesIO(data)) as reopened:
        assert reopened.mode == "P"
        assert "transparency" in reopened.info
        url = asset_service.save_thumb_image(asset_id, reopened)

    assert url == f"/thumb/{asset_id}.jpg"
    assert_corner_is_canvas(thumbs / f"{asset_id}.jpg")


def test_save_thumb_bytes_rejects_garbage_without_leaving_files(thumbs: Path) -> None:
    asset_id = "asset-garbage"

    assert asset_service.save_thumb_bytes(asset_id, b"not an image") is None
    assert not (thumbs / f"{asset_id}.jpg").exists()
    assert list(thumbs.iterdir()) == []


def test_ensure_model_thumbnail_extracts_embedded_3mf_thumbnail(thumbs: Path, tmp_path: Path) -> None:
    asset_id = "asset-3mf"
    model = tmp_path / "model.3mf"
    embedded = png_bytes(Image.new("RGBA", (700, 700), (*SOURCE_RED, 0)))
    with zipfile.ZipFile(model, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata/thumbnail.png", embedded)

    url = asset_service.ensure_model_thumbnail(asset_id, model)

    assert url == f"/thumb/{asset_id}.jpg"
    written = thumbs / f"{asset_id}.jpg"
    assert written.is_file()
    with Image.open(written) as thumb:
        assert thumb.format == "JPEG"
        assert max(thumb.size) <= 512


def test_ensure_model_thumbnail_prefers_existing_file_over_source(thumbs: Path, tmp_path: Path) -> None:
    asset_id = "asset-existing"
    existing = thumbs / f"{asset_id}.jpg"
    Image.new("RGB", (8, 8), (12, 34, 56)).save(existing, format="JPEG")
    before = existing.read_bytes()

    url = asset_service.ensure_model_thumbnail(asset_id, tmp_path / "does-not-exist.3mf")

    assert url == f"/thumb/{asset_id}.jpg"
    assert existing.read_bytes() == before
