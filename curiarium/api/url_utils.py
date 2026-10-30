import ipaddress
import socket
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import HTTPException

DEFAULT_PORTS = {"http": 80, "https": 443}

# Tracking parameters are dropped so two links to the same page collapse to one
# source key. The list is deliberately conservative: an unknown key is kept,
# because dropping a parameter that changes the page would merge two models.
TRACKING_QUERY_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "si", "ref", "ref_src", "spm"})
TRACKING_QUERY_PREFIXES = ("utm_",)


def is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


def _validate_url_shape(parsed) -> Optional[int]:
    if parsed.scheme not in DEFAULT_PORTS:
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Credentials in URL are not allowed")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid URL")
    try:
        return parsed.port
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid URL port") from None


def resolve_remote_host(host: str, port: Optional[int]) -> list[str]:
    if not host:
        raise HTTPException(status_code=400, detail="Invalid URL host")
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".local"):
        raise HTTPException(status_code=400, detail="Local addresses are not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if is_blocked_ip(ip):
            raise HTTPException(status_code=400, detail="Local addresses are not allowed")
        return [str(ip)]

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="Unable to resolve host") from None

    resolved: list[str] = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if is_blocked_ip(ip):
            raise HTTPException(status_code=400, detail="Local addresses are not allowed")
        text = str(ip)
        if text not in resolved:
            resolved.append(text)
    if not resolved:
        raise HTTPException(status_code=400, detail="Unable to resolve host")
    return resolved


def validate_remote_host(host: str) -> None:
    resolve_remote_host(host, None)


def resolve_remote_url(url: str) -> list[str]:
    """Validate a URL and return the addresses that were validated for it.

    The returned addresses are the ones the caller must connect to: re-resolving
    before connecting would reopen the DNS-rebinding window.
    """
    parsed = urlparse(url)
    port = _validate_url_shape(parsed) or DEFAULT_PORTS[parsed.scheme]
    return resolve_remote_host(parsed.hostname, port)


def validate_remote_url(url: str) -> str:
    resolve_remote_url(url)
    return url


def _is_tracking_param(key: str) -> bool:
    lowered = (key or "").lower()
    return lowered in TRACKING_QUERY_KEYS or lowered.startswith(TRACKING_QUERY_PREFIXES)


def _canonical_url(value: str) -> str:
    """The canonical form of an already-schemed URL; may raise on a bad port."""
    parsed = urlparse(value)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if not host:
        return value.lower()
    if host.startswith("www."):
        host = host[4:]
    if port is not None and port != DEFAULT_PORTS.get(scheme):
        host = f"{host}:{port}"
    path = parsed.path or ""
    if path.endswith("/"):
        path = path[:-1]
    params = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if not _is_tracking_param(key)]
    query = urlencode(sorted(params))
    return f"{scheme}://{host}{path}" + (f"?{query}" if query else "")


def canonical_url(raw: str) -> str:
    """A displayable, de-duplicated form of `raw`: no DNS, no validation, total.

    It keeps the scheme and host a human can click (a project renders this as
    "View original on <site>"), while dropping the parts that differ between two
    links to the same page: `www.`, a default port, the fragment, tracking
    parameters, parameter order and a trailing slash.

    It must never raise: `urlparse` rejects an unmatched bracket and `.port`
    rejects a non-numeric port (see `_validate_url_shape`), and an import of a
    garbage URL must not turn into a 500.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    try:
        return _canonical_url(value)
    except ValueError:
        return value.lower()


def source_key(raw: str) -> str:
    """The de-duplication key for a model page: stable, total, no I/O.

    The three supported page hosts use the numeric model id, so a renamed slug
    (`/model/123-old-name` -> `/model/123-new-name`) is the same source. Every
    other URL falls back to `canonical_url`, which is total by construction.
    """
    canonical = canonical_url(raw)
    if not canonical:
        return ""
    # Lazy: this module is on the SSRF path, and import_resolvers pulls in the
    # fetch helpers - importing it at module level would drag that graph here.
    from import_resolvers import (
        is_makerworld_page_host,
        is_printables_page_host,
        is_thingiverse_page_host,
        makerworld_model_id_from_url,
        printables_model_id_from_url,
        thingiverse_thing_id_from_url,
    )

    try:
        host = (urlparse(canonical).hostname or "").lower()
    except ValueError:
        return canonical
    if is_makerworld_page_host(host):
        model_id = makerworld_model_id_from_url(canonical)
        if model_id:
            return f"makerworld:{model_id}"
    elif is_printables_page_host(host):
        model_id = printables_model_id_from_url(canonical)
        if model_id:
            return f"printables:{model_id}"
    elif is_thingiverse_page_host(host):
        thing_id = thingiverse_thing_id_from_url(canonical)
        if thing_id:
            return f"thingiverse:{thing_id}"
    return canonical


def normalize_import_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    return validate_remote_url(raw)
