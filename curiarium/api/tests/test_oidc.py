"""OIDC / SSO login (Mf-4c24): the flow, the trust boundaries and the refusals.

Every test here patches the two outbound seams (`oidc._http_get_json` and
`oidc._http_post_form_json`); no test opens a socket. The provider is a small
in-process object that signs id_tokens with a throwaway RSA key, so the real
verification path (pinned algorithm, JWKS lookup, issuer/audience/nonce) runs
exactly as it does in production.

The state cookie is `Secure`, so httpx deliberately will not replay it over
`http://testserver`; the callback helpers pass it explicitly, which is also what
lets a test drop or mismatch it on purpose.
"""

import json
import logging
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from argon2 import PasswordHasher
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

import accounts
import audit
import auth
import config
import login_throttle as login_throttle_module
import main
import oidc
from db import engine
from migrations import run_migrations
from models import AuditEvent, OidcIdentity, User, UserSession

ISSUER = "https://idp.example.com"
CLIENT_ID = "vault-client"
CLIENT_SECRET = "client-secret"
PUBLIC_URL = "https://vault.example.com"
AUTHORIZE_ENDPOINT = f"{ISSUER}/authorize"
TOKEN_ENDPOINT = f"{ISSUER}/token"
JWKS_URI = f"{ISSUER}/jwks"
KID = "test-signing-key-1"

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_JWK = jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key(), as_dict=True)
PUBLIC_JWK.update({"kid": KID, "alg": "RS256", "use": "sig"})
JWKS = {"keys": [PUBLIC_JWK]}
# A key the JWKS does not publish: a token signed with it must be refused on the
# signature even though its claims are otherwise perfect.
OTHER_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


# --- fixtures ---------------------------------------------------------------


def truncate_accounts() -> None:
    """Remove every account, session and SSO binding; audit rows stay (append-only)."""
    with Session(engine) as db:
        db.execute(delete(OidcIdentity))
        db.execute(delete(UserSession))
        db.execute(delete(User))
        db.commit()


@pytest.fixture(autouse=True)
def clean_accounts():
    """Start and finish every test without accounts and without OIDC state."""
    run_migrations(engine)
    truncate_accounts()
    login_throttle_module.limiter.reset()
    oidc.reset()
    yield
    truncate_accounts()
    login_throttle_module.limiter.reset()
    oidc.reset()


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use argon2's floor parameters; nothing here asserts anything about hashing."""
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture()
def client():
    with TestClient(main.app) as test_client:
        yield test_client


# --- the mock provider ------------------------------------------------------


class MockProvider:
    """A stateless-enough IdP: discovery, JWKS and a signed id_token per exchange."""

    def __init__(self, *, claims_overrides: dict | None = None, alg: str = "RS256") -> None:
        self.claims = dict(claims_overrides or {})
        self.alg = alg
        self.discovery = {
            "issuer": ISSUER,
            "authorization_endpoint": AUTHORIZE_ENDPOINT,
            "token_endpoint": TOKEN_ENDPOINT,
            "jwks_uri": JWKS_URI,
        }
        self.discovery_calls = 0
        self.jwks_calls = 0
        self.token_calls = 0
        self.token_form: dict | None = None
        self.last_id_token: str | None = None
        self.nonce = ""

    def get_json(self, url: str) -> dict:
        if url == f"{ISSUER}/.well-known/openid-configuration":
            self.discovery_calls += 1
            return self.discovery
        if url == JWKS_URI:
            self.jwks_calls += 1
            return JWKS
        raise AssertionError(f"unexpected provider GET {url}")

    def post_form_json(self, url: str, data: dict) -> dict:
        assert url == TOKEN_ENDPOINT, url
        self.token_calls += 1
        self.token_form = data
        self.last_id_token = self.make_id_token()
        return {"id_token": self.last_id_token}

    def make_id_token(self) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "subject-1",
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            "preferred_username": "sso-user",
            "email": "sso@example.com",
            "groups": ["staff"],
        }
        claims.update(self.claims)
        # The nonce is the pending login's value, never the test's convenience.
        claims["nonce"] = self.nonce
        headers = {"kid": KID}
        if self.alg == "none":
            # The classic forgery: an unsigned token. The verifier must refuse it
            # on the algorithm before it ever looks for a key.
            return jwt.encode(claims, None, algorithm="none", headers=headers)
        if self.alg == "wrong-key":
            return jwt.encode(claims, OTHER_PRIVATE_KEY, algorithm="RS256", headers=headers)
        if self.alg == "HS256":
            # A deliberately symmetric forgery: the verifier must refuse it on
            # the algorithm, before it ever looks for a key.
            return jwt.encode(
                claims, "a-symmetric-secret-a-caller-chose", algorithm="HS256", headers=headers
            )
        return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers=headers)


