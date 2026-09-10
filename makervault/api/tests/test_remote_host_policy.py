"""Offline hostname/transport regressions; no public DNS or network traffic."""
import io
import socket
import ssl
from urllib.error import URLError
from urllib.request import Request

import pytest
from fastapi import HTTPException

import safe_http
import url_utils
from http_security import host_is_allowed, resolve_trusted_hosts
from passkey_config import PasskeyConfigurationError, load_passkey_config


PUBLIC_IP = "93.184.216.34"
PUBLIC_IPV6 = "2606:4700:4700::1111"


@pytest.fixture
def dns(monkeypatch):
    calls = []

    def resolve(host, port, **kwargs):
        calls.append((host, port, kwargs))
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC_IP, port))]

    monkeypatch.setattr(url_utils.socket, "getaddrinfo", resolve)
    return calls


@pytest.mark.parametrize("hostname,expected", [
    ("EXAMPLE.com", "example.com"),
    ("example.com.", "example.com"),
    ("bücher.example", "xn--bcher-kva.example"),
    ("bücher.example.", "xn--bcher-kva.example"),
    ("XN--BCHER-KVA.EXAMPLE", "xn--bcher-kva.example"),
    ("faß.example", "xn--fa-hia.example"),
    ("xn--fa-hia.example", "xn--fa-hia.example"),
])
def test_valid_dns_names_use_one_canonical_identity(hostname, expected, dns):
    original = f"https://{hostname}:8443/model.stl?part=1"
    resolved = url_utils.resolve_remote_target(original)
    assert resolved.host == expected
    assert resolved.url == original  # No stored URL/path rewrite.
    assert dns[0][0:2] == (expected, 8443)
    assert url_utils.remote_url_origin(original) == ("https", expected, 8443)
    assert len(dns) == 1  # Origin comparison never resolves again.


def test_unicode_identity_does_not_casefold_to_different_domain(dns):
    unicode_host = url_utils.resolve_remote_target("https://faß.example/model.stl")
    ascii_host = url_utils.resolve_remote_target("https://fass.example/model.stl")
    assert unicode_host.host == "xn--fa-hia.example"
    assert unicode_host.host != ascii_host.host
    assert [call[0] for call in dns] == ["xn--fa-hia.example", "fass.example"]


@pytest.mark.parametrize("hostname", [
    "ẞ.example", "K.example", "BÜCHER.example",  # Reject Unicode case mapping.
    "bu\u0308cher.example",  # Reject non-NFC, not a silent identity rewrite.
    "ab\u00adcd.example", "ab\u200bcd.example", "ab\u200dcd.example",
    "example。com", "ｅxample.com", "💩.example",
    "aא.example", "xn--.example", "xn--invalid-.example",
    "example.com..", ".example.com", "example..com", "bad_name.example",
    "-bad.example", "bad-.example", "ab--cd.example", "bad name.example", "bad\\name.example",
    "%65xample.com", "example%00.com", "[2606:4700:4700::1111%eth0]",
    "[2606:4700:4700::1111]suffix", "[2606:4700:4700::1111]:",
    "example.com:", "example.com:１２３", "example.com:443:80",
    "a" * 64 + ".example", ".".join(["a" * 63] * 4),
])
def test_malformed_host_rejected_before_dns(hostname, monkeypatch):
    def forbidden_dns(*args, **kwargs):
        pytest.fail("Malformed hostname reached DNS")

    monkeypatch.setattr(url_utils.socket, "getaddrinfo", forbidden_dns)
    with pytest.raises(HTTPException) as error:
        url_utils.resolve_remote_target(f"https://{hostname}/model.stl")
    assert error.value.status_code == 400


@pytest.mark.parametrize("url", [
    "https://@example.com/model.stl", "https://:@example.com/model.stl",
    "https://user:password@example.com/model.stl",
    "\nhttps://example.com/model.stl", "https://exa\tmple.com/model.stl",
    "https://example.com/model.stl\r\nX-Fixture: value",
])
def test_raw_url_rejected_before_request_can_strip_characters(url, monkeypatch):
    monkeypatch.setattr(safe_http, "_request_once", lambda *args: pytest.fail("Invalid URL connected"))
    with pytest.raises(HTTPException) as error:
        safe_http.safe_urlopen(url)
    assert error.value.status_code == 400


@pytest.mark.parametrize("hostname", ["LOCALHOST.", "printer.local.", "home.arpa.", "private.home.arpa."])
def test_local_suffixes_rejected_before_dns(hostname, dns):
    with pytest.raises(HTTPException, match="Local addresses"):
        url_utils.resolve_remote_target(f"https://{hostname}/model.stl")
    assert dns == []


@pytest.mark.parametrize("authority,expected,family", [
    (PUBLIC_IP, PUBLIC_IP, socket.AF_INET),
    (PUBLIC_IP + ".", PUBLIC_IP, socket.AF_INET),
    ("[2606:4700:4700:0:0:0:0:1111]", PUBLIC_IPV6, socket.AF_INET6),
])
def test_public_literals_preserve_numeric_resolution(authority, expected, family, monkeypatch):
    calls = []

    def resolve(host, port, **kwargs):
        calls.append((host, kwargs))
        address = (expected, port) if family == socket.AF_INET else (expected, port, 0, 0)
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", address)]

    monkeypatch.setattr(url_utils.socket, "getaddrinfo", resolve)
    resolved = url_utils.resolve_remote_target(f"https://{authority}/model.stl")
    assert resolved.host == expected
    assert calls[0][0] == expected
    assert calls[0][1]["flags"] == socket.AI_NUMERICHOST


