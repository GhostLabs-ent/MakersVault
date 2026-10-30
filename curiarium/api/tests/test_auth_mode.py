"""AUTH_MODE decouples "auth is on" from the break-glass environment pair.

`auth.AUTH_MODE` is read once at import, so every test here changes the mode by
patching the module attributes and re-deriving `AUTH_ENABLED` with the very same
expression the import uses (`set_mode`). That is a faithful mode change: the
guards read module attributes at request time, exactly as they read the values
the import derived.

The security pin at the centre of this file is the blank environment pair. A
blank `AUTH_USERNAME`/`AUTH_PASSWORD` still matches blank submitted credentials
in `credentials_match` (two `compare_digest` of empty bytes), so `auto` mode used
to be safe only because a blank pair made `AUTH_ENABLED` false and `/login` 503'd
first. Any mode that forces auth on must therefore refuse an empty form before it
is compared - and must never mint a session from it.
"""

import json

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

import accounts
import asset_file_service
import asset_service
import audit
import auth
import config
import db
import library_scan
import login_throttle as login_throttle_module
import main
import mfa
import oidc
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, AuditEvent, Folder, MfaRecoveryCode, OidcIdentity, User, UserSession

BREAK_GLASS_USERNAME = "admin"
BREAK_GLASS_PASSWORD = "super-secret"
LOCAL_USERNAME = "root"
LOCAL_PASSWORD = "root-password-1"
NOT_CONFIGURED = "Authentication is not configured on the server"

STL_BYTES = b"solid cube\nendsolid cube\n"

ISSUER = "https://idp.example.com"
CLIENT_ID = "vault-client"
CLIENT_SECRET = "client-secret"
PUBLIC_URL = "https://vault.example.com"


# --- fixtures and helpers ---------------------------------------------------


def truncate_accounts() -> None:
    """Empty every auth table, children first: the foreign keys are enforced."""
    with Session(engine) as db:
        db.execute(delete(MfaRecoveryCode))
        db.execute(delete(OidcIdentity))
        db.execute(delete(UserSession))
        db.execute(delete(User))
        db.commit()


@pytest.fixture(autouse=True)
def clean_accounts():
    """Migrate once, then start and finish every test without accounts."""
    run_migrations(engine)
    truncate_accounts()
    login_throttle_module.limiter.reset()
    login_throttle_module.mfa_limiter.reset()
    oidc.reset()
    yield
    truncate_accounts()
    login_throttle_module.limiter.reset()
    login_throttle_module.mfa_limiter.reset()
    oidc.reset()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point every storage binding at a temp root and undo the rows a test made.

    AC-6 uploads a model to mint a file grant through an auth-disabled API; the
    rows and files must not leak into the next test file.
    """
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(main, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_service, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    run_migrations(engine)

    with Session(engine) as session:
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        folders_before = {folder.id for folder in session.exec(select(Folder))}

    yield storage

    with Session(engine) as session:
        for asset_file in list(session.exec(select(AssetFile))):
            if asset_file.asset_id not in assets_before:
                session.delete(asset_file)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        session.commit()


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argon2's floor parameters; nothing here asserts anything about hashing."""
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture(autouse=True)
def pinned_env_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the break-glass pair so no developer `.env` can change these cases."""
    set_mode(
        monkeypatch,
        auth.AUTH_MODE,
        username=BREAK_GLASS_USERNAME,
        password=BREAK_GLASS_PASSWORD,
    )


@pytest.fixture()
def client():
    with TestClient(main.app) as test_client:
        yield test_client


def set_mode(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    *,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Patch the auth mode the way the import does: mode first, then the derived flag.

    `AUTH_ENABLED` is computed once at import from the module attributes, so a
    realistic mode change has to re-derive it with the very same expression.
    """
    monkeypatch.setattr(auth, "AUTH_MODE", mode)
    if username is not None:
        monkeypatch.setattr(auth, "AUTH_USERNAME", username)
    if password is not None:
        monkeypatch.setattr(auth, "AUTH_PASSWORD", password)
    monkeypatch.setattr(
        auth,
        "AUTH_ENABLED",
        auth.resolve_auth_enabled(auth.AUTH_MODE, auth.AUTH_USERNAME, auth.AUTH_PASSWORD),
    )


