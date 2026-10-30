"""Adversarial tests for URL-import SSRF defenses.

Every test names a bypass that worked when imports went through urllib's
default client: it followed redirects to loopback or the metadata service and
re-resolved the hostname at connect time. Nothing here touches a real network;
a fake resolver and a fake connector route the fake hostnames to local
``RoutingServer`` instances.
"""
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request

import pytest
from fastapi import HTTPException

import import_service
from safe_http import safe_urlopen
from schemas import ImportRequest

# RFC 5737/TEST-NET ranges are classified as non-global by ``ipaddress`` and are
# rejected by ``is_blocked_ip``, so the fake hosts use genuine global addresses.
PUBLIC_IP = "93.184.216.34"
SECOND_PUBLIC_IP = "8.8.8.8"
THIRD_PUBLIC_IP = "1.1.1.1"


class _RoutingHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.record(method, self.path, dict(self.headers), body)
        status, headers, payload = self.server.route_table.get(self.path, (404, {}, b""))
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(payload)

    def log_message(self, *args):
        pass


class RoutingServer:
    """Loopback HTTP server with a per-path route table and a request log."""

    def __init__(self, routes=None):
        self.route_table = dict(routes or {})
        self.requests = []
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _RoutingHandler)
        self._httpd.daemon_threads = True
        self._httpd.route_table = self.route_table
        self._httpd.record = self._record
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    @property
    def port(self):
        return self._httpd.server_address[1]

    def route(self, path, status=200, headers=None, body=b""):
        self.route_table[path] = (status, dict(headers or {}), body)

    def _record(self, method, path, headers, body):
        self.requests.append((method, path, headers, body))

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class _FakeNetwork:
    """Fake resolver plus fake connector, keyed on hostnames and (ip, port)."""

    def __init__(self):
        self.hosts = {}
        self.mapping = {}
        self.attempts = []
        self.lookups = []
        self.on_lookup = []

    def pin(self, host, ip, server):
        self.hosts[host] = [ip]
        self.mapping[(ip, server.port)] = server.port

    def url(self, host, server, path="/"):
        return f"http://{host}:{server.port}{path}"


def _with_credentials(url):
    return url.replace("://", "://user:pass@", 1)


