import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException

DEFAULT_PORTS = {"http": 80, "https": 443}


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


def normalize_import_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    return validate_remote_url(raw)
