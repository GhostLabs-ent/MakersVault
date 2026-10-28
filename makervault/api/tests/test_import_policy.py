"""Regression tests for Mf-vesa: the session cookie is scoped to the public
rate-limit workarounds, and a paid/gated URL never reaches the network.

Each test pins one half of the policy:

* ``test_cookie_attaches_only_for_credentialed_hosts`` - a cookie goes to the two
  credentialed resolvers and to nothing else, look-alike hosts included.
* ``test_credentialed_registry_is_closed`` - the privileged host set is an
  enumerated registry, so a third credentialed source is a reviewed edit.
* ``test_paid_and_gated_urls_are_refused`` / ``_free_public_urls_are_not_refused``
  - the UX check matches whole path segments and query keys, so "reorder" and
  "paid_note" stay free while "cart" does not.
* ``test_paid_import_issues_no_request_and_no_cookie`` and
  ``test_open_import_response_refuses_purchase_state_at_any_depth`` - the guard
  runs before any connection exists, in every import route and inside the fetch
  helper that HTML-discovered download URLs re-enter.
* ``test_import_request_has_no_purchase_or_payment_fields`` - the app has no
  purchase state to store, request or replay.
* ``test_import_path_never_logs_the_cookie`` - the modules holding the cookie
  value have no logger at all; ``test_failed_paid_free_import_never_echoes_the_cookie``
  pins the error path that turns an upstream failure into a response body.
"""

import logging
from pathlib import Path
from urllib.error import HTTPError

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import import_policy
import import_service
import main
from schemas import ImportProjectRequest, ImportRequest, ImportZipEntriesRequest, ImportZipExtractRequest

IMPORT_FIELDS = {"url", "title", "notes", "tags", "folder_id", "filename", "makerworld_cookie", "thingiverse_cookie"}

# The same credentialed body against a checkout URL, for every import route.
PAID_PAYLOAD = {"url": "https://makerworld.com/en/cart", "makerworld_cookie": "mw_session=SECRET"}

API_ROOT = Path(__file__).resolve().parents[1]
COOKIE_PATH_MODULES = (
    "import_service.py",
    "import_resolvers.py",
    "routers/imports.py",
    "import_policy.py",
    "safe_http.py",
)


