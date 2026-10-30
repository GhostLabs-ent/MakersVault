"""HTTP client for remote imports that never follows a redirect blindly.

Design constraints, in order of importance:

* **No redirect is followed automatically.** Every hop is validated for URL
  shape (http/https only, no embedded credentials, parseable port) and for the
  addresses its hostname resolves to *before* any socket is opened, so a 302 to
  ``127.0.0.1`` or ``169.254.169.254`` is refused while it is still a string.
* **The validated DNS answer is the one used to connect.** The socket is dialed
  to the pinned IP while TLS SNI and certificate verification stay bound to the
  URL hostname, so a resolver that changes its answer between validation and
  connect (DNS rebinding) cannot move the socket.
* **Redirect responses are attacker controlled.** Malformed ``Location`` values
  and unusable ports surface as 400 rather than a 500.
* **Limits:** ``timeout`` per request, ``max_redirects`` hops, and response
  bodies are not read here at all -- callers already cap them with
  ``IMPORT_HTML_MAX_BYTES`` and ``IMPORT_MAX_BYTES``.
* **Environment ``HTTP_PROXY``/``HTTPS_PROXY`` are deliberately ignored.** A
  proxy connects on our behalf, which defeats IP pinning. This is a behavior
  change compared with the urllib default.

The opener itself is stateless; pinned addresses live on the per-call request,
so a request object must never be reused across calls.
"""
import functools
import http.client
import socket
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from fastapi import HTTPException

from config import IMPORT_MAX_REDIRECTS, IMPORT_TIMEOUT_SECONDS
from url_utils import DEFAULT_PORTS, resolve_remote_url

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization"}
DROPPED_WITH_BODY = {"content-type", "content-length"}


class _PinnedConnectionMixin:
    """Dial the validated IP instead of letting HTTPConnection re-resolve."""

    def __init__(self, *args, pinned_ips: list[str], **kwargs):
        super().__init__(*args, **kwargs)
        self._pinned_ips = list(pinned_ips)
        # HTTPConnection.__init__ assigns the instance slot
        # ``self._create_connection = socket.create_connection``, which shadows
        # any subclass method of the same name, so the slot is rebound here.
        self._create_connection = self._connect_pinned

    def _connect_pinned(self, address, timeout, source_address):
        port = address[1]
        last_error = None
        for ip in self._pinned_ips:
            try:
                return socket.create_connection((ip, port), timeout, source_address)
            except OSError as err:
                last_error = err
        if last_error is not None:
            raise last_error
        raise OSError("No validated address to connect to")


class _PinnedHTTPConnection(_PinnedConnectionMixin, http.client.HTTPConnection):
    pass


class _PinnedHTTPSConnection(_PinnedConnectionMixin, http.client.HTTPSConnection):
    pass


class _PinnedHTTPHandler(HTTPHandler):
    def http_open(self, req):
        return self.do_open(functools.partial(_PinnedHTTPConnection, pinned_ips=req.pinned_ips), req)


class _PinnedHTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        # Only the context is forwarded: ``check_hostname`` was removed in 3.12,
        # and passing ``context`` alone keeps default certificate verification.
        return self.do_open(functools.partial(_PinnedHTTPSConnection, pinned_ips=req.pinned_ips), req, context=self._context)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PinnedRequest(Request):
    pinned_ips: list[str]


# The explicit ProxyHandler instance suppresses build_opener's default one,
# which would read HTTP(S)_PROXY from the environment and rewrite req.host in
# ``set_proxy`` while the pinned addresses still point at the origin. ``{}``
# registers no proxy at all.
_opener = build_opener(_PinnedHTTPHandler(), _PinnedHTTPSHandler(), _NoRedirectHandler(), ProxyHandler({}))


def safe_urlopen(request: Request, *, timeout: int = IMPORT_TIMEOUT_SECONDS, max_redirects: int = IMPORT_MAX_REDIRECTS):
    """Open ``request`` without following redirects, validating each hop first."""
    url = request.full_url
    for redirects in range(max_redirects + 1):
        try:
            request.pinned_ips = resolve_remote_url(request.full_url)
            return _opener.open(request, timeout=timeout)
        except HTTPError as err:
            if err.code not in REDIRECT_STATUSES:
                raise
            location = (err.headers.get("Location") if err.headers else "") or ""
            err.close()
            location = location.strip()
            if not location:
                raise HTTPException(status_code=400, detail="Redirect response is missing a Location header") from err
            if redirects >= max_redirects:
                raise HTTPException(status_code=400, detail="Too many redirects while fetching URL") from err
            try:
                url = urljoin(url, location)
                request = _build_redirect_request(request, url, err.code)
            except (ValueError, http.client.InvalidURL) as exc:
                # Location is attacker controlled: a malformed IPv6 literal or
                # URL must be a 400, not an unhandled exception.
                raise HTTPException(status_code=400, detail="Invalid redirect URL") from exc
        except (ValueError, http.client.InvalidURL) as err:
            raise HTTPException(status_code=400, detail="Invalid URL") from err
    raise HTTPException(status_code=400, detail="Too many redirects while fetching URL")


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is None:
        port = DEFAULT_PORTS.get(scheme, 0)
    return scheme, host, port


def _build_redirect_request(request: Request, next_url: str, status: int) -> _PinnedRequest:
    headers = {name: value for name, value in request.header_items() if name.lower() != "host"}
    method = request.get_method()
    data = request.data
    drops_body = method != "HEAD" and (status == 303 or (status in {301, 302} and method == "POST"))
    if drops_body:
        method = "GET"
        data = None
        headers = {name: value for name, value in headers.items() if name.lower() not in DROPPED_WITH_BODY}
    if _origin(request.full_url) != _origin(next_url):
        headers = {name: value for name, value in headers.items() if name.lower() not in SENSITIVE_HEADERS}
    return _PinnedRequest(next_url, data=data, headers=headers, method=method)
