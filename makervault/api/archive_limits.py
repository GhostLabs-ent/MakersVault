from typing import Iterable
from zipfile import ZipFile, ZipInfo

from config import (
    ARCHIVE_MAX_ENTRIES,
    ARCHIVE_MAX_EXPANDED_BYTES,
    ARCHIVE_MAX_RATIO,
    ARCHIVE_MAX_SELECTED,
    FILE_MAX_BYTES,
)


class ArchiveLimitError(ValueError):
    pass


def bounded_archive_infos(archive: ZipFile) -> list[ZipInfo]:
    infos = archive.infolist()
    if len(infos) > ARCHIVE_MAX_ENTRIES:
        raise ArchiveLimitError(
            f"Archive contains more than {ARCHIVE_MAX_ENTRIES} entries"
        )
    return infos


def compression_ratio(info: ZipInfo) -> float:
    if info.file_size <= 0:
        return 0.0
    if info.compress_size <= 0:
        return float("inf")
    return info.file_size / info.compress_size


def validate_archive_member(info: ZipInfo, *, enforce_file_size: bool = True) -> None:
    if enforce_file_size and info.file_size > FILE_MAX_BYTES:
        raise ArchiveLimitError(f"Archive entry exceeds the per-file size limit: {info.filename}")
    if compression_ratio(info) > ARCHIVE_MAX_RATIO:
        raise ArchiveLimitError(f"Archive entry has an extreme compression ratio: {info.filename}")


def validate_selected_members(infos: Iterable[ZipInfo]) -> list[ZipInfo]:
    selected = list(infos)
    if len(selected) > ARCHIVE_MAX_SELECTED:
        raise ArchiveLimitError(
            f"Select no more than {ARCHIVE_MAX_SELECTED} archive entries at once"
        )
    expanded = 0
    for info in selected:
        expanded += max(0, info.file_size)
        if expanded > ARCHIVE_MAX_EXPANDED_BYTES:
            raise ArchiveLimitError("Selected archive entries exceed the expansion limit")
    return selected
