import json
import os
import re
from html.parser import HTMLParser
from typing import Any, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request

from fastapi import HTTPException

from config import (
    IMPORT_ALLOWED_EXTS,
    IMPORT_BLOCKED_EXTS,
    IMPORT_BROWSER_USER_AGENT,
    IMPORT_EXT_PRIORITY,
    IMPORT_HTML_MAX_BYTES,
    IMPORT_TIMEOUT_SECONDS,
    IMPORT_USER_AGENT,
)
from file_utils import is_json_content_type
from schemas import ImportRequest
from safe_http import safe_urlopen


def makerworld_html_headers(referer: Optional[str] = None, cookie: Optional[str] = None) -> dict:
    headers = {
        "User-Agent": IMPORT_BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": "\"Not A(Brand\";v=\"99\", \"Google Chrome\";v=\"121\", \"Chromium\";v=\"121\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
    }
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    return headers


def makerworld_api_headers(referer: Optional[str] = None, nonce: Optional[str] = None, cookie: Optional[str] = None) -> dict:
    headers = {
        "User-Agent": IMPORT_BROWSER_USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "X-BBL-Client-Type": "web",
        "X-BBL-Client-Version": "00.00.00.01",
        "X-BBL-App-Source": "makerworld",
        "X-BBL-Client-Name": "MakerWorld",
    }
    if referer:
        headers["Referer"] = referer
    if nonce:
        headers["X-Nonce"] = nonce
    if cookie:
        headers["Cookie"] = cookie
    return headers


def resolve_makerworld_cookie(body: ImportRequest) -> Optional[str]:
    raw = (body.makerworld_cookie or os.getenv("MAKERWORLD_COOKIE", "")).strip()
    if not raw:
        return None
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return None
    value = lines[0]
    for line in lines:
        if line.lower().startswith("cookie:"):
            value = line[len("cookie:"):].strip()
            break
    return value or None


def resolve_thingiverse_cookie(body: ImportRequest) -> Optional[str]:
    raw = (body.thingiverse_cookie or os.getenv("THINGIVERSE_COOKIE", "")).strip()
    if not raw:
        return None
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return None
    value = lines[0]
    for line in lines:
        if line.lower().startswith("cookie:"):
            value = line[len("cookie:"):].strip()
            break
    return value or None


def is_makerworld_host(host: str) -> bool:
    normalized = (host or "").lower().rstrip(".")
    return normalized == "makerworld.com" or normalized.endswith(".makerworld.com")


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if not value:
                continue
            key_lower = key.lower()
            if key_lower in {"href", "src", "data-download", "data-download-url", "data-url", "data-file", "data-href"}:
                self.links.append(value)


def score_download_url(url: str) -> int:
    lower = url.lower()
    score = 0
    if "download" in lower:
        score += 6
    if "files" in lower:
        score += 2
    for idx, ext in enumerate(IMPORT_EXT_PRIORITY):
        if ext in lower:
            score += (len(IMPORT_EXT_PRIORITY) - idx) * 10
    return score


def is_potential_url(value: str) -> bool:
    if re.search(r"\s", value):
        return False
    if re.search(r"[<>{}\"\\^`]", value):
        return False
    return True


def contains_allowed_ext(url: str) -> bool:
    lower = url.lower()
    for ext in IMPORT_ALLOWED_EXTS:
        if re.search(re.escape(ext) + r"(?:$|[?#&])", lower):
            return True
    return False


def is_allowed_download_candidate(url: str) -> bool:
    lower = url.lower()
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext:
        if ext in IMPORT_ALLOWED_EXTS:
            return True
        if ext in IMPORT_BLOCKED_EXTS:
            return False
        if "download" in lower:
            return True
        return contains_allowed_ext(lower)
    if contains_allowed_ext(lower):
        return True
    return "download" in lower


def find_download_url(html: str, base_url: str) -> Optional[str]:
    parser = LinkCollector()
    try:
        parser.feed(html)
    except Exception:
        pass
    links = list(parser.links)
    links.extend(re.findall(r"https?://[^\s\"'<>]+", html, re.IGNORECASE))

    candidates: List[str] = []
    seen = set()
    for link in links:
        link = (link or "").strip()
        if not link or link.startswith("#"):
            continue
        if link.lower().startswith(("javascript:", "mailto:")):
            continue
        abs_url = urljoin(base_url, link)
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        if is_allowed_download_candidate(abs_url):
            candidates.append(abs_url)

    if not candidates:
        return None
    candidates.sort(key=score_download_url, reverse=True)
    return candidates[0]


