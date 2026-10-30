"""Stream a multipart file part straight into a caller-owned path.

Starlette's form parser spools every file part into a ``SpooledTemporaryFile``
and only then hands the bytes to the handler, so a large upload is written to
the OS temp directory in full and copied to storage in full. This module drives
python-multipart's push parser itself and writes each file-part chunk to the
staging path as it arrives, off the event loop. The caller renames the finished
file into its final place once the rendered destination is known.

The parser's own ``max_size`` silently truncates instead of raising, so the
byte counter here is the enforcement point and it rejects an over-cap stream
while it is still arriving.
"""

from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional

from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

# One write call per megabyte: storage can be a network mount, so a single huge
# write would keep a worker thread busy for a long time without progress.
WRITE_CHUNK_SIZE = 1024 * 1024
# Part headers are tiny; this cap only stops a malicious body from growing them
# without bound before the parser reaches the data.
HEADER_BYTES_CAP = 16 * 1024


class UploadTooLarge(Exception):
    """The file part exceeded ``max_bytes`` while streaming."""

    def __init__(self, limit: int):
        super().__init__(f"upload exceeds {limit} bytes")
        self.limit = limit


class UploadRequestError(Exception):
    """A request the endpoint answers with ``status_code`` instead of storing."""

    status_code = 400

    def __init__(self, detail: str, status_code: Optional[int] = None):
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class MalformedMultipart(UploadRequestError):
    """The request body is not the multipart document its headers promise."""


class MissingFilePart(UploadRequestError):
    """No part named ``field`` with a filename was present."""

    def __init__(self, field_name: str):
        super().__init__(f"{field_name}: field required", status_code=422)


class UnsupportedContentType(UploadRequestError):
    """The named file part's Content-Type is not one the endpoint accepts."""

    status_code = 415

    def __init__(self, content_type: str):
        self.content_type = content_type
        super().__init__(f"unsupported content type: {content_type or 'missing'}")


@dataclass
class StreamedUpload:
    fields: Dict[str, str]
    filename: str
    content_type: str
    size: int
    path: Path


def _user_safe_decode(src: bytes, codec: str) -> str:
    try:
        return src.decode(codec)
    except UnicodeDecodeError:
        return src.decode("latin-1")


class FileSink:
    """Write one file part to a staging path, one bounded chunk at a time."""

    def __init__(self, path: Path):
        self.path = path
        self._handle: Optional[BinaryIO] = None

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def open(self) -> None:
        if self._handle is None:
            # A concurrent upload's move prunes the empty staging directory, so
            # the sink re-creates it at open time rather than trusting mkdir.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("wb")

    def write(self, data: bytes) -> None:
        assert self._handle is not None
        for start in range(0, len(data), WRITE_CHUNK_SIZE):
            self._handle.write(data[start : start + WRITE_CHUNK_SIZE])

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def discard(self) -> None:
        try:
            self.close()
        finally:
            self.path.unlink(missing_ok=True)


@dataclass
class _PartState:
    headers: Dict[bytes, bytes] = field(default_factory=dict)
    header_field: bytes = b""
    header_value: bytes = b""
    header_bytes: int = 0
    field_name: str = ""
    filename: Optional[str] = None
    content_type: str = ""
    is_file: bool = False
    sink: Optional[FileSink] = None
    field_data: bytearray = field(default_factory=bytearray)


