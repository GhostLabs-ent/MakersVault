import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request

from fastapi import HTTPException

from asset_service import persist_asset_from_response, stream_response_to_file
from config import IMPORT_HTML_MAX_BYTES, IMPORT_TIMEOUT_SECONDS, IMPORT_USER_AGENT
from file_utils import build_import_filename, is_html_content_type, mime_from_content_type
from import_policy import credentialed_source_for, refuse_paid_or_gated
from import_resolvers import (
    find_download_url,
    is_makerworld_page_host,
    is_printables_page_host,
    is_thingiverse_page_host,
    makerworld_html_headers,
    printables_html_headers,
    resolve_makerworld_cookie,
    resolve_makerworld_download_url,
    resolve_printables_download_url,
    resolve_thingiverse_cookie,
    resolve_thingiverse_download_url,
    thingiverse_html_headers,
)
from models import Asset
from safe_http import safe_urlopen
from schemas import ImportRequest
from url_utils import validate_remote_url


@dataclass(frozen=True)
class ImportPage:
    """A page that was read on the way to a file, with its post-redirect URL."""

    url: str
    html: str


@dataclass(frozen=True)
class ImportAttempt:
    """One single-file import attempt: the asset, the page, or the error."""

    asset: Optional[Asset] = None
    page: Optional[ImportPage] = None
    error: Optional[HTTPException] = None


@dataclass(frozen=True)
class ZipAttempt:
    """One zip download attempt; `tmp_path` is the caller's to delete on success."""

    tmp_path: Optional[Path] = None
    filename: str = ""
    mime: str = ""
    page: Optional[ImportPage] = None
    error: Optional[HTTPException] = None


def import_request_headers(url: str, body: ImportRequest, referer: Optional[str] = None) -> dict:
    """Headers for one import hop; the only place a session cookie can enter an
    outbound request.

    A cookie is attached only when the hop's host belongs to a credentialed
    public resolver (import_policy.credentialed_source_for), which is what keeps
    the credential scoped to anonymous rate-limit workarounds.
    """
    headers = {"User-Agent": IMPORT_USER_AGENT, "Accept": "*/*"}
    host = (urlparse(url).hostname or "").lower()
    source = credentialed_source_for(host)
    if source == "makerworld":
        headers = makerworld_html_headers(referer or url, cookie=resolve_makerworld_cookie(body))
    elif source == "thingiverse":
        headers = thingiverse_html_headers(referer or url, cookie=resolve_thingiverse_cookie(body))
    elif is_printables_page_host(host):
        headers = printables_html_headers(referer or url)
    if referer:
        headers["Referer"] = referer
    return headers


def _resolve_import(
    url: str,
    body: ImportRequest,
    referer: Optional[str],
    depth: int,
    pages: List["ImportPage"],
):
    # URL-only guard: no DNS, no request and no cookie for a paid/gated URL. It
    # also covers HTML-discovered download URLs because they re-enter here.
    refuse_paid_or_gated(url)
    if depth > 3:
        raise HTTPException(status_code=400, detail="Too many redirects while resolving download link")
    url = validate_remote_url(url)
    headers = import_request_headers(url, body, referer)
    req = Request(url, headers=headers)
    try:
        resp = safe_urlopen(req, timeout=IMPORT_TIMEOUT_SECONDS)
    except HTTPError as err:
        raise HTTPException(status_code=err.code or 400, detail=f"Failed to fetch URL: {err.reason}") from err
    except URLError as err:
        raise HTTPException(status_code=400, detail="Failed to reach the provided URL") from err

    final_url = resp.geturl()
    content_type = resp.headers.get("Content-Type", "")
    if is_html_content_type(content_type):
        html_bytes = resp.read(IMPORT_HTML_MAX_BYTES + 1)
        truncated = len(html_bytes) > IMPORT_HTML_MAX_BYTES
        if truncated:
            html_bytes = html_bytes[:IMPORT_HTML_MAX_BYTES]
        charset = resp.headers.get_content_charset() or "utf-8"
        html = html_bytes.decode(charset, errors="replace")
        resp.close()
        # Keep the page before it is replaced by the download: a gated model has
        # no download to return, and its metadata is all the caller will get.
        pages.append(ImportPage(url=final_url, html=html))
        download_url = None
        host = urlparse(final_url).hostname or ""
        if is_makerworld_page_host(host):
            download_url = resolve_makerworld_download_url(html, final_url, resolve_makerworld_cookie(body))
        if not download_url and is_thingiverse_page_host(host):
            download_url = resolve_thingiverse_download_url(final_url, resolve_thingiverse_cookie(body))
        if not download_url and is_printables_page_host(host):
            download_url = resolve_printables_download_url(final_url)
        if not download_url:
            download_url = find_download_url(html, final_url)
        if not download_url:
            if truncated:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "No downloadable model file found in the scanned portion of the page. "
                        "Use a direct download link or increase IMPORT_HTML_MAX_KB."
                    ),
                )
            raise HTTPException(status_code=400, detail="No downloadable model file found. Use a direct download link.")
        return _resolve_import(download_url, body, referer=final_url, depth=depth + 1, pages=pages)
    return resp, final_url