def install_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    claims_overrides: dict | None = None,
    alg: str = "RS256",
) -> MockProvider:
    """Patch the two mandated seams with an in-process provider."""
    provider = MockProvider(claims_overrides=claims_overrides, alg=alg)
    monkeypatch.setattr(oidc, "_http_get_json", provider.get_json)
    monkeypatch.setattr(oidc, "_http_post_form_json", provider.post_form_json)
    return provider


def configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool = True,
    issuer: str = ISSUER,
    client_id: str = CLIENT_ID,
    client_secret: str = CLIENT_SECRET,
    allowed_groups: str = "staff",
    allowed_domains: str = "",
    editor_groups: str = "editors",
    admin_groups: str = "",
    public_url: str = PUBLIC_URL,
) -> None:
    monkeypatch.setattr(config, "OIDC_ENABLED", enabled)
    monkeypatch.setattr(config, "OIDC_ISSUER", issuer)
    monkeypatch.setattr(config, "OIDC_CLIENT_ID", client_id)
    monkeypatch.setattr(config, "OIDC_CLIENT_SECRET", client_secret)
    monkeypatch.setattr(config, "OIDC_SCOPES", "openid profile email")
    monkeypatch.setattr(config, "OIDC_GROUPS_CLAIM", "groups")
    monkeypatch.setattr(config, "OIDC_ALLOWED_GROUPS", allowed_groups)
    monkeypatch.setattr(config, "OIDC_ALLOWED_DOMAINS", allowed_domains)
    monkeypatch.setattr(config, "OIDC_EDITOR_GROUPS", editor_groups)
    monkeypatch.setattr(config, "OIDC_ADMIN_GROUPS", admin_groups)
    monkeypatch.setenv("PUBLIC_URL", public_url)


# --- helpers ----------------------------------------------------------------


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def bootstrap_admin(client: TestClient) -> dict:
    """Let break-glass create the first admin, then sign in as that real account."""
    glass = client.post("/login", json=BREAK_GLASS)
    assert glass.status_code == 200, glass.text
    created = client.post(
        "/users",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "role": "admin"},
        headers=bearer(glass.json()["token"]),
    )
    assert created.status_code == 201, created.text
    login = client.post("/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert login.status_code == 200, login.text
    return login.json()


def start_login(client: TestClient, provider: MockProvider) -> tuple[str, object]:
    """Begin a login and teach the provider the nonce this request minted."""
    response = client.get("/auth/oidc/start", follow_redirects=False)
    assert response.status_code == 302, response.text
    query = parse_qs(urlparse(response.headers["location"]).query)
    state = query["state"][0]
    provider.nonce = query["nonce"][0]
    return state, response


def callback(
    client: TestClient,
    *,
    state: str | None = None,
    code: str | None = "auth-code",
    cookie: str | None = None,
    send_cookie: bool = True,
):
    """Hit the callback, passing the Secure state cookie explicitly.

    httpx will not send a `Secure` cookie over `http://testserver`, so every test
    that needs the cookie sets it by hand; that also makes dropping or
    mismatching it a one-line test.
    """
    params: dict[str, str] = {}
    if state is not None:
        params["state"] = state
    if code is not None:
        params["code"] = code
    headers: dict[str, str] = {}
    if send_cookie:
        value = state or "" if cookie is None else cookie
        headers["Cookie"] = f"{oidc.STATE_COOKIE_NAME}={value}"
    return client.get("/auth/oidc/callback", params=params, headers=headers, follow_redirects=False)


def assert_rejected(response, expected: str) -> str:
    """The rejection is a 302 carrying the frozen value in the fragment only."""
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert "?" not in location, location
    assert location.startswith(f"{PUBLIC_URL}/#sso_error="), location
    value = location.split("#sso_error=", 1)[1]
    assert value == expected
    assert value in oidc.SSO_ERRORS
    return location


def sso_code_from(response) -> str:
    """The successful callback parks a single-use handoff code in the fragment."""
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert "?" not in location, location
    assert location.startswith(f"{PUBLIC_URL}/#sso_code="), location
    return location.split("#sso_code=", 1)[1]


def complete_login(client: TestClient, provider: MockProvider):
    """start -> callback -> exchange, returning the exchange response."""
    state, _ = start_login(client, provider)
    handoff = sso_code_from(callback(client, state=state))
    return client.post("/auth/oidc/exchange", json={"code": handoff})


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, auth.AUTH_SECRET, algorithms=[auth.AUTH_ALGO])