class _StreamCallbacks:
    """Parser callbacks that divert the selected file part into a ``FileSink``.

    File bytes are queued here and flushed by the caller after each
    ``parser.write`` because callbacks are synchronous and file I/O must not run
    on the event loop.
    """

    def __init__(
        self,
        staging_path: Path,
        *,
        max_bytes: int,
        field_name: str,
        max_fields: int,
        max_field_bytes: int,
        charset: str,
        allowed_content_types: Optional[Collection[str]] = None,
    ):
        self.staging_path = staging_path
        self.max_bytes = max_bytes
        self.field_name = field_name
        self.max_fields = max_fields
        self.max_field_bytes = max_field_bytes
        self.charset = charset
        self.allowed_content_types = (
            frozenset(name.strip().lower() for name in allowed_content_types) if allowed_content_types is not None else None
        )
        self.pending: List[bytes] = []
        self.fields: Dict[str, str] = {}
        self.sink: Optional[FileSink] = None
        self.file_size = 0
        self.file_filename = ""
        self.file_content_type = ""
        self.field_count = 0
        self.ended = False
        self._part = _PartState()

    def handlers(self) -> Dict[str, object]:
        return {
            "on_part_begin": self.on_part_begin,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_end": self.on_end,
        }

    def take_pending(self) -> List[bytes]:
        pending = self.pending
        self.pending = []
        return pending

    def on_part_begin(self) -> None:
        self._part = _PartState()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._part.header_bytes += end - start
        self._check_header_size()
        self._part.header_field += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._part.header_bytes += end - start
        self._check_header_size()
        self._part.header_value += data[start:end]

    def _check_header_size(self) -> None:
        if self._part.header_bytes > HEADER_BYTES_CAP:
            raise MalformedMultipart("multipart part headers are too large")

    def on_header_end(self) -> None:
        self._part.headers[self._part.header_field.lower()] = self._part.header_value
        self._part.header_field = b""
        self._part.header_value = b""

    def on_headers_finished(self) -> None:
        part = self._part
        _, options = parse_options_header(part.headers.get(b"content-disposition", b""))
        name = options.get(b"name")
        if not name:
            raise MalformedMultipart("multipart part is missing a name")
        part.field_name = _user_safe_decode(name, self.charset)
        part.content_type = part.headers.get(b"content-type", b"").decode("latin-1")
        filename = options.get(b"filename")
        if filename is None:
            self.field_count += 1
            if self.field_count > self.max_fields:
                raise MalformedMultipart(f"Too many fields. Maximum number of fields is {self.max_fields}.")
            return
        part.is_file = True
        part.filename = _user_safe_decode(filename, self.charset)
        if self.sink is not None or part.field_name != self.field_name:
            # Only the named field is consumed; later file parts are ignored.
            return
        # No file has been opened yet, so the staging path is still absent and
        # the ``except BaseException`` cleanup below finds nothing to discard.
        self._check_content_type(part.content_type)
        self.sink = FileSink(self.staging_path)
        part.sink = self.sink
        self.file_filename = part.filename
        self.file_content_type = part.content_type

    def _check_content_type(self, content_type: str) -> None:
        if self.allowed_content_types is None:
            return
        # The raw header value, parameters included: a part that carried a
        # ``; charset=`` suffix keeps the verdict the pre-streaming check gave it.
        if content_type.strip().lower() not in self.allowed_content_types:
            raise UnsupportedContentType(content_type)

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        payload = data[start:end]
        if not payload:
            return
        part = self._part
        if part.is_file:
            if part.sink is None:
                # Only the named field is consumed; later file parts are ignored.
                return
            if self.max_bytes and self.file_size + len(payload) > self.max_bytes:
                raise UploadTooLarge(self.max_bytes)
            self.file_size += len(payload)
            self.pending.append(payload)
            return
        if len(part.field_data) + len(payload) > self.max_field_bytes:
            raise MalformedMultipart(f"Field exceeds the {self.max_field_bytes} byte limit")
        part.field_data += payload

    def on_part_end(self) -> None:
        part = self._part
        if not part.is_file:
            self.fields[part.field_name] = _user_safe_decode(bytes(part.field_data), self.charset)

    def on_end(self) -> None:
        self.ended = True


def _multipart_options(request: Request) -> Dict[bytes, bytes]:
    ctype, options = parse_options_header(request.headers.get("content-type", ""))
    if ctype != b"multipart/form-data":
        raise MalformedMultipart("Expected multipart/form-data")
    if b"boundary" not in options:
        raise MalformedMultipart("Missing multipart boundary")
    return options


async def stream_file_part(
    request: Request,
    staging_path: Path,
    *,
    max_bytes: int,
    field: str = "file",
    max_fields: int = 64,
    max_field_bytes: int = 1024 * 1024,
    allowed_content_types: Optional[Collection[str]] = None,
) -> StreamedUpload:
    """Stream the named file part of a multipart request into ``staging_path``.

    The caller owns the finished file on success. On any failure - malformed
    body, oversize stream, client disconnect, OS error - the staging file is
    removed before the exception propagates.

    When ``allowed_content_types`` is given, the selected file part's
    Content-Type is checked as soon as its headers are parsed, before any of its
    bytes are read or staged, and a value outside the set raises
    ``UnsupportedContentType``.
    """
    options = _multipart_options(request)
    charset = options.get(b"charset", b"utf-8").decode("latin-1")
    callbacks = _StreamCallbacks(
        staging_path,
        max_bytes=max_bytes,
        field_name=field,
        max_fields=max_fields,
        max_field_bytes=max_field_bytes,
        charset=charset,
        allowed_content_types=allowed_content_types,
    )
    try:
        # The constructor enforces the boundary cap by raising ``FormParserError``,
        # the *parent* of ``MultipartParseError``: untranslated it would slip past
        # the ``write`` handler below and leave as a 500.
        try:
            parser = MultipartParser(options[b"boundary"], callbacks.handlers())
        except FormParserError as exc:
            raise MalformedMultipart(f"Malformed multipart body: {exc}") from None
        async for chunk in request.stream():
            try:
                parser.write(chunk)
            except FormParserError as exc:
                raise MalformedMultipart(f"Malformed multipart body: {exc}") from None
            if callbacks.sink is not None and not callbacks.sink.is_open:
                await run_in_threadpool(callbacks.sink.open)
            await _flush_pending(callbacks)
        parser.finalize()
        if not callbacks.ended:
            raise MalformedMultipart("incomplete multipart body")
        if callbacks.sink is None:
            raise MissingFilePart(field)
        await run_in_threadpool(callbacks.sink.close)
        return StreamedUpload(
            fields=callbacks.fields,
            filename=callbacks.file_filename,
            content_type=callbacks.file_content_type,
            size=callbacks.file_size,
            path=staging_path,
        )
    except BaseException:
        sink = callbacks.sink
        if sink is not None:
            await run_in_threadpool(sink.discard)
        else:
            await run_in_threadpool(staging_path.unlink, missing_ok=True)
        raise


async def _flush_pending(callbacks: _StreamCallbacks) -> None:
    sink = callbacks.sink
    if sink is None:
        callbacks.take_pending()
        return
    for data in callbacks.take_pending():
        await run_in_threadpool(sink.write, data)
