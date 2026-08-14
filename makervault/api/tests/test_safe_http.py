import ipaddress
import socket
from pathlib import Path
from urllib.request import Request

import pytest
from fastapi import HTTPException

import safe_http
import url_utils
from url_utils import ResolvedAddress, ResolvedTarget


PUBLIC_IPV4 = "93.184.216.34"


class FakeResponse:
    def __init__(self, status: int, location: str | None = None):
        self.status = status
        self.reason = "test response"
        self.headers = {"Location": location} if location else {}
        self.closed = False

    def close(self) -> None:
        self.closed = True


def target(url: str) -> ResolvedTarget:
    parsed_host = url.split("/", 3)[2].split(":", 1)[0]
    address = ResolvedAddress(
        socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        (PUBLIC_IPV4, 443),
        ipaddress.ip_address(PUBLIC_IPV4),
    )
    return ResolvedTarget(url, "https", parsed_host, 443, (address,))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/model.stl",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/model.stl",
        "http://[::1]/model.stl",
        "http://0.0.0.0/model.stl",
        "http://localhost./model.stl",
        "http://printer.local/model.stl",
    ],
)
def test_local_and_special_use_targets_are_rejected(url) -> None:
    with pytest.raises(HTTPException, match="Local addresses"):
        url_utils.resolve_remote_target(url)


def test_mixed_public_private_dns_answer_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        url_utils.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC_IPV4, 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.5", 443)),
        ],
    )

    with pytest.raises(HTTPException, match="Local addresses"):
        url_utils.resolve_remote_target("https://mixed.example/model.3mf")


@pytest.mark.parametrize(
    "url, message",
    [
        ("ftp://public.example/model.stl", "http:// or https://"),
        ("https://user:secret@public.example/model.stl", "Credentials"),
        ("https://public.example:70000/model.stl", "Invalid URL"),
        ("https://public.example/model.stl\nHost: localhost", "Invalid URL"),
    ],
)
def test_invalid_url_authority_and_control_characters_are_rejected(url, message) -> None:
    with pytest.raises(HTTPException, match=message):
        url_utils.validate_remote_url(url)


def test_validated_numeric_address_is_the_connected_peer(monkeypatch) -> None:
    resolution_calls = []

    def changing_dns(*_args, **_kwargs):
        resolution_calls.append(True)
        answer = PUBLIC_IPV4 if len(resolution_calls) == 1 else "127.0.0.1"
        port = _args[1]
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (answer, port))]

    connected = []

    class FakeSocket:
        def settimeout(self, _timeout):
            pass

        def connect(self, sockaddr):
            connected.append(sockaddr)

        def close(self):
            pass

    monkeypatch.setattr(url_utils.socket, "getaddrinfo", changing_dns)
    resolved = url_utils.resolve_remote_target("http://changing.example/model.stl")
    monkeypatch.setattr(safe_http.socket, "socket", lambda *_args: FakeSocket())

    safe_http._connected_socket(resolved.addresses[0], 5)

    assert len(resolution_calls) == 1
    assert connected == [(PUBLIC_IPV4, 80)]


def test_redirect_to_private_dns_is_rejected_before_connection(monkeypatch) -> None:
    def dns(host, port, **_kwargs):
        answer = PUBLIC_IPV4 if host == "public.example" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (answer, port))]

    requests = []

    def request_once(request, resolved, _timeout):
        requests.append((request, resolved))
        return FakeResponse(302, "http://private.example/secret")

    monkeypatch.setattr(url_utils.socket, "getaddrinfo", dns)
    monkeypatch.setattr(safe_http, "_request_once", request_once)

    with pytest.raises(HTTPException, match="Local addresses"):
        safe_http.safe_urlopen("http://public.example/model.stl")

    assert len(requests) == 1


def test_cross_origin_redirect_strips_credentials(monkeypatch) -> None:
    requests = []
    responses = [FakeResponse(302, "https://cdn.example/model.3mf"), FakeResponse(200)]
    monkeypatch.setattr(safe_http, "resolve_remote_target", target)

    def request_once(request, _target, _timeout):
        requests.append(request)
        return responses.pop(0)

    monkeypatch.setattr(safe_http, "_request_once", request_once)
    request = Request(
        "https://source.example/download",
        headers={
            "Authorization": "Bearer secret",
            "Cookie": "session=secret",
            "Host": "attacker.example",
            "Accept": "application/octet-stream",
        },
    )

    result = safe_http.safe_urlopen(request)
    redirected_headers = {key.lower(): value for key, value in requests[1].header_items()}

    assert result.status == 200
    assert "authorization" not in redirected_headers
    assert "cookie" not in redirected_headers
    assert "host" not in redirected_headers
    assert redirected_headers["accept"] == "application/octet-stream"


def test_redirect_method_rules_and_relative_location(monkeypatch) -> None:
    requests = []
    responses = [FakeResponse(302, "/finished"), FakeResponse(200)]
    monkeypatch.setattr(safe_http, "resolve_remote_target", target)

    def request_once(request, _target, _timeout):
        requests.append(request)
        return responses.pop(0)

    monkeypatch.setattr(safe_http, "_request_once", request_once)
    result = safe_http.safe_urlopen(
        Request(
            "https://source.example/start",
            data=b"payload",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    )

    assert result.status == 200
    assert requests[1].full_url == "https://source.example/finished"
    assert requests[1].get_method() == "GET"
    assert requests[1].data is None
    assert "content-type" not in {key.lower() for key, _ in requests[1].header_items()}


def test_https_downgrade_and_redirect_limit_fail_closed(monkeypatch) -> None:
    downgrade = FakeResponse(302, "http://public.example/model.stl")
    monkeypatch.setattr(safe_http, "resolve_remote_target", target)
    monkeypatch.setattr(safe_http, "_request_once", lambda *_args: downgrade)

    with pytest.raises(HTTPException, match="downgrade"):
        safe_http.safe_urlopen("https://public.example/model.stl")
    assert downgrade.closed

    excessive = FakeResponse(302, "/again")
    monkeypatch.setattr(safe_http, "_request_once", lambda *_args: excessive)
    with pytest.raises(HTTPException, match="Too many"):
        safe_http.safe_urlopen("https://public.example/model.stl", max_redirects=0)
    assert excessive.closed


def test_all_import_requests_use_safe_transport() -> None:
    api_root = Path(__file__).resolve().parents[1]
    for filename in ("import_service.py", "import_resolvers.py"):
        source = (api_root / filename).read_text(encoding="utf-8")
        assert "urlopen(" not in source.replace("safe_urlopen(", "")