def latest_oidc_failure_detail() -> str:
    with Session(engine) as db:
        rows = db.exec(select(AuditEvent).where(AuditEvent.action == audit.LOGIN_OIDC_FAILED)).all()
    assert rows, "no login.oidc.failed row was recorded"
    latest = max(rows, key=lambda row: row.created_at)
    return latest.detail_json or ""


def user_count() -> int:
    with Session(engine) as db:
        return len(db.exec(select(User)).all())


# --- flow (AC-1) ------------------------------------------------------------


def test_status_reports_whether_sso_is_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, enabled=True)
    enabled = client.get("/auth/oidc/status")

    assert enabled.status_code == 200
    assert enabled.json() == {"enabled": True}

    monkeypatch.setattr(config, "OIDC_ENABLED", False)
    disabled = client.get("/auth/oidc/status")

    assert disabled.status_code == 200
    assert disabled.json() == {"enabled": False}


def test_start_redirects_with_pkce_and_a_scoped_state_cookie(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)

    state, response = start_login(client, provider)
    location = response.headers["location"]
    query = parse_qs(urlparse(location).query)

    assert location.startswith(f"{AUTHORIZE_ENDPOINT}?")
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]
    assert query["state"] == [state]
    assert query["nonce"][0]
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [f"{PUBLIC_URL}/auth/oidc/callback"]

    cookie = response.headers["set-cookie"]
    lowered = cookie.lower()
    assert cookie.startswith(f"{oidc.STATE_COOKIE_NAME}={state}")
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=lax" in lowered
    assert "path=/auth/oidc" in lowered


def test_full_flow_returns_a_session_and_exchanges_the_code_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)
    bootstrap_admin(client)

    state, _ = start_login(client, provider)
    response = callback(client, state=state)
    handoff = sso_code_from(response)

    exchanged = client.post("/auth/oidc/exchange", json={"code": handoff})

    assert exchanged.status_code == 200, exchanged.text
    body = exchanged.json()
    assert body["token"]
    assert body["expires_in"] == auth.AUTH_ACCESS_TOKEN_TTL
    assert body["refresh_token"]
    assert provider.token_calls == 1
    assert provider.token_form is not None
    assert provider.token_form["grant_type"] == "authorization_code"
    assert provider.token_form["code"] == "auth-code"
    assert provider.token_form["client_secret"] == CLIENT_SECRET
    assert provider.token_form["code_verifier"]


def test_the_flow_never_constructs_a_real_httpx_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)
    bootstrap_admin(client)

    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("the OIDC flow must only use the monkeypatched seams")

    # The TestClient already exists; any *new* httpx.Client means a seam leaked.
    monkeypatch.setattr(httpx, "Client", forbidden_client)

    exchanged = complete_login(client, provider)

    assert exchanged.status_code == 200, exchanged.text


def test_each_start_mints_a_distinct_state(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)

    first, _ = start_login(client, provider)
    second, _ = start_login(client, provider)

    assert first != second


def test_start_is_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    install_provider(monkeypatch)
    monkeypatch.setattr(oidc, "start_limiter", oidc._StartLimiter(limit=2, window=60))

    for _ in range(2):
        allowed = client.get("/auth/oidc/start", follow_redirects=False)
        assert allowed.status_code == 302

    throttled = client.get("/auth/oidc/start", follow_redirects=False)

    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) > 0


