import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException


def is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


def validate_remote_host(host: str) -> None:
    if not host:
        raise HTTPException(status_code=400, detail="Invalid URL host")
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".local"):
        raise HTTPException(status_code=400, detail="Local addresses are not allowed")
    try:
        ip = ipaddress.ip_address(host)
        if is_blocked_ip(ip):
            raise HTTPException(status_code=400, detail="Local addresses are not allowed")
        return
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="Unable to resolve host") from None

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if is_blocked_ip(ip):
            raise HTTPException(status_code=400, detail="Local addresses are not allowed")


def validate_remote_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Credentials in URL are not allowed")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid URL")
    validate_remote_host(parsed.hostname)
    return url


def normalize_import_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    return validate_remote_url(raw)