def normalize_candidate_url(raw: str, base_url: str) -> Optional[str]:
    value = (raw or "").strip()
    if not value:
        return None
    if not is_potential_url(value):
        return None
    if value.startswith("//"):
        value = f"https:{value}"
    if value.startswith(("http://", "https://")):
        return value if is_allowed_download_candidate(value) else None
    if value.startswith("/"):
        abs_url = urljoin(base_url, value)
        return abs_url if is_allowed_download_candidate(abs_url) else None
    if "/" in value:
        abs_url = urljoin(base_url, value)
        return abs_url if is_allowed_download_candidate(abs_url) else None
    return None


def find_download_url_in_json(data: Any, base_url: str) -> Optional[str]:
    candidates: List[str] = []
    seen = set()
    stack = [data]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, str):
            if current in seen:
                continue
            seen.add(current)
            url = normalize_candidate_url(current, base_url)
            if url:
                candidates.append(url)
    if not candidates:
        return None
    candidates.sort(key=score_download_url, reverse=True)
    return candidates[0]


def extract_next_data_json(html: str) -> Optional[Any]:
    match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    raw = (match.group(1) or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def makerworld_design_id_from_next_data(data: Any) -> Optional[str]:
    try:
        design = data.get("props", {}).get("pageProps", {}).get("design", {})
        design_id = design.get("id")
        return str(design_id) if design_id else None
    except AttributeError:
        return None


def makerworld_instance_id_from_next_data(data: Any) -> Optional[str]:
    try:
        design = data.get("props", {}).get("pageProps", {}).get("design", {})
        default_instance = design.get("defaultInstanceId")
        if default_instance:
            return str(default_instance)
        instances = design.get("instances") or []
        if isinstance(instances, list):
            for inst in instances:
                if isinstance(inst, dict):
                    inst_id = inst.get("id")
                    if inst_id:
                        return str(inst_id)
        return None
    except AttributeError:
        return None


def makerworld_nonce_from_next_data(data: Any) -> Optional[str]:
    try:
        nonce = data.get("props", {}).get("pageProps", {}).get("x-nonce")
        return nonce if isinstance(nonce, str) and nonce.strip() else None
    except AttributeError:
        return None


def makerworld_model_id_from_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    match = re.search(r"/models/(\d+)", parsed.path or "")
    return match.group(1) if match else None


def fetch_json_from_url(url: str, referer: Optional[str] = None, headers: Optional[dict] = None) -> Optional[Any]:
    request_headers = {"User-Agent": IMPORT_USER_AGENT, "Accept": "application/json"}
    if referer:
        request_headers["Referer"] = referer
    if headers:
        request_headers.update(headers)
    req = Request(url, headers=request_headers)
    try:
        resp = safe_urlopen(req, timeout=IMPORT_TIMEOUT_SECONDS)
    except HTTPError:
        return None
    except URLError:
        return None

    with resp:
        raw = resp.read(IMPORT_HTML_MAX_BYTES + 1)
        if len(raw) > IMPORT_HTML_MAX_BYTES:
            return None
        content_type = resp.headers.get("Content-Type", "")
        if not is_json_content_type(content_type):
            trimmed = raw.lstrip()
            if not trimmed.startswith((b"{", b"[")):
                return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None


def parse_json_error_message(raw: bytes) -> Optional[str]:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("error", "detail", "message"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_download_url_from_response(data: Any, base_url: str) -> Optional[str]:
    if isinstance(data, dict):
        for key in ("url", "downloadUrl", "download_url"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
        inner = data.get("data")
        if isinstance(inner, dict):
            for key in ("url", "downloadUrl", "download_url"):
                value = inner.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    return find_download_url_in_json(data, base_url)


def fetch_makerworld_instance_download_url(
    instance_id: str,
    page_url: str,
    makerworld_cookie: Optional[str],
) -> Optional[str]:
    api_url = (
        "https://makerworld.com/api/v1/design-service/instance/"
        f"{instance_id}/f3mf?type=download&fileType=3mfstl"
    )
    req = Request(api_url, headers=makerworld_api_headers(referer=page_url, cookie=makerworld_cookie))
    try:
        resp = safe_urlopen(req, timeout=IMPORT_TIMEOUT_SECONDS)
    except HTTPError:
        return None
    except URLError:
        return None

    with resp:
        raw = resp.read(IMPORT_HTML_MAX_BYTES + 1)
        if len(raw) > IMPORT_HTML_MAX_BYTES:
            return None
        content_type = resp.headers.get("Content-Type", "")
        if not is_json_content_type(content_type):
            trimmed = raw.lstrip()
            if not trimmed.startswith((b"{", b"[")):
                return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return extract_download_url_from_response(data, api_url)


def fetch_makerworld_model_download_url(
    model_id: str,
    page_url: str,
    nonce: Optional[str],
    makerworld_cookie: Optional[str],
) -> Optional[str]:
    api_url = f"https://makerworld.com/api/v1/models/{model_id}/download"
    req = Request(api_url, headers=makerworld_api_headers(referer=page_url, nonce=nonce, cookie=makerworld_cookie))
    try:
        resp = safe_urlopen(req, timeout=IMPORT_TIMEOUT_SECONDS)
    except HTTPError:
        return None
    except URLError:
        return None

    with resp:
        raw = resp.read(IMPORT_HTML_MAX_BYTES + 1)
        if len(raw) > IMPORT_HTML_MAX_BYTES:
            return None
        content_type = resp.headers.get("Content-Type", "")
        if not is_json_content_type(content_type):
            trimmed = raw.lstrip()
            if not trimmed.startswith((b"{", b"[")):
                return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return extract_download_url_from_response(data, api_url)


def resolve_makerworld_download_url(
    html: str,
    page_url: str,
    makerworld_cookie: Optional[str],
) -> Optional[str]:
    next_data = extract_next_data_json(html)
    design_id = None
    nonce = None
    instance_id = None
    if next_data:
        url = find_download_url_in_json(next_data, page_url)
        if url:
            return url
        design_id = makerworld_design_id_from_next_data(next_data)
        nonce = makerworld_nonce_from_next_data(next_data)
        instance_id = makerworld_instance_id_from_next_data(next_data)

    if instance_id:
        url = fetch_makerworld_instance_download_url(instance_id, page_url, makerworld_cookie)
        if url:
            return url

    model_id = design_id or makerworld_model_id_from_url(page_url)
    if not model_id:
        return None
    url = fetch_makerworld_model_download_url(model_id, page_url, nonce, makerworld_cookie)
    if url:
        return url
    api_candidates = [
        f"https://makerworld.com/api/v1/models/{model_id}",
        f"https://makerworld.com/api/v1/models/{model_id}/files",
        f"https://makerworld.com/api/v1/model/{model_id}",
        f"https://makerworld.com/api/v1/model/{model_id}/files",
    ]
    for api_url in api_candidates:
        data = fetch_json_from_url(api_url, referer=page_url)
        if not data:
            continue
        url = find_download_url_in_json(data, api_url)
        if url:
            return url
    return None


def is_printables_page_host(host: str) -> bool:
    host = (host or "").lower()
    return host in {"printables.com", "www.printables.com"}


def printables_html_headers(referer: Optional[str] = None) -> dict:
    headers = {
        "User-Agent": IMPORT_BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def printables_model_id_from_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    match = re.search(r"/model/(\d+)", parsed.path or "")
    return match.group(1) if match else None


def fetch_printables_graphql(query: str, variables: dict, referer: Optional[str]) -> Optional[Any]:
    payload = {"query": query, "variables": variables or {}}
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "User-Agent": IMPORT_BROWSER_USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.printables.com",
    }
    if referer:
        headers["Referer"] = referer
    req = Request("https://api.printables.com/graphql/", data=data, headers=headers)
    try:
        resp = safe_urlopen(req, timeout=IMPORT_TIMEOUT_SECONDS)
    except HTTPError as err:
        message = None
        try:
            message = parse_json_error_message(err.read())
        except Exception:
            message = None
        if err.code in {401, 403, 429}:
            raise HTTPException(status_code=err.code or 400, detail=message or "Printables request failed")
        return None
    except URLError:
        return None

    with resp:
        raw = resp.read(IMPORT_HTML_MAX_BYTES + 1)
        if len(raw) > IMPORT_HTML_MAX_BYTES:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None


def parse_printables_error_messages(errors: Any) -> Optional[str]:
    if not isinstance(errors, list):
        return None
    messages: List[str] = []
    for err in errors:
        if not isinstance(err, dict):
            continue
        values = err.get("messages")
        if isinstance(values, list):
            messages.extend([value for value in values if isinstance(value, str) and value.strip()])
        elif isinstance(values, str) and values.strip():
            messages.append(values.strip())
    return ", ".join(messages) if messages else None


def select_best_download_link(links: List[str]) -> Optional[str]:
    candidates = [link for link in links if is_allowed_download_candidate(link)]
    if not candidates:
        return None
    candidates.sort(key=score_download_url, reverse=True)
    return candidates[0]


def extract_printables_ids(items: Any) -> List[str]:
    ids: List[str] = []
    if not isinstance(items, list):
        return ids
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get("id")
        if value is None:
            continue
        ids.append(str(value))
    return ids


def fetch_printables_model_meta(print_id: str, page_url: str) -> Optional[dict]:
    query = """
    query ($id: ID!) {
      print(id: $id) {
        id
        downloadPacks { id fileType }
        stls { id name }
      }
    }
    """
    data = fetch_printables_graphql(query, {"id": print_id}, referer=page_url)
    if not isinstance(data, dict):
        return None
    model = data.get("data", {}).get("print")
    return model if isinstance(model, dict) else None


def fetch_printables_download_output(print_id: str, variables: dict, page_url: str) -> Optional[dict]:
    mutation = """
    mutation ($printId: ID!, $source: DownloadSourceEnum!, $fileType: DownloadFileTypeEnum, $id: ID, $files: [DownloadFileInput!]) {
      getDownloadLink(printId: $printId, source: $source, fileType: $fileType, id: $id, files: $files) {
        ok
        errors { field messages code }
        output { link files { id link fileType } }
      }
    }
    """
    data = fetch_printables_graphql(mutation, variables, referer=page_url)
    if not isinstance(data, dict):
        return None
    result = data.get("data", {}).get("getDownloadLink")
    if not isinstance(result, dict):
        return None
    if result.get("ok") is False:
        message = parse_printables_error_messages(result.get("errors"))
        if message:
            raise HTTPException(status_code=400, detail=message)
        return None
    output = result.get("output")
    return output if isinstance(output, dict) else None


def resolve_printables_download_url(page_url: str) -> Optional[str]:
    print_id = printables_model_id_from_url(page_url)
    if not print_id:
        return None
    meta = fetch_printables_model_meta(print_id, page_url)
    if not meta:
        return None
    packs = meta.get("downloadPacks") if isinstance(meta, dict) else None
    pack_id = None
    if isinstance(packs, list):
        for pack in packs:
            if not isinstance(pack, dict):
                continue
            if pack.get("fileType") == "MODEL_FILES" and pack.get("id"):
                pack_id = str(pack.get("id"))
                break
        if not pack_id and packs:
            for pack in packs:
                if isinstance(pack, dict) and pack.get("id"):
                    pack_id = str(pack.get("id"))
                    break
    if pack_id:
        output = fetch_printables_download_output(
            print_id,
            {"printId": print_id, "source": "model_detail", "fileType": "pack", "id": pack_id},
            page_url,
        )
        if output:
            links = [link for link in [output.get("link")] if isinstance(link, str)]
            for entry in output.get("files") or []:
                if isinstance(entry, dict) and isinstance(entry.get("link"), str):
                    links.append(entry["link"])
            best = select_best_download_link(links)
            if best:
                return best
    stl_ids = extract_printables_ids(meta.get("stls"))
    if stl_ids:
        output = fetch_printables_download_output(
            print_id,
            {"printId": print_id, "source": "model_detail", "files": [{"fileType": "stl", "ids": stl_ids}]},
            page_url,
        )
        if output:
            links = [link for link in [output.get("link")] if isinstance(link, str)]
            for entry in output.get("files") or []:
                if isinstance(entry, dict) and isinstance(entry.get("link"), str):
                    links.append(entry["link"])
            best = select_best_download_link(links)
            if best:
                return best
    return None


def is_thingiverse_page_host(host: str) -> bool:
    host = (host or "").lower()
    return host in {"thingiverse.com", "www.thingiverse.com"}


def thingiverse_html_headers(referer: Optional[str] = None, cookie: Optional[str] = None) -> dict:
    headers = {
        "User-Agent": IMPORT_BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    return headers


def thingiverse_api_headers(
    referer: Optional[str] = None,
    cookie: Optional[str] = None,
    token: Optional[str] = None,
) -> dict:
    headers = {
        "User-Agent": IMPORT_BROWSER_USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.thingiverse.com",
    }
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def thingiverse_thing_id_from_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    match = re.search(r"thing:(\d+)", parsed.path or "", re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"/things/(\d+)", parsed.path or "", re.IGNORECASE)
    return match.group(1) if match else None


def fetch_thingiverse_json(
    url: str,
    page_url: str,
    thingiverse_cookie: Optional[str],
    token: Optional[str],
) -> Optional[Any]:
    req = Request(url, headers=thingiverse_api_headers(referer=page_url, cookie=thingiverse_cookie, token=token))
    try:
        resp = safe_urlopen(req, timeout=IMPORT_TIMEOUT_SECONDS)
    except HTTPError as err:
        message = None
        try:
            message = parse_json_error_message(err.read())
        except Exception:
            message = None
        if err.code in {401, 403, 429}:
            raise HTTPException(status_code=err.code or 400, detail=message or "Thingiverse request failed")
        return None
    except URLError:
        return None

    with resp:
        raw = resp.read(IMPORT_HTML_MAX_BYTES + 1)
        if len(raw) > IMPORT_HTML_MAX_BYTES:
            return None
        content_type = resp.headers.get("Content-Type", "")
        if not is_json_content_type(content_type):
            trimmed = raw.lstrip()
            if not trimmed.startswith((b"{", b"[")):
                return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None


def fetch_thingiverse_view_token(page_url: str, thingiverse_cookie: Optional[str]) -> Optional[str]:
    api_url = "https://www.thingiverse.com/api/v2/auth/view"
    req = Request(api_url, headers=thingiverse_api_headers(referer=page_url, cookie=thingiverse_cookie))
    try:
        resp = safe_urlopen(req, timeout=IMPORT_TIMEOUT_SECONDS)
    except HTTPError as err:
        message = None
        try:
            message = parse_json_error_message(err.read())
        except Exception:
            message = None
        if err.code in {401, 403, 429}:
            detail = message or (
                "Thingiverse blocked the request. Paste the Cookie header from your browser session "
                "in Settings to import."
            )
            raise HTTPException(status_code=err.code or 400, detail=detail)
        return None
    except URLError:
        return None

    with resp:
        raw = resp.read(IMPORT_HTML_MAX_BYTES + 1)
        if len(raw) > IMPORT_HTML_MAX_BYTES:
            return None
        content_type = resp.headers.get("Content-Type", "")
        if not is_json_content_type(content_type):
            trimmed = raw.lstrip()
            if not trimmed.startswith((b"{", b"[")):
                return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        token = data.get("access") or data.get("token") or data.get("access_token")
        if isinstance(token, str) and token.strip():
            return token.strip()
        inner = data.get("data")
        if isinstance(inner, dict):
            token = inner.get("access") or inner.get("token") or inner.get("access_token")
            if isinstance(token, str) and token.strip():
                return token.strip()
    return None


def resolve_thingiverse_download_url(page_url: str, thingiverse_cookie: Optional[str]) -> Optional[str]:
    thing_id = thingiverse_thing_id_from_url(page_url)
    if not thing_id:
        return None
    token = fetch_thingiverse_view_token(page_url, thingiverse_cookie)
    if not token:
        if not thingiverse_cookie:
            raise HTTPException(
                status_code=403,
                detail="Thingiverse requires a session cookie to fetch download links.",
            )
        return None
    api_candidates = [
        f"https://www.thingiverse.com/api/v2/things/{thing_id}/files",
        f"https://www.thingiverse.com/api/v2/things/{thing_id}",
    ]
    for api_url in api_candidates:
        data = fetch_thingiverse_json(api_url, page_url, thingiverse_cookie, token)
        if not data:
            continue
        url = find_download_url_in_json(data, api_url)
        if url:
            return url
    return f"https://www.thingiverse.com/thing:{thing_id}/zip"