# --- roles (AC-2) -----------------------------------------------------------


def test_an_editor_group_claim_grants_editor(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, allowed_groups="editors", editor_groups="editors")
    provider = install_provider(monkeypatch, claims_overrides={"groups": ["editors"]})
    bootstrap_admin(client)

    exchanged = complete_login(client, provider)

    assert exchanged.status_code == 200, exchanged.text
    payload = decode_access_token(exchanged.json()["token"])
    assert payload["role"] == accounts.EDITOR_ROLE
    with Session(engine) as db:
        user = db.get(User, payload["sub"])
        assert user is not None
        assert user.role == accounts.EDITOR_ROLE


def test_a_principal_outside_the_editor_groups_is_a_viewer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch, allowed_groups="staff", editor_groups="editors")
    provider = install_provider(monkeypatch, claims_overrides={"groups": ["staff"]})
    bootstrap_admin(client)

    exchanged = complete_login(client, provider)

    assert exchanged.status_code == 200, exchanged.text
    payload = decode_access_token(exchanged.json()["token"])
    assert payload["role"] == accounts.DEFAULT_ROLE
    with Session(engine) as db:
        user = db.get(User, payload["sub"])
        assert user is not None
        assert user.role == accounts.DEFAULT_ROLE
        assert user.password_hash is None


def test_relogin_does_not_create_a_second_account_or_rewrite_the_role(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch, allowed_groups="staff", editor_groups="editors")
    provider = install_provider(monkeypatch, claims_overrides={"groups": ["staff"]})
    bootstrap_admin(client)

    first = complete_login(client, provider)
    assert first.status_code == 200, first.text
    user_id = decode_access_token(first.json()["token"])["sub"]
    users_before = user_count()

    # An operator promotes the account locally. A later claim must not undo it.
    with Session(engine) as db:
        user = db.get(User, user_id)
        assert user is not None
        user.role = accounts.EDITOR_ROLE
        db.add(user)
        db.commit()

    second = complete_login(client, provider)

    assert second.status_code == 200, second.text
    assert decode_access_token(second.json()["token"])["role"] == accounts.EDITOR_ROLE
    with Session(engine) as db:
        assert len(db.exec(select(User)).all()) == users_before
        stored = db.get(User, user_id)
        assert stored is not None
        assert stored.role == accounts.EDITOR_ROLE
        assert len(db.exec(select(OidcIdentity)).all()) == 1


def test_a_claim_can_never_grant_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, editor_groups="editors")

    for claims in (
        {"groups": ["anything"]},
        {"groups": ["admin"]},
        {"groups": ["editors", "admin"]},
    ):
        assert oidc.role_for_claims(claims) != accounts.ADMIN_ROLE

    with Session(engine) as db:
        with pytest.raises(accounts.InvalidAccount):
            accounts.create_sso_user(db, username="sso-admin", role=accounts.ADMIN_ROLE)


# --- the boot validator (AC-6) ----------------------------------------------


@pytest.mark.parametrize(
    "case, expected",
    [
        ("missing_client_secret", "OIDC_CLIENT_SECRET"),
        ("empty_allow_lists", "OIDC_ALLOWED_GROUPS"),
        ("non_https_issuer", "OIDC_ISSUER"),
        ("admin_groups", "OIDC_ADMIN_GROUPS"),
        ("auth_disabled", "AUTH_ENABLED"),
        ("empty_public_url", "PUBLIC_URL"),
    ],
)
def test_validate_refuses_partial_or_fail_open_configuration(
    monkeypatch: pytest.MonkeyPatch, case: str, expected: str
) -> None:
    configure(monkeypatch)

    if case == "missing_client_secret":
        monkeypatch.setattr(config, "OIDC_CLIENT_SECRET", "")
    elif case == "empty_allow_lists":
        monkeypatch.setattr(config, "OIDC_ALLOWED_GROUPS", "")
        monkeypatch.setattr(config, "OIDC_ALLOWED_DOMAINS", "")
    elif case == "non_https_issuer":
        monkeypatch.setattr(config, "OIDC_ISSUER", "http://idp.example.com")
    elif case == "admin_groups":
        monkeypatch.setattr(config, "OIDC_ADMIN_GROUPS", "admin")
    elif case == "auth_disabled":
        monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    elif case == "empty_public_url":
        monkeypatch.delenv("PUBLIC_URL", raising=False)

    with pytest.raises(RuntimeError, match=expected):
        oidc.validate_oidc_configuration()


