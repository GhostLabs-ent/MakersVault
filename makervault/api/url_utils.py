import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import idna
from fastapi import HTTPException


_ASCII_LOWERCASE = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


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
    # One DNS root dot is allowed, not arbitrary empty labels. Bound work before
    # punycode conversion, and never accept an IPv6 zone identifier or URL escape.
    if not host or len(host) > 254 or "%" in host:
        raise HTTPException(status_code=400, detail="Invalid URL host")
    candidate = host.removesuffix(".")
    if candidate.endswith("."):
        raise HTTPException(status_code=400, detail="Invalid URL host")
    try:
        literal = ipaddress.ip_address(candidate)
    except ValueError:
        pass
    else:
        return literal.compressed
    try:
        # Lower ASCII only: Unicode casefold/compatibility mapping can change
        # domain identity. IDNA2008 validates Unicode/NFC and existing A-labels.
        return idna.encode(
            candidate.translate(_ASCII_LOWERCASE), strict=True, uts46=False,
            std3_rules=True,
        ).decode("ascii")
    except idna.IDNAError as exc:
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


def remote_url_origin(url: str) -> tuple[str, str, int]:
    """Validate an outbound authority and return its canonical origin without DNS."""
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
    if "@" in parsed.netloc:
        raise HTTPException(status_code=400, detail="Credentials in URL are not allowed")
    # Split the original authority: SplitResult.hostname lowercases Unicode
    # before our explicit policy can reject it (for example, the Kelvin sign).
    authority = parsed.netloc
    if authority.startswith("["):
        closing = authority.find("]")
        raw_host = authority[1:closing]
        suffix = authority[closing + 1 :]
        try:
            ipaddress.IPv6Address(raw_host)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid URL host") from exc
    else:
        raw_host, separator, port_text = authority.partition(":")
        suffix = separator + port_text
    if suffix and (
        not suffix.startswith(":") or not suffix[1:].isascii() or not suffix[1:].isdigit()
    ):
        raise HTTPException(status_code=400, detail="Invalid URL port")
    if not raw_host:
        raise HTTPException(status_code=400, detail="Invalid URL")
    host = _validate_host_name(raw_host)
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
    remote_url_origin(url)
    return url


def resolve_remote_target(url: str) -> ResolvedTarget:
    scheme, host, port = remote_url_origin(url)
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
