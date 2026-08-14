import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

import resource_limits
from config import env_limit_int


def test_limit_configuration_rejects_invalid_values(monkeypatch) -> None:
    monkeypatch.setenv("TEST_RESOURCE_LIMIT", "0")
    with pytest.raises(RuntimeError, match="must be at least 1"):
        env_limit_int("TEST_RESOURCE_LIMIT", 10)

    monkeypatch.setenv("TEST_RESOURCE_LIMIT", "many")
    with pytest.raises(RuntimeError, match="must be an integer"):
        env_limit_int("TEST_RESOURCE_LIMIT", 10)


def test_storage_reserve_configuration_allows_zero(monkeypatch) -> None:
    monkeypatch.setenv("TEST_STORAGE_RESERVE", "0")
    assert env_limit_int("TEST_STORAGE_RESERVE", 512, minimum=0) == 0


def test_stream_upload_rejects_and_removes_partial_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(resource_limits, "ensure_storage_reserve", lambda *_args, **_kwargs: None)
    destination = tmp_path / "partial.bin"
    upload = UploadFile(filename="large.bin", file=io.BytesIO(b"12345"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            resource_limits.stream_upload_to_file(
                upload,
                destination,
                "Uploaded file",
                max_bytes=4,
            )
        )

    assert exc.value.status_code == 413
    assert not destination.exists()


def test_storage_reserve_returns_507(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(resource_limits, "STORAGE_RESERVE_BYTES", 512)
    monkeypatch.setattr(
        resource_limits.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=1000, used=600, free=400),
    )

    with pytest.raises(HTTPException) as exc:
        resource_limits.ensure_storage_reserve(tmp_path / "file.bin")

    assert exc.value.status_code == 507


def test_stream_reader_preserves_unlimited_batch_distinction(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(resource_limits, "ensure_storage_reserve", lambda *_args, **_kwargs: None)

    for index in range(25):
        destination = tmp_path / f"file-{index}.bin"
        size = resource_limits.stream_reader_to_file(
            io.BytesIO(b"data"),
            destination,
            "Uploaded file",
            max_bytes=4,
        )
        assert size == 4

    assert len(list(tmp_path.iterdir())) == 25