def open_import_response(url: str, body: ImportRequest, referer: Optional[str] = None, depth: int = 0):
    """Open the (possibly HTML-redirected) response for an import URL.

    The thin public wrapper keeps the `main.open_import_response` patch surface
    exactly as it was; the attempt helpers below use `_resolve_import` directly
    because they also need the page HTML that was read on the way.
    """
    return _resolve_import(url, body, referer, depth, [])


def import_asset_attempt(url: str, body: ImportRequest) -> "ImportAttempt":
    """One single-file import attempt, keeping the page it read when it fails."""
    pages: List[ImportPage] = []
    try:
        resp, final_url = _resolve_import(url, body, None, 0, pages)
        with resp:
            asset = persist_asset_from_response(resp, final_url, body)
    except HTTPException as err:
        return ImportAttempt(page=pages[-1] if pages else None, error=err)
    return ImportAttempt(asset=asset, page=pages[-1] if pages else None)


def download_zip_attempt(url: str, body: ImportRequest) -> "ZipAttempt":
    """One zip download attempt, keeping the page it read and its temp file."""
    pages: List[ImportPage] = []
    tmp_path: Optional[Path] = None
    try:
        resp, final_url = _resolve_import(url, body, None, 0, pages)
        tmp_path, filename, mime = _write_import_temp(resp, final_url, body)
    except HTTPException as err:
        # A failure after the write (there is none today) must not leak the file;
        # the caller owns deletion only on success.
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        return ZipAttempt(page=pages[-1] if pages else None, error=err)
    return ZipAttempt(tmp_path=tmp_path, filename=filename, mime=mime, page=pages[-1] if pages else None)


def import_asset_from_url(url: str, body: ImportRequest, referer: Optional[str] = None, depth: int = 0):
    resp, final_url = open_import_response(url, body, referer=referer, depth=depth)
    with resp:
        return persist_asset_from_response(resp, final_url, body)


def _write_import_temp(resp, final_url: str, body: ImportRequest) -> tuple[Path, str, str]:
    """Stream one open response into a temp file; remove it if the write fails."""
    tmp_path = None
    with resp:
        filename = build_import_filename(final_url, resp.headers, body.filename)
        mime = mime_from_content_type(resp.headers.get("Content-Type", ""), filename)
        suffix = Path(filename).suffix or ""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp_path = Path(tmp.name)
        tmp.close()
        try:
            stream_response_to_file(resp, tmp_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
    return tmp_path, filename, mime


def download_import_to_temp(url: str, body: ImportRequest) -> tuple[Path, str, str]:
    resp, final_url = open_import_response(url, body)
    return _write_import_temp(resp, final_url, body)
