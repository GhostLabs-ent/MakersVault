import tempfile
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request

from fastapi import HTTPException

from asset_service import persist_asset_from_response, stream_response_to_file
from config import IMPORT_HTML_MAX_BYTES, IMPORT_TIMEOUT_SECONDS, IMPORT_USER_AGENT
from file_utils import build_import_filename, is_html_content_type, mime_from_content_type
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
from safe_http import safe_urlopen
from schemas import ImportRequest
from url_utils import validate_remote_url


def open_import_response(url: str, body: ImportRequest, referer: Optional[str] = None, depth: int = 0):
    if depth > 3:
        raise HTTPException(status_code=400, detail="Too many redirects while resolving download link")
    url = validate_remote_url(url)
    headers = {"User-Agent": IMPORT_USER_AGENT, "Accept": "*/*"}
    host = (urlparse(url).hostname or "").lower()
    makerworld_cookie = None
    thingiverse_cookie = None
    if is_makerworld_page_host(host):
        makerworld_cookie = resolve_makerworld_cookie(body)
        headers = makerworld_html_headers(referer or url, cookie=makerworld_cookie)
    elif is_thingiverse_page_host(host):
        thingiverse_cookie = resolve_thingiverse_cookie(body)
        headers = thingiverse_html_headers(referer or url, cookie=thingiverse_cookie)
    elif is_printables_page_host(host):
        headers = printables_html_headers(referer or url)
    if referer:
        headers["Referer"] = referer
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
        download_url = None
        host = urlparse(final_url).hostname or ""
        if is_makerworld_page_host(host):
            if not makerworld_cookie:
                makerworld_cookie = resolve_makerworld_cookie(body)
            download_url = resolve_makerworld_download_url(html, final_url, makerworld_cookie)
        if not download_url and is_thingiverse_page_host(host):
            if thingiverse_cookie is None:
                thingiverse_cookie = resolve_thingiverse_cookie(body)
            download_url = resolve_thingiverse_download_url(final_url, thingiverse_cookie)
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
        return open_import_response(download_url, body, referer=final_url, depth=depth + 1)
    return resp, final_url


def import_asset_from_url(url: str, body: ImportRequest, referer: Optional[str] = None, depth: int = 0):
    resp, final_url = open_import_response(url, body, referer=referer, depth=depth)
    with resp:
        return persist_asset_from_response(resp, final_url, body)


def download_import_to_temp(url: str, body: ImportRequest) -> tuple[Path, str, str]:
    resp, final_url = open_import_response(url, body)
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