def test_a_complete_configuration_validates_and_disabled_needs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch)
    assert oidc.validate_oidc_configuration() is None

    monkeypatch.setattr(config, "OIDC_ENABLED", False)
    monkeypatch.setattr(config, "OIDC_ISSUER", "")
    monkeypatch.setattr(config, "OIDC_CLIENT_ID", "")
    monkeypatch.setattr(config, "OIDC_CLIENT_SECRET", "")
    monkeypatch.setattr(config, "OIDC_ALLOWED_GROUPS", "")
    monkeypatch.setattr(config, "OIDC_ALLOWED_DOMAINS", "")
    monkeypatch.setattr(config, "OIDC_ADMIN_GROUPS", "")
    monkeypatch.delenv("PUBLIC_URL", raising=False)

    assert oidc.validate_oidc_configuration() is None


# --- state (AC-4) -----------------------------------------------------------


def test_a_replayed_state_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)
    bootstrap_admin(client)
    state, _ = start_login(client, provider)

    first = callback(client, state=state)
    sso_code_from(first)

    replay = callback(client, state=state)

    assert_rejected(replay, oidc.SSO_ERROR_STATE_REPLAYED)


def test_an_unknown_state_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)

    response = callback(client, state="never-issued")

    assert_rejected(response, oidc.SSO_ERROR_STATE_UNKNOWN)


def test_a_missing_state_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)

    response = callback(client, state=None, send_cookie=False)

    assert_rejected(response, oidc.SSO_ERROR_STATE_MISSING)


def test_an_expired_state_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)
    state, _ = start_login(client, provider)

    future = time.monotonic() + oidc.STATE_TTL_SECONDS + 1
    monkeypatch.setattr(oidc, "_now", lambda: future)
    response = callback(client, state=state)

    assert_rejected(response, oidc.SSO_ERROR_STATE_EXPIRED)


def test_a_missing_state_cookie_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)
    state, _ = start_login(client, provider)

    response = callback(client, state=state, send_cookie=False)

    assert_rejected(response, oidc.SSO_ERROR_COOKIE_MISMATCH)


def test_a_mismatched_state_cookie_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)
    state, _ = start_login(client, provider)

    response = callback(client, state=state, cookie="a-different-browser-state")

    assert_rejected(response, oidc.SSO_ERROR_COOKIE_MISMATCH)


def test_a_wrong_nonce_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)
    state, _ = start_login(client, provider)
    provider.nonce = "a-nonce-that-does-not-belong-to-this-login"

    response = callback(client, state=state)

    assert_rejected(response, oidc.SSO_ERROR_NONCE_MISMATCH)


def test_an_hs256_id_token_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch, alg="HS256")
    state, _ = start_login(client, provider)

    response = callback(client, state=state)

    assert_rejected(response, oidc.SSO_ERROR_TOKEN_INVALID)


def test_an_unsigned_none_algorithm_token_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch, alg="none")
    state, _ = start_login(client, provider)

    assert_rejected(callback(client, state=state), oidc.SSO_ERROR_TOKEN_INVALID)