def configure_oidc(monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True) -> None:
    """A complete, valid OIDC configuration; the idiom from tests/test_oidc.py."""
    monkeypatch.setattr(config, "OIDC_ENABLED", enabled)
    monkeypatch.setattr(config, "OIDC_ISSUER", ISSUER)
    monkeypatch.setattr(config, "OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(config, "OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setattr(config, "OIDC_SCOPES", "openid profile email")
    monkeypatch.setattr(config, "OIDC_GROUPS_CLAIM", "groups")
    monkeypatch.setattr(config, "OIDC_ALLOWED_GROUPS", "staff")
    monkeypatch.setattr(config, "OIDC_ALLOWED_DOMAINS", "")
    monkeypatch.setattr(config, "OIDC_EDITOR_GROUPS", "editors")
    monkeypatch.setattr(config, "OIDC_ADMIN_GROUPS", "")
    monkeypatch.setattr(config, "OIDC_DEFAULT_ROLE", accounts.DEFAULT_ROLE)
    monkeypatch.setenv("PUBLIC_URL", PUBLIC_URL)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def break_glass_login(client: TestClient) -> dict:
    response = client.post(
        "/login",
        json={"username": BREAK_GLASS_USERNAME, "password": BREAK_GLASS_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def login_user(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def create_user(client: TestClient, admin_token: str, username: str, password: str) -> dict:
    response = client.post(
        "/users",
        json={"username": username, "password": password, "role": "admin"},
        headers=bearer(admin_token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def session_count() -> int:
    with Session(engine) as db:
        return len(db.exec(select(UserSession)).all())


def login_succeeded_events(target: str) -> list[AuditEvent]:
    with Session(engine) as db:
        rows = db.exec(
            select(AuditEvent).where(
                AuditEvent.action == audit.LOGIN_SUCCEEDED,
                AuditEvent.target == target,
            )
        ).all()
        return list(rows)


def current_code(secret: str) -> str:
    """The TOTP code for a base32 seed at the current wall-clock step."""
    raw = mfa.parse_secret(secret)
    assert raw is not None, f"{secret!r} is not a base32 seed"
    return mfa.totp_at(raw, mfa.current_step())


def enrol(client: TestClient, token: str, password: str) -> None:
    """Enrol the session's own account, so `/login` must answer a challenge."""
    enrolment = client.post("/mfa/enrol", json={"password": password}, headers=bearer(token))
    assert enrolment.status_code == 200, enrolment.text
    secret = enrolment.json()["secret"]
    confirmed = client.post(
        "/mfa/confirm",
        json={"password": password, "secret": secret, "code": current_code(secret)},
        headers=bearer(token),
    )
    assert confirmed.status_code == 200, confirmed.text


# --- the pure derivations ---------------------------------------------------


def test_resolve_auth_enabled_matrix() -> None:
    """AC-1/AC-4: only `auto` still keys off the environment pair.

    The pair variants are a set pair, a fully blank pair and the two half-blank
    shapes. `auto` is the legacy rule verbatim: `bool(username and password)`,
    with no stripping or normalisation.
    """
    pairs = [
        ("admin", "super-secret"),
        ("", ""),
        ("admin", ""),
        ("", "super-secret"),
    ]
    expectations = {
        auth.AUTH_MODE_AUTO: [True, False, False, False],
        auth.AUTH_MODE_LOCAL: [True, True, True, True],
        auth.AUTH_MODE_BOTH: [True, True, True, True],
        auth.AUTH_MODE_OIDC: [True, True, True, True],
        auth.AUTH_MODE_OFF: [False, False, False, False],
    }
    for mode, expected in expectations.items():
        for (username, password), want in zip(pairs, expected, strict=True):
            got = auth.resolve_auth_enabled(mode, username, password)
            assert got is want, f"resolve_auth_enabled({mode!r}, {username!r}, {password!r}) == {got}"


def test_unknown_mode_fails_closed() -> None:
    """AC-2: a typo in AUTH_MODE must not leave the API open, whatever the pair.

    An empty string is unknown here too: `AUTH_MODE=""` is normalised to `auto`
    by the environment read at import (`(os.getenv(...) or "auto").strip().lower()`),
    not by this pure function, which fails closed on anything it does not know.
    """
    for mode in ("wizard", "AUTO ", "auto ", "local1", ""):
        assert auth.resolve_auth_enabled(mode, "admin", "super-secret") is False


@pytest.mark.parametrize(
    "mode, password_ok, oidc_ok",
    [
        (auth.AUTH_MODE_AUTO, True, True),
        (auth.AUTH_MODE_LOCAL, True, False),
        (auth.AUTH_MODE_BOTH, True, True),
        (auth.AUTH_MODE_OIDC, False, True),
        (auth.AUTH_MODE_OFF, False, False),
    ],
)
def test_login_paths_per_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str, password_ok: bool, oidc_ok: bool
) -> None:
    """AC-1: each mode names exactly which login paths exist."""
    set_mode(monkeypatch, mode)

    assert auth.password_login_allowed() is password_ok
    assert auth.oidc_login_allowed() is oidc_ok


def test_auto_mode_keeps_the_legacy_pair_rule() -> None:
    """AC-4: today's AUTH_ENABLED rule, unchanged, for the `auto` row.

    The env-read expression turns an empty `AUTH_MODE` into `auto` at import, so
    the pure function is only ever asked about `AUTH_MODE_AUTO` here.
    """
    for username, password in (("admin", "secret"), ("", ""), ("admin", ""), ("", "secret"), (" ", " ")):
        assert auth.resolve_auth_enabled(auth.AUTH_MODE_AUTO, username, password) is bool(
            username and password
        )


# --- the security pin -------------------------------------------------------


@pytest.mark.parametrize("mode", [auth.AUTH_MODE_LOCAL, auth.AUTH_MODE_BOTH, auth.AUTH_MODE_OIDC])
@pytest.mark.parametrize(
    "username, password",
    [
        ("", ""),
        ("", "super-secret"),
        ("admin", ""),
    ],
)
def test_blank_environment_pair_never_mints_a_session(
    monkeypatch: pytest.MonkeyPatch, mode: str, username: str, password: str
) -> None:
    """AC-1 (security pin): a blank pair must not accept an empty form.

    `credentials_match("", "")` is True, so a mode that forces auth on without
    checking that the pair is genuinely configured would mint a break-glass admin
    session from an empty form against an empty users table.
    """
    if mode == auth.AUTH_MODE_OIDC:
        configure_oidc(monkeypatch)
    set_mode(monkeypatch, mode, username=username, password=password)

    with TestClient(main.app) as client:
        response = client.post("/login", json={"username": "", "password": ""})

        assert response.status_code == 401, response.text
        assert session_count() == 0, "an empty form must not create a session"


# --- AC-1: a real account signs in with no environment pair -----------------


@pytest.mark.parametrize("mode", [auth.AUTH_MODE_LOCAL, auth.AUTH_MODE_BOTH])
def test_local_password_login_survives_a_blank_environment_pair(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """AC-1: with a real account, blank env credentials change nothing.

    The pair is only the break-glass door; a stored account is the real one.
    """
    glass = break_glass_login(client)
    create_user(client, glass["token"], LOCAL_USERNAME, LOCAL_PASSWORD)
    set_mode(monkeypatch, mode, username="", password="")

    body = login_user(client, LOCAL_USERNAME, LOCAL_PASSWORD)

    assert body["token"], body
    assert body["refresh_token"], body
    events = login_succeeded_events(LOCAL_USERNAME)
    assert events, "the successful login wrote no login.succeeded row"
    assert json.loads(events[-1].detail_json or "{}")["kind"] == "password"
    assert client.get("/health").json()["auth_required"] is True


# --- AC-2: the boot validator ----------------------------------------------


def test_oidc_mode_without_oidc_enabled_refuses_to_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-2: `oidc` with SSO unconfigured leaves no login path at all.

    The refusal happens at startup, not at the first login attempt, and it names
    both remedies.
    """
    monkeypatch.setattr(config, "OIDC_ENABLED", False)
    set_mode(monkeypatch, auth.AUTH_MODE_OIDC)

    with pytest.raises(RuntimeError) as excinfo:
        auth.validate_auth_configuration()
    message = str(excinfo.value)
    assert "AUTH_MODE" in message
    assert "OIDC_ENABLED" in message
    assert "AUTH_MODE=both" in message
    assert "OIDC_ENABLED=1" in message

    with pytest.raises(RuntimeError) as boot:
        with TestClient(main.app):
            pass
    assert "AUTH_MODE=both" in str(boot.value), "the real lifespan must refuse this boot"


def test_local_mode_with_oidc_enabled_refuses_to_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-2: a complete OIDC configuration is still refused under `AUTH_MODE=local`."""
    configure_oidc(monkeypatch)
    set_mode(monkeypatch, auth.AUTH_MODE_LOCAL)

    with pytest.raises(RuntimeError) as excinfo:
        oidc.validate_oidc_configuration()
    message = str(excinfo.value)
    assert "AUTH_MODE" in message
    assert "AUTH_MODE=both" in message
    assert "unset OIDC_ENABLED" in message


def test_unknown_auth_mode_refuses_to_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-2: an unknown AUTH_MODE refuses the boot and lists the accepted values."""
    set_mode(monkeypatch, "wizard")

    with pytest.raises(RuntimeError) as excinfo:
        auth.validate_auth_configuration()
    message = str(excinfo.value)
    assert "wizard" in message
    assert str(list(auth.AUTH_MODES)) in message


# --- AC-3: break-glass still works, and still revokes itself ----------------


@pytest.mark.parametrize("mode", [auth.AUTH_MODE_BOTH, auth.AUTH_MODE_OIDC])
def test_break_glass_bootstraps_then_revokes_itself(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """AC-3: the env admin still bootstraps an empty table, then loses its session.

    Both the environment credentials and the already-issued break-glass token
    must stop working the moment the first real account exists.
    """
    if mode == auth.AUTH_MODE_OIDC:
        configure_oidc(monkeypatch)
    set_mode(monkeypatch, mode)

    with TestClient(main.app) as client:
        glass = break_glass_login(client)
        create_user(client, glass["token"], LOCAL_USERNAME, LOCAL_PASSWORD)

        recycled = client.post(
            "/login",
            json={"username": BREAK_GLASS_USERNAME, "password": BREAK_GLASS_PASSWORD},
        )
        assert recycled.status_code == 401, recycled.text
        assert client.get("/me", headers=bearer(glass["token"])).status_code == 401


# --- `oidc` mode refuses the local password path ----------------------------


@pytest.mark.parametrize("enrolled", [False, True])
def test_oidc_mode_refuses_local_password_login(
    monkeypatch: pytest.MonkeyPatch, enrolled: bool
) -> None:
    """AC-1/AC-5: `oidc` refuses a valid local password, with or without MFA.

    A TOTP user gets a 401, not a 200 challenge: a second factor only exists on a
    password login path, and this mode has none.
    """
    configure_oidc(monkeypatch)
    set_mode(monkeypatch, auth.AUTH_MODE_BOTH)
    with TestClient(main.app) as client:
        glass = break_glass_login(client)
        create_user(client, glass["token"], LOCAL_USERNAME, LOCAL_PASSWORD)
        if enrolled:
            session = login_user(client, LOCAL_USERNAME, LOCAL_PASSWORD)
            enrol(client, session["token"], LOCAL_PASSWORD)
        sessions_before = session_count()

        set_mode(monkeypatch, auth.AUTH_MODE_OIDC)
        response = client.post("/login", json={"username": LOCAL_USERNAME, "password": LOCAL_PASSWORD})

        assert response.status_code == 401, response.text
        assert "mfa_token" not in response.json()
        assert session_count() == sessions_before


def test_mfa_verify_is_closed_in_oidc_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-5: a challenge minted in `both` must not be spendable after a flip to `oidc`."""
    configure_oidc(monkeypatch)
    set_mode(monkeypatch, auth.AUTH_MODE_OIDC)

    with TestClient(main.app) as client:
        response = client.post("/mfa/verify", json={"mfa_token": "not-a-token", "code": "123456"})

    assert response.status_code == 503
    assert response.json()["detail"] == NOT_CONFIGURED


# --- AC-6: auth disabled, by mode or by the legacy blank pair ---------------


@pytest.mark.parametrize("mode", [auth.AUTH_MODE_OFF, auth.AUTH_MODE_AUTO])
def test_disabled_auth_keeps_the_deployment_open(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    """AC-6: every guard stays open and every auth endpoint 503s.

    `off` is the explicit switch; the second case is the legacy deployment that
    disables auth by leaving `AUTH_USERNAME`/`AUTH_PASSWORD` blank.
    """
    if mode == auth.AUTH_MODE_OFF:
        set_mode(monkeypatch, auth.AUTH_MODE_OFF)
    else:
        set_mode(monkeypatch, auth.AUTH_MODE_AUTO, username="", password="")

    with TestClient(main.app) as client:
        assert client.get("/health").json()["auth_required"] is False

        for path in ("/login", "/refresh", "/logout"):
            response = client.post(path, json={"username": "admin", "password": "super-secret"})
            assert response.status_code == 503, (path, response.text)
            assert response.json()["detail"] == NOT_CONFIGURED

        for path in ("/auth/oidc/status", "/auth/oidc/start", "/auth/oidc/callback"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 503, (path, response.text)
            assert response.json()["detail"] == NOT_CONFIGURED

        exchange = client.post("/auth/oidc/exchange", json={"code": "anything"})
        assert exchange.status_code == 503
        assert exchange.json()["detail"] == NOT_CONFIGURED

        verify = client.post("/mfa/verify", json={"mfa_token": "not-a-token", "code": "123456"})
        assert verify.status_code == 503
        assert verify.json()["detail"] == NOT_CONFIGURED

        assert client.get("/assets").status_code == 200
        uploaded = client.post(
            "/upload", files={"file": ("cube.stl", STL_BYTES, "model/stl")}
        )
        assert uploaded.status_code == 200, uploaded.text
        asset = uploaded.json()
        minted = client.post("/file-grants", json={"paths": [f"/file/{asset['id']}/{asset['filename']}"]})
        assert minted.status_code == 200, minted.text
