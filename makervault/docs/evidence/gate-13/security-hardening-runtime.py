"""Offline proof of the installed outbound policy; no application startup or DNS."""
import importlib.metadata
import json
import platform

from fastapi import HTTPException
from url_utils import remote_url_origin


cases = {
    "https://EXAMPLE.com./model.stl": ("https", "example.com", 443),
    "https://bücher.example:8443/model.stl": ("https", "xn--bcher-kva.example", 8443),
    "https://xn--bcher-kva.example/model.stl": ("https", "xn--bcher-kva.example", 443),
    "https://faß.example/model.stl": ("https", "xn--fa-hia.example", 443),
    "https://fass.example/model.stl": ("https", "fass.example", 443),
    "https://[2606:4700:4700::1111]/model.stl": ("https", "2606:4700:4700::1111", 443),
}
accepted = {}
for value, expected in cases.items():
    observed = remote_url_origin(value)
    assert observed == expected
    accepted[value] = observed
rejected = {}
for host in ("ẞ.example", "K.example", "example.com..", "localhost", "[::1]", "ab\u00adcd.example"):
    try:
        remote_url_origin(f"https://{host}/model.stl")
    except HTTPException as error:
        assert error.status_code == 400
        rejected[host] = error.status_code
    else:
        raise AssertionError("Invalid fixture hostname accepted")
packages = {}
for name in ("idna", "httpx2", "httpcore2", "pytest"):
    try:
        packages[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        packages[name] = None
assert packages == {"idna":"3.18", "httpx2":None, "httpcore2":None, "pytest":None}
print(json.dumps({"status":"passed", "machine":platform.machine(), "python":platform.python_version(),
    "packages":packages, "accepted":accepted, "rejected":rejected,
    "scope":"No DNS, network, TLS handshake, application startup or vault data"}, sort_keys=True))
