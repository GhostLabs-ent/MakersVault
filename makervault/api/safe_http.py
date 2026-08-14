import http.client
import socket
import ssl
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request

from fastapi import HTTPException

from config import IMPORT_MAX_REDIRECTS, IMPORT_TIMEOUT_SECONDS
from url_utils import ResolvedAddress, ResolvedTarget, resolve_remote_target, validate_remote_url


REDIRECT_STATUSES = {301, 302, 303, 307, 308}
SENSITIVE_REDIRECT_HEADERS = {"authorization", "cookie", "proxy-authorization", "host"}
ENTITY_HEADERS = {"content-length", "content-type", "transfer-encoding"}


class SafeHTTPResponse:
    def __init__(self, response: http.client.HTTPResponse, connection, url: str):
        self._response = response
        self._connection = connection
        self.url = url
        self.status = response.status
        self.code = response.status
        self.reason = response.reason
        self.headers = response.headers

    def read(self, amount: Optional[int] = None) -> bytes:
        return self._response.read() if amount is None else self._response.read(amount)

    def geturl(self) -> str:
        return self.url

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def _connected_socket(address: ResolvedAddress, timeout: float) -> socket.socket:
    sock = socket.socket(address.family, address.socktype, address.proto)
    try:
        sock.settimeout(timeout)
        sock.connect(address.sockaddr)
        return sock
    except Exception:
        sock.close()
        raise


def _connect_target(target: ResolvedTarget, timeout: float):
    errors = []
    context = ssl.create_default_context() if target.scheme == "https" else None
    for address in target.addresses:
        raw_socket = None
        try:
            raw_socket = _connected_socket(address, timeout)
            if target.scheme == "https":
                assert context is not None
                raw_socket = context.wrap_socket(raw_socket, server_hostname=target.host)
                connection = http.client.HTTPSConnection(
                    target.host,
                    target.port,
                    timeout=timeout,
                    context=context,
                )
            else:
                connection = http.client.HTTPConnection(target.host, target.port, timeout=timeout)
            connection.sock = raw_socket
            return connection
        except (OSError, ssl.SSLError) as exc:
            errors.append(exc)
            if raw_socket is not None:
                raw_socket.close()
    reason = errors[-1] if errors else OSError("No validated addresses available")
    raise URLError(reason)


def _request_path(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def _request_once(request: Request, target: ResolvedTarget, timeout: float) -> SafeHTTPResponse:
    connection = _connect_target(target, timeout)
    headers = {
        key: value
        for key, value in request.header_items()
        if key.lower() != "host"
    }
    try:
        connection.request(
            request.get_method(),
            _request_path(target.url),
            body=request.data,
            headers=headers,
        )
        response = connection.getresponse()
        return SafeHTTPResponse(response, connection, target.url)
    except Exception:
        connection.close()
        raise


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
    return scheme, (parsed.hostname or "").rstrip(".").lower(), port


def _redirect_request(request: Request, response: SafeHTTPResponse, next_url: str) -> Request:
    old_origin = _origin(request.full_url)
    next_origin = _origin(next_url)
    if old_origin[0] == "https" and next_origin[0] != "https":
        raise HTTPException(status_code=400, detail="HTTPS downgrade redirects are not allowed")

    method = request.get_method()
    data = request.data
    convert_to_get = response.status == 303 and method != "HEAD"
    convert_to_get = convert_to_get or (response.status in {301, 302} and method not in {"GET", "HEAD"})
    headers = {}
    for key, value in request.header_items():
        lowered = key.lower()
        if lowered == "host":
            continue
        if old_origin != next_origin and lowered in SENSITIVE_REDIRECT_HEADERS:
            continue
        if convert_to_get and lowered in ENTITY_HEADERS:
            continue
        headers[key] = value
    if convert_to_get:
        method = "GET"
        data = None
    return Request(next_url, data=data, headers=headers, method=method)


def safe_urlopen(
    request: Request | str,
    timeout: float = IMPORT_TIMEOUT_SECONDS,
    max_redirects: int = IMPORT_MAX_REDIRECTS,
) -> SafeHTTPResponse:
    current = request if isinstance(request, Request) else Request(request)
    redirects = 0
    while True:
        target = resolve_remote_target(current.full_url)
        try:
            response = _request_once(current, target, timeout)
        except HTTPException:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise URLError(exc) from exc

        if response.status in REDIRECT_STATUSES:
            location = response.headers.get("Location")
            if not location:
                raise HTTPError(current.full_url, response.status, response.reason, response.headers, response)
            if redirects >= max_redirects:
                response.close()
                raise HTTPException(status_code=400, detail="Too many remote redirects")
            next_url = urljoin(current.full_url, location)
            try:
                validate_remote_url(next_url)
                next_request = _redirect_request(current, response, next_url)
            finally:
                response.close()
            current = next_request
            redirects += 1
            continue

        if response.status >= 300:
            raise HTTPError(current.full_url, response.status, response.reason, response.headers, response)
        return response