def test_a_token_signed_by_an_unpublished_key_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Perfect claims, wrong signature: the JWKS is the only trusted key source."""
    configure(monkeypatch)
    provider = install_provider(monkeypatch, alg="wrong-key")
    state, _ = start_login(client, provider)

    assert_rejected(callback(client, state=state), oidc.SSO_ERROR_TOKEN_INVALID)


def test_an_expired_id_token_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch, claims_overrides={"exp": int(time.time()) - 30})
    state, _ = start_login(client, provider)

    assert_rejected(callback(client, state=state), oidc.SSO_ERROR_TOKEN_INVALID)


def test_a_wrong_issuer_or_audience_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)

    for overrides in (
        {"iss": "https://evil.example.com"},
        {"aud": "a-different-client"},
    ):
        provider = install_provider(monkeypatch, claims_overrides=overrides)
        state, _ = start_login(client, provider)
        response = callback(client, state=state)
        assert_rejected(response, oidc.SSO_ERROR_TOKEN_INVALID)


def test_every_rejection_uses_the_frozen_sso_error_fragment(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)

    for response, expected in (
        (callback(client, state=None, send_cookie=False), oidc.SSO_ERROR_STATE_MISSING),
        (callback(client, state="never-issued"), oidc.SSO_ERROR_STATE_UNKNOWN),
    ):
        location = assert_rejected(response, expected)
        assert expected in oidc.SSO_ERRORS
        assert "?" not in location


# --- the allow-list (AC-3) --------------------------------------------------


def test_a_rejected_group_redirects_without_provider_free_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch, allowed_groups="staff", allowed_domains="")
    provider = install_provider(
        monkeypatch,
        claims_overrides={
            "groups": ["INTRUDER-FREE-TEXT"],
            "preferred_username": "FREE-TEXT-NAME",
            "email": "free-text@intruder.example",
        },
    )
    state, _ = start_login(client, provider)

    location = assert_rejected(callback(client, state=state), oidc.SSO_ERROR_GROUP_NOT_ALLOWED)

    assert "INTRUDER-FREE-TEXT" not in location
    assert "FREE-TEXT-NAME" not in location
    assert "free-text@intruder.example" not in location


def test_a_rejected_email_domain_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, allowed_groups="", allowed_domains="example.com")
    provider = install_provider(monkeypatch, claims_overrides={"email": "someone@evil.test"})
    state, _ = start_login(client, provider)

    response = callback(client, state=state)

    assert_rejected(response, oidc.SSO_ERROR_DOMAIN_NOT_ALLOWED)


def test_group_and_domain_allow_lists_compose_with_and(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch, allowed_groups="staff", allowed_domains="example.com")
    provider = install_provider(
        monkeypatch,
        claims_overrides={"groups": ["staff"], "email": "a@evil.test"},
    )
    bootstrap_admin(client)

    # In the group but on a rejected domain: the domain must still say no.
    state, _ = start_login(client, provider)
    assert_rejected(callback(client, state=state), oidc.SSO_ERROR_DOMAIN_NOT_ALLOWED)

    # On the domain but not in the group: the group must still say no.
    provider.claims.update({"groups": ["other"], "email": "a@example.com"})
    state, _ = start_login(client, provider)
    assert_rejected(callback(client, state=state), oidc.SSO_ERROR_GROUP_NOT_ALLOWED)

    # Both together: the only shape that passes.
    provider.claims.update({"groups": ["staff"], "email": "a@example.com"})
    state, _ = start_login(client, provider)
    handoff = sso_code_from(callback(client, state=state))
    exchanged = client.post("/auth/oidc/exchange", json={"code": handoff})

    assert exchanged.status_code == 200, exchanged.text


def test_a_rejection_audits_the_reason_but_no_secret_material(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "oidc-client-secret-do-not-leak-9f3a"
    code = "auth-code-do-not-log-7b1c"
    configure(monkeypatch, client_secret=secret, allowed_groups="staff")
    provider = install_provider(monkeypatch, claims_overrides={"groups": ["intruders"]})
    state, _ = start_login(client, provider)

    response = callback(client, state=state, code=code)

    assert_rejected(response, oidc.SSO_ERROR_GROUP_NOT_ALLOWED)
    detail = latest_oidc_failure_detail()
    assert json.loads(detail)["sso_error"] == oidc.SSO_ERROR_GROUP_NOT_ALLOWED
    assert provider.last_id_token is not None
    for fragment in (secret, code, state, provider.last_id_token):
        assert fragment not in detail


# --- bootstrap lockout (AC-2) -----------------------------------------------


def test_provisioning_is_refused_when_no_enabled_admin_exists(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)
    state, _ = start_login(client, provider)

    # The callback still verifies and parks a handoff; the mutation is refused.
    handoff = sso_code_from(callback(client, state=state))
    exchanged = client.post("/auth/oidc/exchange", json={"code": handoff})

    assert exchanged.status_code == 409
    with Session(engine) as db:
        assert db.exec(select(User)).all() == []
        assert db.exec(select(OidcIdentity)).all() == []


# --- secret hygiene (AC-8) --------------------------------------------------


def test_the_client_secret_never_reaches_logs_or_audit_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    secret = "client-secret-must-never-appear-4d2e"
    configure(monkeypatch, client_secret=secret)
    provider = install_provider(monkeypatch)
    bootstrap_admin(client)

    # A success path.
    succeeded = complete_login(client, provider)
    assert succeeded.status_code == 200, succeeded.text

    # A rejection path.
    provider.claims["groups"] = ["intruders"]
    state, _ = start_login(client, provider)
    assert_rejected(callback(client, state=state), oidc.SSO_ERROR_GROUP_NOT_ALLOWED)

    # A provider-error path: the discovery fetch itself fails.
    provider.claims["groups"] = ["staff"]
    state, _ = start_login(client, provider)
    with oidc._cache_lock:
        oidc._discovery_cache.clear()

    def unavailable(_url: str) -> dict:
        raise httpx.ConnectError("the provider is down")

    monkeypatch.setattr(oidc, "_http_get_json", unavailable)
    assert_rejected(callback(client, state=state), oidc.SSO_ERROR_PROVIDER_UNAVAILABLE)

    for record in caplog.records:
        assert secret not in record.getMessage()

    with Session(engine) as db:
        details = db.exec(
            select(AuditEvent.detail_json).where(AuditEvent.detail_json.is_not(None))
        ).all()
    for detail in details:
        assert secret not in detail


def test_a_provider_error_is_frozen_and_does_not_echo_the_exception(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)
    state, _ = start_login(client, provider)
    with oidc._cache_lock:
        oidc._discovery_cache.clear()
    leaked = "PROVIDER-EXCEPTION-TEXT-MUST-NOT-LEAK"

    def unavailable(_url: str) -> dict:
        raise httpx.ConnectError(leaked)

    monkeypatch.setattr(oidc, "_http_get_json", unavailable)
    location = assert_rejected(callback(client, state=state), oidc.SSO_ERROR_PROVIDER_UNAVAILABLE)

    assert leaked not in location


# --- local login is unaffected (AC-5) ---------------------------------------


def test_local_login_still_works_and_an_sso_account_has_no_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    provider = install_provider(monkeypatch)
    admin = bootstrap_admin(client)
    assert admin["token"]

    provisioned = complete_login(client, provider)
    assert provisioned.status_code == 200, provisioned.text

    local = client.post("/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert local.status_code == 200, local.text

    sso_local = client.post(
        "/login", json={"username": "sso-user", "password": "any-password-at-all"}
    )
    assert sso_local.status_code == 401

    with Session(engine) as db:
        user = db.exec(select(User).where(User.username == "sso-user")).one()
        assert user.password_hash is None


# --- store hygiene ----------------------------------------------------------


def test_reset_empties_both_stores_and_the_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oidc, "start_limiter", oidc._StartLimiter(limit=1, window=60))
    oidc.pending_logins.put("state-1", object(), 60)
    oidc.handoff_codes.put("code-1", object(), 60)
    oidc.start_limiter.record("192.0.2.1")
    assert oidc.start_limiter.retry_after("192.0.2.1") > 0

    oidc.reset()

    assert oidc.pending_logins.consume("state-1") == (None, "unknown")
    assert oidc.handoff_codes.consume("code-1") == (None, "unknown")
    assert oidc.start_limiter.retry_after("192.0.2.1") == 0


# --- handoff-code lifecycle -------------------------------------------------


def test_a_handoff_code_is_single_use(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The exchange spends the code, so a replayed POST is a 401, not a second session."""
    provider = install_provider(monkeypatch)
    configure(monkeypatch)
    bootstrap_admin(client)

    first = complete_login(client, provider)
    assert first.status_code == 200, first.text
    code = oidc.park_handoff({"sub": "single-use", "preferred_username": "sso-once", "groups": []})
    assert client.post("/auth/oidc/exchange", json={"code": code}).status_code == 200

    replay = client.post("/auth/oidc/exchange", json={"code": code})
    assert replay.status_code == 401, replay.text


