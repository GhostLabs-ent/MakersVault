import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import HTTPException


@dataclass(frozen=True)
class ResolvedAddress:
    family: int
    socktype: int
    proto: int
    sockaddr: tuple
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True)
class ResolvedTarget:
    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[ResolvedAddress, ...]


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not ip.is_global or ip.is_multicast or ip.is_unspecified


def _normalized_host(host: str) -> str:
    try:
        return host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid URL host") from exc


def _validate_host_name(host: str) -> str:
    if not host:
        raise HTTPException(status_code=400, detail="Invalid URL host")
    normalized = _normalized_host(host)
    if (
        normalized == "localhost"
        or normalized.endswith(".localhost")
        or normalized.endswith(".local")
        or normalized == "home.arpa"
        or normalized.endswith(".home.arpa")
    ):
        raise HTTPException(status_code=400, detail="Local addresses are not allowed")
    try:
        literal = ipaddress.ip_address(normalized)
    except ValueError:
        return normalized
    if is_blocked_ip(literal):
        raise HTTPException(status_code=400, detail="Local addresses are not allowed")
    return normalized


def _parse_remote_url(url: str) -> tuple[str, str, int]:
    if not isinstance(url, str) or not url:
        raise HTTPException(status_code=400, detail="Invalid URL")
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid URL") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Credentials in URL are not allowed")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid URL")
    host = _validate_host_name(parsed.hostname)
    target_port = port if port is not None else (443 if scheme == "https" else 80)
    if target_port < 1 or target_port > 65535:
        raise HTTPException(status_code=400, detail="Invalid URL port")
    return scheme, host, target_port


def validate_remote_host(host: str) -> None:
    normalized = _validate_host_name(host)
    try:
        literal = ipaddress.ip_address(normalized)
    except ValueError:
        try:
            infos = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise HTTPException(status_code=400, detail="Unable to resolve host") from exc
        if not infos:
            raise HTTPException(status_code=400, detail="Unable to resolve host")
        for info in infos:
            try:
                address = ipaddress.ip_address(info[4][0])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid resolved address") from exc
            if is_blocked_ip(address):
                raise HTTPException(status_code=400, detail="Local addresses are not allowed")
        return
    if is_blocked_ip(literal):
        raise HTTPException(status_code=400, detail="Local addresses are not allowed")


def validate_remote_url(url: str) -> str:
    _parse_remote_url(url)
    return url


def resolve_remote_target(url: str) -> ResolvedTarget:
    scheme, host, port = _parse_remote_url(url)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        flags = 0
    else:
        if is_blocked_ip(literal):
            raise HTTPException(status_code=400, detail="Local addresses are not allowed")
        flags = getattr(socket, "AI_NUMERICHOST", 0)

    try:
        infos = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            flags=flags,
        )
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="Unable to resolve host") from exc
    if not infos:
        raise HTTPException(status_code=400, detail="Unable to resolve host")

    addresses = []
    seen = set()
    for family, socktype, proto, _, sockaddr in infos:
        if family not in {socket.AF_INET, socket.AF_INET6} or socktype != socket.SOCK_STREAM:
            raise HTTPException(status_code=400, detail="Invalid resolved address")
        if len(sockaddr) < 2 or sockaddr[1] != port:
            raise HTTPException(status_code=400, detail="Invalid resolved address")
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid resolved address") from exc
        if is_blocked_ip(address):
            raise HTTPException(status_code=400, detail="Local addresses are not allowed")
        key = (family, socktype, proto, sockaddr)
        if key in seen:
            continue
        seen.add(key)
        addresses.append(ResolvedAddress(family, socktype, proto, sockaddr, address))
    if not addresses:
        raise HTTPException(status_code=400, detail="Unable to resolve host")
    return ResolvedTarget(url, scheme, host, port, tuple(addresses))


def normalize_import_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    return validate_remote_url(raw)