@pytest.mark.parametrize("authority", ["127.0.0.1.", "[::1]", "[::ffff:127.0.0.1]", "[fe80::1]"])
def test_private_literals_still_rejected(authority, dns):
    with pytest.raises(HTTPException, match="Local addresses"):
        url_utils.resolve_remote_target(f"https://{authority}/model.stl")
    assert dns == []


def test_unicode_mixed_dns_answer_fails_before_connection(monkeypatch):
    hosts = []

    def resolve(host, port, **kwargs):
        hosts.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))
                for ip in (PUBLIC_IP, "10.0.0.5")]

    monkeypatch.setattr(url_utils.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(safe_http, "_request_once", lambda *args: pytest.fail("Mixed DNS connected"))
    with pytest.raises(HTTPException, match="Local addresses"):
        safe_http.safe_urlopen("https://bücher.example/model.stl")
    assert hosts == ["xn--bcher-kva.example"]


class Response:
    def __init__(self, location):
        self.status = 302 if location else 200
        self.reason = "fixture"
        self.headers = {"Location": location} if location else {}
        self.closed = False

    def close(self):
        self.closed = True


@pytest.mark.parametrize("start,destination,keep_credentials", [
    ("https://bücher.example/start", "https://xn--bcher-kva.example/final", True),
    ("https://XN--BCHER-KVA.EXAMPLE.:443/start", "https://bücher.example/final", True),
    ("https://faß.example/start", "https://fass.example/final", False),
    ("https://bücher.example/start", "https://bücher.example:8443/final", False),
    ("https://bücher.example/start", "https://other.example/final", False),
])
def test_redirect_credentials_follow_canonical_origin(start, destination, keep_credentials, dns, monkeypatch):
    requests = []
    response = Response(destination)

    def request_once(request, resolved, timeout):
        requests.append(request)
        return response if len(requests) == 1 else Response(None)

    monkeypatch.setattr(safe_http, "_request_once", request_once)
    safe_http.safe_urlopen(Request(start, headers={
        "Authorization": "Bearer fixture", "Cookie": "fixture=value",
        "Proxy-Authorization": "fixture", "Host": "wrong.example", "Accept": "model/stl",
    }))
    headers = {key.lower(): value for key, value in requests[1].header_items()}
    for name in ("authorization", "cookie", "proxy-authorization"):
        assert (name in headers) == keep_credentials
    assert "host" not in headers
    assert headers["accept"] == "model/stl"
    assert response.closed
    assert len(dns) == 2  # Every hop validates a fresh DNS answer.


@pytest.mark.parametrize("destination,message", [
    ("https://ẞ.example/model.stl", "Invalid URL host"),
    ("http://xn--bcher-kva.example/model.stl", "downgrade"),
])
def test_invalid_unicode_and_downgrade_redirects_close_response(destination, message, dns, monkeypatch):
    response = Response(destination)
    monkeypatch.setattr(safe_http, "_request_once", lambda *args: response)
    with pytest.raises(HTTPException, match=message):
        safe_http.safe_urlopen("https://bücher.example/start")
    assert response.closed
    assert len(dns) == 1


def test_dns_host_header_sni_and_connected_peer_agree(dns, monkeypatch):
    sent, peers, server_names = [], [], []

    class Socket:
        def settimeout(self, timeout):
            pass

        def connect(self, sockaddr):
            peers.append(sockaddr)

        def sendall(self, data):
            sent.append(data)

        def makefile(self, mode):
            return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

        def close(self):
            pass

    class Context:
        verify_mode = ssl.CERT_REQUIRED
        check_hostname = True

        def wrap_socket(self, sock, *, server_hostname):
            server_names.append(server_hostname)
            return sock

    monkeypatch.setattr(safe_http.socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(safe_http.ssl, "create_default_context", Context)
    with safe_http.safe_urlopen(Request("https://bücher.example.:8443/model.stl", headers={"Host": "wrong.example"})) as response:
        assert response.status == 200
    assert dns[0][0] == server_names[0] == "xn--bcher-kva.example"
    assert peers == [(PUBLIC_IP, 8443)]
    wire = b"".join(sent)
    assert b"Host: xn--bcher-kva.example:8443\r\n" in wire
    assert b"wrong.example" not in wire
    assert len(dns) == 1


def test_tls_failure_is_not_downgraded_or_retried_without_validation(dns, monkeypatch):
    closed = []

    class Socket:
        def close(self):
            closed.append(True)

    class Context:
        def wrap_socket(self, sock, *, server_hostname):
            assert server_hostname == "xn--bcher-kva.example"
            raise ssl.SSLCertVerificationError("fixture rejection")

    monkeypatch.setattr(safe_http, "_connected_socket", lambda *args: Socket())
    monkeypatch.setattr(safe_http.ssl, "create_default_context", Context)
    with pytest.raises(URLError):
        safe_http.safe_urlopen("https://bücher.example/model.stl")
    assert closed == [True]
    assert len(dns) == 1


def test_outbound_idna_does_not_broaden_inbound_host_or_passkey_policy():
    hosts = resolve_trusted_hosts({"TRUSTED_HOSTS": "xn--bcher-kva.example"})
    assert host_is_allowed("XN--BCHER-KVA.EXAMPLE:443", hosts)
    assert not host_is_allowed("bücher.example", hosts)
    assert not host_is_allowed("other.example", hosts)
    environment = {"MAKERSVAULT_ENV": "test", "WEBAUTHN_RP_ID": "xn--bcher-kva.example",
                   "WEBAUTHN_ORIGIN": "https://xn--bcher-kva.example"}
    assert load_passkey_config(environment).origin == "https://xn--bcher-kva.example"
    with pytest.raises(PasskeyConfigurationError):
        load_passkey_config({**environment, "WEBAUTHN_ORIGIN": "https://bücher.example"})