def test_a_handoff_code_expires(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """120 seconds is the whole lifetime; the store's clock is the seam."""
    install_provider(monkeypatch)
    configure(monkeypatch)
    bootstrap_admin(client)

    clock = [1_000.0]
    monkeypatch.setattr(oidc, "_now", lambda: clock[0])
    code = oidc.park_handoff({"sub": "expiring", "preferred_username": "sso-expiring", "groups": []})

    clock[0] += oidc.HANDOFF_TTL_SECONDS + 1
    response = client.post("/auth/oidc/exchange", json={"code": code})
    assert response.status_code == 401, response.text


def test_an_unknown_handoff_code_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    install_provider(monkeypatch)
    configure(monkeypatch)
    bootstrap_admin(client)

    response = client.post("/auth/oidc/exchange", json={"code": "never-minted-here"})
    assert response.status_code == 401, response.text


# --- binding safety ---------------------------------------------------------


def test_a_claim_naming_an_existing_account_provisions_a_new_one(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The takeover regression: a claim must never be linked to an existing account.

    A principal whose `preferred_username` (and email) match a local account gets
    a NEW, suffixed account. Binding by name or email would let anyone who can
    create an account at the IdP sign in as an existing local user.
    """
    provider = install_provider(
        monkeypatch,
        claims_overrides={"preferred_username": ADMIN_USERNAME, "email": f"{ADMIN_USERNAME}@local.test"},
    )
    configure(monkeypatch, allowed_domains="local.test")
    bootstrap_admin(client)
    before = user_count()

    response = complete_login(client, provider)
    assert response.status_code == 200, response.text

    assert user_count() == before + 1
    with Session(engine) as db:
        created = db.exec(select(User).where(User.username != ADMIN_USERNAME)).all()
        existing = accounts.get_user_by_username(db, ADMIN_USERNAME)
        identity = db.exec(select(OidcIdentity)).first()
    assert created, "no SSO account was provisioned"
    assert created[0].username != ADMIN_USERNAME
    assert created[0].username.startswith(ADMIN_USERNAME)
    # The existing admin is untouched: same id, same role, and no identity points at it.
    assert existing is not None and existing.role == accounts.ADMIN_ROLE
    assert identity is not None and identity.user_id == created[0].id
    assert identity.user_id != existing.id


def test_a_disabled_sso_account_cannot_sign_in_again(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disabling the account is the kill switch, and it must beat a valid claim."""
    provider = install_provider(monkeypatch)
    configure(monkeypatch)
    bootstrap_admin(client)
    assert complete_login(client, provider).status_code == 200

    with Session(engine) as db:
        user = db.exec(select(User).where(User.username == "sso-user")).first()
        assert user is not None
        user.disabled = 1
        db.add(user)
        db.commit()

    again = complete_login(client, provider)
    assert again.status_code == 401, again.text


# --- robustness -------------------------------------------------------------


def test_a_non_ascii_state_is_a_rejection_not_a_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`hmac.compare_digest` raises on non-ASCII `str`, and `state` is attacker input.

    A 500 here would break the "every rejection maps to a frozen sso_error"
    contract (and write no audit row), so the comparison is done over UTF-8 bytes.
    """
    install_provider(monkeypatch)
    configure(monkeypatch)

    # The cookie stays ASCII (a header cannot carry anything else); it is the
    # query parameter that is attacker-controlled, which is the path that used to
    # raise.
    response = client.get(
        "/auth/oidc/callback",
        params={"state": "caf\u00e9", "code": "auth-code"},
        headers={"Cookie": f"{oidc.STATE_COOKIE_NAME}=ascii-state"},
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    assert response.headers["location"].startswith(f"{PUBLIC_URL}/#sso_error=")


def test_the_stores_refuse_a_new_entry_at_capacity() -> None:
    store = oidc._ExpiringStore(cap=2)
    store.put("first", 1, 60)
    store.put("second", 2, 60)

    with pytest.raises(oidc.StoreFull):
        store.put("third", 3, 60)

    # Replacing a key already in the store is not growth, so it is allowed.
    store.put("first", 4, 60)
    assert store.consume("first") == (4, None)
