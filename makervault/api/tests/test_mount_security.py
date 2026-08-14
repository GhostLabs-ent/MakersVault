import os

import pytest

from mount_import import open_safe_mount_file, resolve_safe_mount_file


def test_regular_mounted_file_is_opened_beneath_root(tmp_path) -> None:
    root = tmp_path / "mount"
    root.mkdir()
    source = root / "model.stl"
    source.write_bytes(b"solid model")

    assert resolve_safe_mount_file(root, source) == source.resolve()
    with open_safe_mount_file(root, source) as (handle, size, opened_path):
        assert handle.read() == b"solid model"
        assert size == len(b"solid model")
        assert opened_path == source.resolve()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_mounted_symlinks_are_rejected_inside_and_outside_root(tmp_path) -> None:
    root = tmp_path / "mount"
    root.mkdir()
    inside = root / "inside.stl"
    inside.write_bytes(b"inside")
    outside = tmp_path / "outside.stl"
    outside.write_bytes(b"outside")
    inside_link = root / "inside-link.stl"
    outside_link = root / "outside-link.stl"
    inside_link.symlink_to(inside)
    outside_link.symlink_to(outside)

    with pytest.raises(ValueError, match="symbolic link"):
        resolve_safe_mount_file(root, inside_link)
    with pytest.raises(ValueError, match="symbolic link"):
        resolve_safe_mount_file(root, outside_link)