def auth_header(client: TestClient) -> dict:
    """Bearer token, or empty when the app is running with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    "url,expects_cookie",
    [
        ("https://makerworld.com/en/models/1", True),
        ("https://www.makerworld.com/en/models/1", True),
        ("https://thingiverse.com/thing:1234", True),
        ("https://www.thingiverse.com/thing:1234", True),
        ("https://printables.com/model/1", False),
        ("https://evil-makerworld.com/en/models/1", False),
        ("https://makerworld.com.evil.io/en/models/1", False),
        ("https://notthingiverse.com/thing:1234", False),
        ("https://example.com/cube.stl", False),
        ("https://cdn.example.com/files/cube.stl", False),
        ("http://93.184.216.34/cube.stl", False),
    ],
)
def test_cookie_attaches_only_for_credentialed_hosts(monkeypatch, url, expects_cookie):
    # Both resolvers fall back to these env vars, so a contaminated env would
    # attach a cookie on a host that must never see one and flip the assertion.
    monkeypatch.delenv("MAKERWORLD_COOKIE", raising=False)
    monkeypatch.delenv("THINGIVERSE_COOKIE", raising=False)
    body = ImportRequest(url=url, makerworld_cookie="mw_session=SECRET", thingiverse_cookie="cf_clearance=SECRET")
    headers = import_service.import_request_headers(url, body)
    assert ("Cookie" in headers) is expects_cookie
    if not expects_cookie:
        assert not any("SECRET" in value for value in headers.values())


def test_credentialed_registry_is_closed():
    # Adding a third credentialed source must be a deliberate, reviewed edit:
    # this assertion is what makes it show up in review.
    assert set(import_policy.CREDENTIALED_HOST_MATCHERS) == {"makerworld", "thingiverse"}
    assert import_policy.credentialed_source_for("makerworld.com") == "makerworld"
    assert import_policy.credentialed_source_for("WWW.MakerWorld.com") == "makerworld"
    assert import_policy.credentialed_source_for("www.thingiverse.com") == "thingiverse"
    assert import_policy.credentialed_source_for("printables.com") is None
    assert import_policy.credentialed_source_for("evil-makerworld.com") is None
    assert import_policy.credentialed_source_for("makerworld.com.evil.io") is None
    assert import_policy.credentialed_source_for("") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://gumroad.com/l/xyz",
        "https://shop.gumroad.com/l/xyz",
        "https://makerworld.com/en/cart",
        "https://www.thingiverse.com/checkout",
        "https://example.com/orders/123",
        "https://example.com/purchase",
        "https://example.com/x?checkout=1",
        "https://example.com/cube.stl?order_id=9",
        "makerworld.com/en/payments",
    ],
)
def test_paid_and_gated_urls_are_refused(url):
    assert import_policy.purchase_state_reason(url)
    with pytest.raises(HTTPException) as excinfo:
        import_policy.refuse_paid_or_gated(url)
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == import_policy.PAID_IMPORT_DETAIL
    assert "supply these files yourself" in excinfo.value.detail


@pytest.mark.parametrize(
    "url",
    [
        "https://makerworld.com/en/models/1",
        "https://www.thingiverse.com/thing:1234",
        "https://www.printables.com/model/1",
        "https://cdn.example.com/files/cube.stl",
        "https://example.com/reorder/cube.stl",
        "https://example.com/cube.stl?paid_note=free",
        "https://example.invalid/cube.stl",
    ],
)
def test_free_public_urls_are_not_refused(url):
    # Whole-segment matching: "reorder" and "paid_note" contain a purchase word
    # but are not one, so they must not trip the guard.
    assert import_policy.purchase_state_reason(url) is None


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/import", PAID_PAYLOAD),
        ("/import/inspect", PAID_PAYLOAD),
        ("/import/zip/entries", PAID_PAYLOAD),
        ("/import/zip", {**PAID_PAYLOAD, "entries": ["cube.stl"]}),
    ],
)
def test_paid_import_issues_no_request_and_no_cookie(monkeypatch, path, payload):
    # Every import route must fail before any credentialed request exists.
    def refuse_to_open(*args, **kwargs):
        raise AssertionError("a paid import must not open a connection")

    monkeypatch.setattr(import_service, "safe_urlopen", refuse_to_open)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        res = client.post(path, json=payload, headers=auth_header(client))
    assert res.status_code == 403
    assert import_policy.PAID_IMPORT_DETAIL in res.text
    assert "SECRET" not in res.text


def test_open_import_response_refuses_purchase_state_at_any_depth(monkeypatch):
    # HTML-discovered download URLs re-enter this function, so the guard has to
    # live above the fetch, not only in the router.
    def refuse_to_open(*args, **kwargs):
        raise AssertionError("a paid import must not open a connection")

    monkeypatch.setattr(import_service, "safe_urlopen", refuse_to_open)
    url = "https://makerworld.com/en/checkout"
    body = ImportRequest(url=url, makerworld_cookie="S")
    with pytest.raises(HTTPException) as excinfo:
        import_service.open_import_response(url, body)
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == import_policy.PAID_IMPORT_DETAIL


def test_import_request_has_no_purchase_or_payment_fields():
    # The app has no purchase state to store, request or replay; this fails
    # loudly if a payment field is ever added to the import body.
    assert set(ImportRequest.model_fields) == IMPORT_FIELDS
    assert len(ImportRequest.model_fields) == 8, "the base import body keeps its eight fields"
    # The project-import body subclasses the same base, so it inherits the sweep.
    for request_model in (ImportProjectRequest, ImportZipEntriesRequest, ImportZipExtractRequest):
        added = set(request_model.model_fields) - IMPORT_FIELDS
        for field in added:
            assert not any(marker in field for marker in ("pay", "purch", "order", "price")), field


def test_import_path_never_logs_the_cookie(caplog):
    # Other modules (asset_service, audit) do log, which is why the behavioural
    # half asserts on the captured records rather than on the code alone.
    caplog.set_level(logging.DEBUG)
    secret_body = ImportRequest(
        url="https://makerworld.com/en/models/1",
        makerworld_cookie="mw_session=SECRET123",
        thingiverse_cookie="cf_clearance=SECRET123",
    )
    for url in ("https://makerworld.com/en/models/1", "https://www.thingiverse.com/thing:1234"):
        headers = import_service.import_request_headers(url, secret_body)
        assert "Cookie" in headers
    assert "SECRET123" not in caplog.text
    # Static guarantee: the module that holds the value has no logger to log it,
    # so adding one fails this test loudly.
    for name in COOKIE_PATH_MODULES:
        source = (API_ROOT / name).read_text().lower()
        assert "logging" not in source, name
        assert "logger" not in source, name


def test_failed_paid_free_import_never_echoes_the_cookie(monkeypatch, caplog):
    # A failed credentialed fetch must neither log nor echo the credential: the
    # router turns HTTPError.reason into the response detail, which is the
    # realistic way a value from the request could reach the body.
    caplog.set_level(logging.DEBUG)

    def skip_url_validation(url: str) -> str:
        """Skip URL validation, which resolves DNS - a network call."""
        return url

    def fail_the_fetch(*args, **kwargs):
        raise HTTPError("https://makerworld.com/en/models/1", 403, "Forbidden", {}, None)

    monkeypatch.setattr(main, "normalize_import_url", skip_url_validation)
    monkeypatch.setattr(import_service, "validate_remote_url", skip_url_validation)
    monkeypatch.setattr(import_service, "safe_urlopen", fail_the_fetch)
    payload = {
        "url": "https://makerworld.com/en/models/1",
        "makerworld_cookie": "mw_session=SECRET123",
        "thingiverse_cookie": "cf_clearance=SECRET123",
    }
    with TestClient(main.app, raise_server_exceptions=False) as client:
        res = client.post("/import", json=payload, headers=auth_header(client))
    assert res.status_code >= 400
    # The upstream reason still reaches the caller, so the assertions above
    # cannot pass because the failure happened somewhere else entirely.
    assert "Failed to fetch URL: Forbidden" in res.text
    assert "SECRET123" not in res.text
    assert "SECRET123" not in caplog.text
