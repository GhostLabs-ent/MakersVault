"""Capability-explicit content storage contract and local filesystem adapter."""

from __future__ import annotations

import os
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator, Protocol, runtime_checkable


class ContentStoreError(RuntimeError):
    pass


class InvalidStoreKey(ContentStoreError):
    pass


class ContentAlreadyExists(ContentStoreError):
    pass


@dataclass(frozen=True)
class StoreCapabilities:
    streaming_read: bool
    staged_write: bool
    atomic_publish: bool
    create_if_absent: bool
    local_materialization: bool
    capacity_admission: bool
    bounded_enumeration: bool
    reversible_delete: bool


@dataclass(frozen=True)
class StoreStat:
    key: str
    size: int
    modified_ns: int


@dataclass(frozen=True)
class Capacity:
    total: int
    used: int
    free: int


@dataclass(frozen=True)
class DeleteMove:
    key: str
    quarantine_key: str


@dataclass(frozen=True)
class DeleteTicket:
    operation_id: str
    moves: tuple[DeleteMove, ...]


@runtime_checkable
class ContentStore(Protocol):
    @property
    def capabilities(self) -> StoreCapabilities: ...

    def open_read(self, key: str) -> BinaryIO: ...

    def stat(self, key: str) -> StoreStat | None: ...

    def exists(self, key: str) -> bool: ...

    def publish(self, staged: Path, key: str, *, overwrite: bool = False) -> StoreStat: ...

    def iter_key_batches(self, prefix: str = "", *, batch_size: int = 1000) -> Iterator[list[str]]: ...

    def capacity(self, key: str | None = None) -> Capacity: ...

    def prepare_delete(self, keys: list[str], operation_id: str | None = None) -> DeleteTicket: ...

    def rollback_delete(self, ticket: DeleteTicket) -> None: ...

    def commit_delete(self, ticket: DeleteTicket) -> None: ...

    @contextmanager
    def materialize(self, key: str) -> Iterator[Path]: ...


def normalize_store_key(key: str, *, allow_empty: bool = False) -> str:
    if not isinstance(key, str):
        raise InvalidStoreKey("content key must be a string")
    if key == "" and allow_empty:
        return ""
    if not key or "\\" in key or "\x00" in key or key.startswith("/"):
        raise InvalidStoreKey("content key must be a non-empty relative POSIX path")
    path = PurePosixPath(key)
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise InvalidStoreKey("content key contains an unsafe path component")
    normalized = path.as_posix()
    if normalized != key:
        raise InvalidStoreKey("content key is not canonical")
    return normalized