@pytest.fixture
def network(monkeypatch):
    fake = _FakeNetwork()
    real_getaddrinfo = socket.getaddrinfo
    real_create_connection = socket.create_connection

    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host not in fake.hosts:
            return real_getaddrinfo(host, port, *args, **kwargs)
        fake.lookups.append(host)
        infos = []
        for ip in list(fake.hosts[host]):
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            infos.append((family, socket.SOCK_STREAM, 6, "", (ip, port or 0)))
        for callback in fake.on_lookup:
            callback(host)
        return infos

    def fake_create_connection(address, *args, **kwargs):
        fake.attempts.append((address[0], address[1]))
        target = fake.mapping.get((address[0], address[1]))
        if target is None:
            raise OSError(f"no route for {address}")
        return real_create_connection(("127.0.0.1", target), *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    return fake


def _headers_of(server, index=-1):
    headers = server.requests[index][2]
    return {key.lower(): value for key, value in headers.items()}


def test_redirect_to_loopback_is_refused_before_connect(network):
    private = RoutingServer({"/secret": (200, {}, b"secret")})
    public = RoutingServer({"/start": (302, {"Location": f"http://127.0.0.1:{private.port}/secret"}, b"")})
    network.pin("one.example", PUBLIC_IP, public)
    with public, private:
        with pytest.raises(HTTPException) as excinfo:
            safe_urlopen(Request(network.url("one.example", public, "/start")))
    assert excinfo.value.status_code == 400
    assert private.requests == []
    assert all(port != private.port for _ip, port in network.attempts)


def test_redirect_to_metadata_address_is_refused_before_connect(network):
    public = RoutingServer({"/start": (302, {"Location": "http://169.254.169.254/latest/meta-data/"}, b"")})
    network.pin("one.example", PUBLIC_IP, public)
    with public:
        with pytest.raises(HTTPException) as excinfo:
            safe_urlopen(Request(network.url("one.example", public, "/start")))
    assert excinfo.value.status_code == 400
    assert network.attempts == [(PUBLIC_IP, public.port)]


def test_redirect_chain_within_limit_returns_final_response(network):
    server = RoutingServer()
    server.route("/a", 302, {"Location": "/b"})
    server.route("/b", 302, {"Location": "/c"})
    server.route("/c", 200, {}, b"final-body")
    network.pin("one.example", PUBLIC_IP, server)
    with server:
        resp = safe_urlopen(Request(network.url("one.example", server, "/a")))
        assert resp.read() == b"final-body"
    assert resp.status == 200
    assert resp.geturl() == network.url("one.example", server, "/c")
    assert [entry[1] for entry in server.requests] == ["/a", "/b", "/c"]


def test_redirect_chain_exceeding_limit_is_refused(network):
    server = RoutingServer()
    server.route("/a", 302, {"Location": "/b"})
    server.route("/b", 302, {"Location": "/c"})
    server.route("/c", 200, {}, b"unreachable")
    network.pin("one.example", PUBLIC_IP, server)
    with server:
        with pytest.raises(HTTPException) as excinfo:
            safe_urlopen(Request(network.url("one.example", server, "/a")), max_redirects=1)
    assert excinfo.value.status_code == 400
    assert "Too many redirects" in excinfo.value.detail
    assert [entry[1] for entry in server.requests] == ["/a", "/b"]


def test_initial_url_with_credentials_is_refused_before_connect(network):
    server = RoutingServer({"/": (200, {}, b"never")})
    network.pin("one.example", PUBLIC_IP, server)
    with server:
        with pytest.raises(HTTPException) as excinfo:
            safe_urlopen(Request(_with_credentials(network.url("one.example", server, "/"))))
    assert excinfo.value.status_code == 400
    assert network.attempts == []
    assert server.requests == []


def test_redirect_location_with_credentials_is_refused_before_connect(network):
    landing = RoutingServer({"/landing": (200, {}, b"never")})
    origin = RoutingServer()
    network.pin("one.example", PUBLIC_IP, origin)
    network.pin("two.example", SECOND_PUBLIC_IP, landing)
    origin.route("/start", 302, {"Location": _with_credentials(network.url("two.example", landing, "/landing"))})
    with origin, landing:
        with pytest.raises(HTTPException) as excinfo:
            safe_urlopen(Request(network.url("one.example", origin, "/start")))
    assert excinfo.value.status_code == 400
    assert landing.requests == []
    assert all(port != landing.port for _ip, port in network.attempts)


def test_redirect_to_non_http_scheme_is_refused(network):
    origin = RoutingServer({"/start": (302, {"Location": "file:///etc/passwd"}, b"")})
    network.pin("one.example", PUBLIC_IP, origin)
    with origin:
        with pytest.raises(HTTPException) as excinfo:
            safe_urlopen(Request(network.url("one.example", origin, "/start")))
    assert excinfo.value.status_code == 400
    assert network.attempts == [(PUBLIC_IP, origin.port)]


def test_redirect_with_invalid_port_is_rejected_as_bad_request(network):
    origin = RoutingServer({"/start": (302, {"Location": "http://one.example:99999/x"}, b"")})
    network.pin("one.example", PUBLIC_IP, origin)
    with origin:
        with pytest.raises(HTTPException) as excinfo:
            safe_urlopen(Request(network.url("one.example", origin, "/start")))
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Invalid URL port"


def test_connection_is_pinned_to_validated_ip_when_dns_changes(network):
    server = RoutingServer({"/ok": (200, {}, b"ok")})
    network.pin("one.example", PUBLIC_IP, server)

    def rebind(host):
        if host == "one.example":
            network.hosts["one.example"] = ["127.0.0.1"]

    network.on_lookup.append(rebind)
    with server:
        resp = safe_urlopen(Request(network.url("one.example", server, "/ok")))
        assert resp.read() == b"ok"
    assert network.lookups.count("one.example") == 1
    assert network.attempts == [(PUBLIC_IP, server.port)]
    assert ("127.0.0.1", server.port) not in network.attempts


def test_cross_origin_redirect_strips_cookie_and_authorization(network):
    landing = RoutingServer({"/landing": (200, {}, b"ok")})
    origin = RoutingServer()
    network.pin("one.example", PUBLIC_IP, origin)
    network.pin("two.example", SECOND_PUBLIC_IP, landing)
    origin.route("/cred", 302, {"Location": network.url("two.example", landing, "/landing")})
    request = Request(
        network.url("one.example", origin, "/cred"),
        headers={"Cookie": "session=1", "Authorization": "Bearer token"},
    )
    with origin, landing:
        resp = safe_urlopen(request)
        assert resp.read() == b"ok"
    landing_headers = _headers_of(landing)
    assert "cookie" not in landing_headers
    assert "authorization" not in landing_headers
    origin_headers = _headers_of(origin)
    assert origin_headers["cookie"] == "session=1"
    assert origin_headers["authorization"] == "Bearer token"


def test_same_origin_redirect_preserves_cookie_and_authorization(network):
    server = RoutingServer()
    server.route("/a", 302, {"Location": "/b"})
    server.route("/b", 200, {}, b"ok")
    network.pin("one.example", PUBLIC_IP, server)
    request = Request(network.url("one.example", server, "/a"), headers={"Cookie": "session=1", "Authorization": "Bearer token"})
    with server:
        resp = safe_urlopen(request)
        assert resp.read() == b"ok"
    final_headers = _headers_of(server)
    assert final_headers["cookie"] == "session=1"
    assert final_headers["authorization"] == "Bearer token"


def test_redirect_method_semantics(network):
    dest_302 = RoutingServer({"/landing": (200, {}, b"landed-302")})
    dest_307 = RoutingServer({"/landing": (200, {}, b"landed-307")})
    origin = RoutingServer()
    network.pin("one.example", PUBLIC_IP, origin)
    network.pin("two.example", SECOND_PUBLIC_IP, dest_302)
    network.pin("three.example", THIRD_PUBLIC_IP, dest_307)
    origin.route("/post302", 302, {"Location": network.url("two.example", dest_302, "/landing")})
    origin.route("/post307", 307, {"Location": network.url("three.example", dest_307, "/landing")})
    with origin, dest_302, dest_307:
        first = safe_urlopen(Request(network.url("one.example", origin, "/post302"), data=b"payload", method="POST"))
        assert first.read() == b"landed-302"
        second = safe_urlopen(Request(network.url("one.example", origin, "/post307"), data=b"payload", method="POST"))
        assert second.read() == b"landed-307"
    assert dest_302.requests[0][0] == "GET"
    assert dest_302.requests[0][3] == b""
    assert dest_307.requests[0][0] == "POST"
    assert dest_307.requests[0][3] == b"payload"


def test_non_redirect_http_error_is_raised(network):
    server = RoutingServer({"/missing": (404, {}, b"nope")})
    network.pin("one.example", PUBLIC_IP, server)
    with server:
        with pytest.raises(HTTPError) as excinfo:
            safe_urlopen(Request(network.url("one.example", server, "/missing")))
    assert excinfo.value.code == 404


def test_environment_proxy_is_ignored(network, monkeypatch):
    server = RoutingServer({"/ok": (200, {}, b"ok")})
    network.pin("one.example", PUBLIC_IP, server)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    request = Request(network.url("one.example", server, "/ok"))
    with server:
        resp = safe_urlopen(request)
        assert resp.read() == b"ok"
    assert network.attempts == [(PUBLIC_IP, server.port)]
    # The environment is visible to urllib's default proxy handler, so a
    # default-opener fetch would have gone to the bogus proxy instead.
    assert ProxyHandler().proxies
    assert not request.has_proxy()


def test_import_service_refuses_private_redirect(network):
    private = RoutingServer({"/secret": (200, {}, b"secret")})
    public = RoutingServer()
    network.pin("one.example", PUBLIC_IP, public)
    public.route("/page", 302, {"Location": f"http://127.0.0.1:{private.port}/secret"})
    url = network.url("one.example", public, "/page")
    with public, private:
        with pytest.raises(HTTPException) as excinfo:
            import_service.open_import_response(url, ImportRequest(url=url))
    assert excinfo.value.status_code == 400
    assert private.requests == []


def test_redirect_with_malformed_location_is_rejected_as_bad_request(network):
    # urllib's redirect handler parses Location before our no-redirect hook runs,
    # so a broken IPv6 literal surfaces through the ValueError -> 400 mapping.
    origin = RoutingServer({"/start": (302, {"Location": "http://[::1/x"}, b"")})
    network.pin("one.example", PUBLIC_IP, origin)
    with origin:
        with pytest.raises(HTTPException) as excinfo:
            safe_urlopen(Request(network.url("one.example", origin, "/start")))
    assert excinfo.value.status_code == 400
    assert network.attempts == [(PUBLIC_IP, origin.port)]


def test_mixed_dns_answer_with_private_address_is_refused_before_connect(network):
    server = RoutingServer({"/ok": (200, {}, b"never")})
    network.pin("one.example", PUBLIC_IP, server)
    network.hosts["one.example"] = [PUBLIC_IP, "127.0.0.1"]
    with server:
        with pytest.raises(HTTPException) as excinfo:
            safe_urlopen(Request(network.url("one.example", server, "/ok")))
    assert excinfo.value.status_code == 400
    assert network.attempts == []
    assert server.requests == []