class LocalContentStore:
    """Filesystem implementation that keeps all existing MakersVault bytes in place."""

    _CAPABILITIES = StoreCapabilities(
        streaming_read=True,
        staged_write=True,
        atomic_publish=True,
        create_if_absent=True,
        local_materialization=True,
        capacity_admission=True,
        bounded_enumeration=True,
        reversible_delete=True,
    )

    def __init__(self, root: Path | str):
        requested = Path(root)
        requested.mkdir(parents=True, exist_ok=True)
        self._root = requested.resolve()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def capabilities(self) -> StoreCapabilities:
        return self._CAPABILITIES

    def local_path(self, key: str) -> Path:
        normalized = normalize_store_key(key)
        untrusted = self._root
        for part in PurePosixPath(normalized).parts:
            untrusted = untrusted / part
            if untrusted.is_symlink():
                raise InvalidStoreKey("content key traverses a symbolic link")
        candidate = untrusted.resolve()
        if candidate == self._root or self._root not in candidate.parents:
            raise InvalidStoreKey("content key resolves outside the store")
        return candidate

    def key_for_path(self, path: Path | str) -> str:
        candidate = Path(path).resolve()
        if candidate == self._root or self._root not in candidate.parents:
            raise InvalidStoreKey("local path is outside the content store")
        return candidate.relative_to(self._root).as_posix()

    def open_read(self, key: str) -> BinaryIO:
        path = self.local_path(key)
        if path.is_symlink():
            raise ContentStoreError("managed content may not be a symbolic link")
        return path.open("rb")

    def stat(self, key: str) -> StoreStat | None:
        path = self.local_path(key)
        try:
            value = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return None
        if path.is_symlink() or not path.is_file():
            return None
        return StoreStat(key=normalize_store_key(key), size=value.st_size, modified_ns=value.st_mtime_ns)

    def exists(self, key: str) -> bool:
        return self.stat(key) is not None

    def staging_path(self, namespace: str, filename: str = "payload") -> Path:
        namespace_key = normalize_store_key(namespace)
        filename_key = normalize_store_key(filename)
        path = self.local_path(f".staging/{namespace_key}/{filename_key}")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def publish(self, staged: Path, key: str, *, overwrite: bool = False) -> StoreStat:
        destination = self.local_path(key)
        staged_path = Path(staged).resolve()
        if not staged_path.is_file() or staged_path.is_symlink():
            raise ContentStoreError("staged content must be a regular local file")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if overwrite:
            os.replace(staged_path, destination)
        else:
            try:
                os.link(staged_path, destination)
            except FileExistsError as exc:
                raise ContentAlreadyExists(key) from exc
            except OSError as exc:
                raise ContentStoreError("create-if-absent publish requires one local filesystem") from exc
            staged_path.unlink()
        self._prune(staged_path.parent)
        self._fsync_directory(destination.parent)
        result = self.stat(key)
        if result is None:
            raise ContentStoreError("published content is not a regular file")
        return result

    def iter_key_batches(self, prefix: str = "", *, batch_size: int = 1000) -> Iterator[list[str]]:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        normalized_prefix = normalize_store_key(prefix, allow_empty=True)
        start = self._root if not normalized_prefix else self.local_path(normalized_prefix)
        if not start.exists():
            return
        batch: list[str] = []
        stack = [start]
        while stack:
            current = stack.pop()
            if current.is_symlink():
                continue
            if current.is_file():
                batch.append(self.key_for_path(current))
                if len(batch) == batch_size:
                    yield sorted(batch)
                    batch = []
                continue
            if current.is_dir():
                children = sorted(current.iterdir(), key=lambda item: item.name, reverse=True)
                stack.extend(children)
        if batch:
            yield sorted(batch)

    def capacity(self, key: str | None = None) -> Capacity:
        target = self._root if key is None else self.local_path(key).parent
        while not target.exists() and target != target.parent:
            target = target.parent
        usage = shutil.disk_usage(target)
        return Capacity(total=usage.total, used=usage.used, free=usage.free)

    def prepare_delete(self, keys: list[str], operation_id: str | None = None) -> DeleteTicket:
        operation = normalize_store_key(operation_id or str(uuid.uuid4()))
        moves: list[DeleteMove] = []
        try:
            for key in sorted(set(keys)):
                normalized = normalize_store_key(key)
                source = self.local_path(normalized)
                if not source.exists():
                    continue
                if source.is_symlink() or not source.is_file():
                    raise ContentStoreError("only regular managed files may be prepared for deletion")
                quarantine_key = f".trash-quarantine/{operation}/{normalized}"
                destination = self.local_path(quarantine_key)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    raise ContentAlreadyExists(quarantine_key)
                os.replace(source, destination)
                moves.append(DeleteMove(normalized, quarantine_key))
        except Exception:
            self.rollback_delete(DeleteTicket(operation, tuple(moves)))
            raise
        return DeleteTicket(operation, tuple(moves))

    def rollback_delete(self, ticket: DeleteTicket) -> None:
        for move in reversed(ticket.moves):
            quarantine = self.local_path(move.quarantine_key)
            if not quarantine.exists():
                continue
            original = self.local_path(move.key)
            original.parent.mkdir(parents=True, exist_ok=True)
            if original.exists():
                raise ContentAlreadyExists(move.key)
            os.replace(quarantine, original)
        self._prune(self.local_path(f".trash-quarantine/{normalize_store_key(ticket.operation_id)}"))

    def commit_delete(self, ticket: DeleteTicket) -> None:
        for move in ticket.moves:
            self.local_path(move.quarantine_key).unlink(missing_ok=True)
        self._prune(self.local_path(f".trash-quarantine/{normalize_store_key(ticket.operation_id)}"))

    @contextmanager
    def materialize(self, key: str) -> Iterator[Path]:
        path = self.local_path(key)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(key)
        yield path

    def _prune(self, start: Path) -> None:
        current = start
        while current != self._root and self._root in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
