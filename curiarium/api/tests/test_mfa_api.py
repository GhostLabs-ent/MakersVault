"""Two-factor behaviour through the real HTTP surface (Mf-lg02).

The unit file (`test_mfa.py`) tests the primitives; this one tests the promises
an operator actually depends on, so every assertion is made through a request:

* AC-1 the enrolment lifecycle, end to end, and disable restoring a plain login;
* AC-4 the admin policy 403s every admin route until the *session* steps up, and
  `POST /settings/mfa` cannot be used to lock yourself out;
* AC-5 one challenge, one burned step - a replay is a 401;
* AC-7 a failed verify is a 401 that still keeps its committed audit row;
* AC-8 nothing else got weaker: auth-disabled still 503s, break-glass still signs
  in, the password throttle and the second (TOTP) limiter are separate, an OIDC
  session carries no marker, and neither a file grant nor `require_auth` accepts
  a challenge token;
* the takeover vector: a hijacked session cannot swap the second factor.

Time is frozen through `mfa._now` rather than slept through: a test that needs a
fresh 30-second bucket advances the clock, it does not wait for one.

The helpers at the top are also imported by `test_mfa.py` and `test_audit_log.py`
so the three files enrol accounts exactly one way.
"""

import json
import time
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, delete, select

import accounts
import audit
import auth
import config
import login_throttle as login_throttle_module
import main
import mfa
import oidc
import permissions
import sessions
import settings_service
from db import engine
from migrations import run_migrations
from models import AppConfig, AuditEvent, MfaRecoveryCode, OidcIdentity, User, UserSession

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
VIEWER_USERNAME = "viewer"
VIEWER_PASSWORD = "viewer-password-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}

# The throwaway account the MFA sweeps enrol. Exported so the audit sweep can
# name the actor it expects without ever enrolling the fixture admin.
MFA_USERNAME = "mfa-probe"
MFA_PASSWORD = "mfa-probe-password-1"

NOT_CONFIGURED = "Authentication is not configured on the server"
ALREADY_ENROLLED = "Two-factor authentication is already enabled"
NOT_ENROLLED = "Two-factor authentication is not enabled for this account"
INVALID_CODE = "Invalid or expired code"
POLICY_NEEDS_MFA = "Enrol two-factor authentication and step up before turning this policy on"
MFA_ROUTES = (
    ("GET", "/mfa"),
    ("POST", "/mfa/enrol"),
    ("POST", "/mfa/confirm"),
    ("POST", "/mfa/verify"),
    ("POST", "/mfa/step-up"),
    ("DELETE", "/mfa"),
    ("POST", "/mfa/recovery-codes"),
    ("POST", "/settings/mfa"),
)
# A body each route accepts, because the 503 guard runs *inside* the handler: a
# malformed body would be a 422 from fastapi's validation, before the guard.
DISABLED_BODIES = {
    ("GET", "/mfa"): None,
    ("POST", "/mfa/enrol"): {"password": "whatever"},
    ("POST", "/mfa/confirm"): {"password": "whatever", "secret": "AAAA", "code": "123456"},
    ("POST", "/mfa/verify"): {"mfa_token": "not-a-token", "code": "123456"},
    ("POST", "/mfa/step-up"): {"code": "123456"},
    ("DELETE", "/mfa"): {"password": "whatever"},
    ("POST", "/mfa/recovery-codes"): {"password": "whatever"},
    ("POST", "/settings/mfa"): {"require_admin": False},
}
# Well-formed but nonexistent ids, so a path template still routes to the guard.
PLACEHOLDER_ID = "00000000-0000-0000-0000-000000000000"
PLACEHOLDER_NAME = "20250101T000000Z-manual-000000"


@dataclass(frozen=True)
class Account:
    """A signed-in account: what the sweeps need to act as somebody."""

    user_id: str
    username: str
    password: str
    token: str
    refresh_token: str


@dataclass(frozen=True)
class Enrolled(Account):
    """An account with a confirmed second factor and its one-time recovery codes.

    `token` is the session that existed *before* enrolment - not `mfa_ok` - which
    is exactly what the takeover and step-up tests need to hold.
    """

    secret: str
    recovery_codes: list[str]


# --- helpers (shared with test_mfa.py and test_audit_log.py) ----------------


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ok(response: Response) -> Response:
    assert response.status_code == 200, response.text
    return response


def sign_in(client: TestClient, username: str, password: str) -> Response:
    """The `/login` request itself, assertion-free: callers check 401/429/200."""
    return client.post("/login", json={"username": username, "password": password})


def tokens(client: TestClient, username: str, password: str) -> dict:
    """A completed password login: the account has no second factor."""
    body = ok(sign_in(client, username, password)).json()
    assert body["mfa_required"] is False, f"{username} was asked for a second factor"
    assert body["token"], body
    return body


def challenge_token(client: TestClient, username: str, password: str) -> str:
    """The `mfa_token` `/login` answers for an enrolled account."""
    body = ok(sign_in(client, username, password)).json()
    assert body["mfa_required"] is True, f"{username} was not asked for a second factor"
    assert body["token"] is None and body["refresh_token"] is None, body
    return body["mfa_token"]


def current_code(secret: str) -> str:
    """The TOTP code for a base32 seed at the current wall-clock step."""
    raw = mfa.parse_secret(secret)
    assert raw is not None, f"{secret!r} is not a base32 seed"
    return mfa.totp_at(raw, mfa.current_step())


def never_valid_code(secret: str) -> str:
    """A six-digit code that cannot match `secret` inside the skew window.

    Enumerating the accepted codes makes "wrong" exact rather than a
    one-in-a-million accident, so no assertion here can flake.
    """
    raw = mfa.parse_secret(secret)
    assert raw is not None, f"{secret!r} is not a base32 seed"
    step = mfa.current_step()
    accepted = {
        mfa.totp_at(raw, step + offset)
        for offset in range(-mfa.TOTP_SKEW_STEPS, mfa.TOTP_SKEW_STEPS + 1)
    }
    candidate = 0
    while f"{candidate:06d}" in accepted:
        candidate += 1
    return f"{candidate:06d}"


def step_forward(monkeypatch: pytest.MonkeyPatch, *, steps: int = 1) -> int:
    """Freeze `mfa._now` `steps` periods ahead; returns the frozen step.

    `/mfa/confirm` burns the counter of the code it accepted, so a later
    verification needs a code from a different counter; advancing the frozen
    clock one step supplies one. Freezing beats sleeping and cannot flake.
    """
    frozen = time.time() + steps * mfa.TOTP_PERIOD
    monkeypatch.setattr(mfa, "_now", lambda: frozen)
    return mfa.current_step()


def create_user(
    client: TestClient,
    admin_token: str,
    username: str,
    password: str,
    role: str = "viewer",
) -> str:
    response = client.post(
        "/users",
        json={"username": username, "password": password, "role": role},
        headers=bearer(admin_token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def break_glass(client: TestClient) -> dict:
    """The bootstrap login, which only works while the users table is empty."""
    return tokens(client, **BREAK_GLASS)


def bootstrap_admin(client: TestClient) -> Account:
    """Break-glass creates the first admin, then everything runs as that account.

    The break-glass session is revoked by the create, in the same transaction,
    so this returns the real account's password session.
    """
    glass = break_glass(client)
    user_id = create_user(client, glass["token"], ADMIN_USERNAME, ADMIN_PASSWORD, role="admin")
    session = tokens(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    return Account(user_id, ADMIN_USERNAME, ADMIN_PASSWORD, session["token"], session["refresh_token"])


def enrol(client: TestClient, headers: dict[str, str], password: str) -> tuple[str, list[str]]:
    """Enrol the *calling* account; returns its base32 seed and recovery codes."""
    enrolment = ok(client.post("/mfa/enrol", json={"password": password}, headers=headers)).json()
    confirmed = ok(
        client.post(
            "/mfa/confirm",
            json={"password": password, "secret": enrolment["secret"], "code": current_code(enrolment["secret"])},
            headers=headers,
        )
    ).json()
    return enrolment["secret"], confirmed["recovery_codes"]


def enrol_account(
    client: TestClient,
    admin_token: str,
    *,
    username: str = MFA_USERNAME,
    password: str = MFA_PASSWORD,
    role: str = "viewer",
) -> Enrolled:
    """Create a throwaway account and enrol it, signed in as itself.

    The fixture admin must never be enrolled: `/login` would start answering a
    challenge mid-sweep and every later request would be a different scenario.
    """
    user_id = create_user(client, admin_token, username, password, role)
    session = tokens(client, username, password)
    secret, codes = enrol(client, bearer(session["token"]), password)
    return Enrolled(
        user_id=user_id,
        username=username,
        password=password,
        token=session["token"],
        refresh_token=session["refresh_token"],
        secret=secret,
        recovery_codes=codes,
    )


def sso_session(username: str = "sso-probe") -> tuple[str, str]:
    """An account with no password, the way the OIDC provisioning creates one."""
    with Session(engine) as session:
        user = accounts.create_sso_user(session, username)
        session.commit()
        row, _refresh = sessions.create(
            session,
            username=user.username,
            user_id=user.id,
            kind=sessions.OIDC_KIND,
            access_ttl=auth.AUTH_ACCESS_TOKEN_TTL,
            refresh_ttl=auth.AUTH_REFRESH_TTL_SECONDS,
        )
        session.commit()
        return user.id, auth.create_access_token(row, sessions.role_for(row, user))


def events_for(value: str) -> list[AuditEvent]:
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.request_id == value)).all())


def request_id(name: str) -> str:
    return f"{name}-{uuid4().hex}"


def session_row(sid: str) -> UserSession:
    with Session(engine) as session:
        row = session.get(UserSession, sid)
        assert row is not None
        return row


def stored_user(user_id: str) -> User:
    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        return user


def admin_keys() -> list[tuple[str, str]]:
    """Every ADMIN route in the matrix, so the policy sweep cannot miss one."""
    return sorted(key for key, level in permissions.ROUTE_PERMISSIONS.items() if level == permissions.ADMIN)


def call_route(client: TestClient, key: tuple[str, str], headers: dict[str, str]) -> Response:
    """One request against a matrix key, with every path template filled in."""
    method, path = key
    filled = (
        path.replace("{user_id}", PLACEHOLDER_ID)
        .replace("{session_id}", PLACEHOLDER_ID)
        .replace("{name}", PLACEHOLDER_NAME)
    )
    return client.request(method, filled, headers=headers)


# --- harness ----------------------------------------------------------------


def truncate_accounts() -> None:
    """Empty every auth table, children first: the foreign keys are enforced."""
    with Session(engine) as session:
        session.execute(delete(MfaRecoveryCode))
        session.execute(delete(OidcIdentity))
        session.execute(delete(UserSession))
        session.execute(delete(User))
        session.commit()


def stored_policy() -> Optional[str]:
    with Session(engine) as session:
        row = session.get(AppConfig, mfa.MFA_REQUIRE_ADMIN_KEY)
        return None if row is None else row.value


def restore_policy(value: Optional[str]) -> None:
    """Put the raw row back: a configuration with no row keeps none."""
    with Session(engine) as session:
        row = session.get(AppConfig, mfa.MFA_REQUIRE_ADMIN_KEY)
        if value is None:
            if row is not None:
                session.delete(row)
        elif row is None:
            session.add(AppConfig(key=mfa.MFA_REQUIRE_ADMIN_KEY, value=value))
        else:
            row.value = value
        session.commit()


@pytest.fixture(autouse=True)
def clean_state():
    """An empty auth surface and the shipped MFA policy, per test.

    The policy is restored raw rather than written back, because the rest of the
    suite asserts that a configuration with no rows keeps none.
    """
    run_migrations(engine)
    truncate_accounts()
    login_throttle_module.limiter.reset()
    login_throttle_module.mfa_limiter.reset()
    policy_before = stored_policy()
    yield
    truncate_accounts()
    login_throttle_module.limiter.reset()
    login_throttle_module.mfa_limiter.reset()
    restore_policy(policy_before)


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argon2's floor parameters: every test here bootstraps accounts."""
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture()
def client():
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture()
def admin(client: TestClient) -> Account:
    return bootstrap_admin(client)


# --- AC-1: the enrolment lifecycle -----------------------------------------


def test_ac1_enrol_confirm_login_verify_and_disable(client: TestClient, admin: Account, monkeypatch) -> None:
    create_user(client, admin.token, VIEWER_USERNAME, VIEWER_PASSWORD)
    session = tokens(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    headers = bearer(session["token"])

    assert ok(client.get("/mfa", headers=headers)).json() == {
        "enrolled": False,
        "enrolled_at": None,
        "recovery_codes_remaining": 0,
        "require_admin": False,
        "can_enrol": True,
    }

    enrolment = ok(client.post("/mfa/enrol", json={"password": VIEWER_PASSWORD}, headers=headers)).json()
    assert (enrolment["digits"], enrolment["period"], enrolment["algorithm"]) == (6, 30, "SHA1")
    assert "=" not in enrolment["secret"], "base32 must be served unpadded"
    assert enrolment["otpauth_uri"].startswith("otpauth://totp/Curiarium:viewer?")
    # Enrolment persists nothing: the account is still un-enrolled until confirm.
    assert ok(client.get("/mfa", headers=headers)).json()["enrolled"] is False

    codes = ok(
        client.post(
            "/mfa/confirm",
            json={
                "password": VIEWER_PASSWORD,
                "secret": enrolment["secret"],
                "code": current_code(enrolment["secret"]),
            },
            headers=headers,
        )
    ).json()["recovery_codes"]
    assert len(codes) == len(set(codes)) == mfa.RECOVERY_CODE_COUNT

    status = ok(client.get("/mfa", headers=headers)).json()
    assert status["enrolled"] is True
    assert status["recovery_codes_remaining"] == mfa.RECOVERY_CODE_COUNT
    assert status["enrolled_at"] is not None
    assert status["can_enrol"] is False

    # Confirm burned the counter of the code it accepted, so a later
    # verification needs a code from a different counter: advance the frozen
    # clock one period instead of sleeping.
    step_forward(monkeypatch)
    challenge = challenge_token(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    verified = ok(client.post("/mfa/verify", json={"mfa_token": challenge, "code": current_code(enrolment["secret"])}))
    body = verified.json()
    assert body["token"] and body["refresh_token"] and body["expires_in"]
    assert body["token_type"] == "bearer"
    assert body["mfa_required"] is False
    assert body["mfa_token"] is None

    # The session is born `mfa_ok`: the factor was proved in this very request.
    sid = auth.decode_access_token(body["token"])["sid"]
    assert session_row(sid).mfa_verified_at is not None
    assert ok(client.get("/me", headers=bearer(body["token"]))).json()["username"] == VIEWER_USERNAME

    disabled = client.request("DELETE", "/mfa", json={"password": VIEWER_PASSWORD}, headers=bearer(body["token"]))
    assert disabled.status_code == 204, disabled.text

    after = tokens(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    assert after["mfa_required"] is False and after["mfa_token"] is None
    final = ok(client.get("/mfa", headers=bearer(after["token"]))).json()
    assert final["enrolled"] is False
    assert final["recovery_codes_remaining"] == 0
    # The admin in this test never enrolled, which is what keeps every other
    # sweep's `/login` a plain login.
    assert tokens(client, ADMIN_USERNAME, ADMIN_PASSWORD)["mfa_required"] is False


def test_ac1_a_recovery_code_signs_in_once_and_is_audited(client: TestClient, admin: Account) -> None:
    enrolled = enrol_account(client, admin.token)

    challenge = challenge_token(client, enrolled.username, enrolled.password)
    value = request_id("recovery-sign-in")
    signed_in = client.post(
        "/mfa/verify",
        json={"mfa_token": challenge, "code": enrolled.recovery_codes[0]},
        headers={"X-Request-ID": value},
    )
    assert signed_in.status_code == 200, signed_in.text
    assert auth.decode_access_token(signed_in.json()["token"])["username"] == enrolled.username

    rows = events_for(value)
    assert [row.action for row in rows] == [audit.MFA_RECOVERY_CODE_USED]
    assert json.loads(rows[0].detail_json)["method"] == "recovery_code"
    assert ok(client.get("/mfa", headers=bearer(signed_in.json()["token"]))).json()["recovery_codes_remaining"] == (
        mfa.RECOVERY_CODE_COUNT - 1
    )

    # A one-time code is one-time: the second presentation of the same row is 401.
    replay = client.post(
        "/mfa/verify",
        json={"mfa_token": challenge_token(client, enrolled.username, enrolled.password), "code": enrolled.recovery_codes[0]},
    )
    assert replay.status_code == 401
    assert replay.json()["detail"] == INVALID_CODE


def test_every_response_carrying_a_secret_or_a_code_is_uncacheable(
    client: TestClient, admin: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A secret a proxy or a browser keeps is a secret that leaked."""
    create_user(client, admin.token, MFA_USERNAME, MFA_PASSWORD)
    headers = bearer(tokens(client, MFA_USERNAME, MFA_PASSWORD)["token"])

    enrolment = ok(client.post("/mfa/enrol", json={"password": MFA_PASSWORD}, headers=headers))
    confirmed = ok(
        client.post(
            "/mfa/confirm",
            json={
                "password": MFA_PASSWORD,
                "secret": enrolment.json()["secret"],
                "code": current_code(enrolment.json()["secret"]),
            },
            headers=headers,
        )
    )
    # `/login` now answers the challenge instead of tokens.
    challenge = ok(sign_in(client, MFA_USERNAME, MFA_PASSWORD))
    step_forward(monkeypatch)
    verified = ok(
        client.post(
            "/mfa/verify",
            json={
                "mfa_token": challenge.json()["mfa_token"],
                "code": current_code(enrolment.json()["secret"]),
            },
        )
    )
    regenerated = ok(client.post("/mfa/recovery-codes", json={"password": MFA_PASSWORD}, headers=headers))

    for name, response in {
        "login challenge": challenge,
        "enrol": enrolment,
        "confirm": confirmed,
        "verify": verified,
        "recovery-codes": regenerated,
    }.items():
        assert response.headers.get("Cache-Control") == "no-store", name


# --- AC-4: the admin policy -------------------------------------------------


def test_ac4_the_policy_403s_every_admin_route_until_the_session_steps_up(
    client: TestClient, admin: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = bearer(admin.token)
    secret, _codes = enrol(client, headers, admin.password)

    # Before the flag: an admin route is simply allowed.
    assert ok(client.get("/users", headers=headers))
    assert ok(client.get("/mfa", headers=headers)).json()["require_admin"] is False
    # A viewer is created now, while this admin session can still act: with the
    # policy on it could not create anything either.
    create_user(client, admin.token, VIEWER_USERNAME, VIEWER_PASSWORD)

    # The route refuses to turn the policy on for a session that could not
    # satisfy it - that refusal is what makes "no lockout reachable" true.
    refused = client.post("/settings/mfa", json={"require_admin": True}, headers=headers)
    assert refused.status_code == 409
    assert refused.json()["detail"] == POLICY_NEEDS_MFA
    assert ok(client.get("/mfa", headers=headers)).json()["require_admin"] is False

    # An operator turns it on out of band, and the sweep covers the whole matrix.
    with Session(engine) as session:
        settings_service.set_mfa_require_admin(True, session=session)
        session.commit()
    assert ok(client.get("/mfa", headers=headers)).json()["require_admin"] is True
    for key in admin_keys():
        response = call_route(client, key, headers)
        assert response.status_code == 403, f"{key} let an un-stepped-up admin through: {response.text}"
        assert response.json()["detail"] == permissions.MFA_REQUIRED_DETAIL
        # This account *is* enrolled, so the enrol-now hint must not be sent.
        assert permissions.MFA_ENROLMENT_HEADER not in response.headers

    # A viewer still gets the plain rank denial, not the MFA one.
    viewer = tokens(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    denied = client.get("/users", headers=bearer(viewer["token"]))
    assert denied.status_code == 403
    assert denied.json()["detail"] == permissions.DENY_DETAIL[permissions.ADMIN]

    # One step-up on this session and the whole matrix opens again.
    step_forward(monkeypatch)
    stepped = ok(client.post("/mfa/step-up", json={"code": current_code(secret)}, headers=headers))
    assert stepped.json() == {"mfa_verified": True}
    for key in admin_keys():
        response = call_route(client, key, headers)
        assert response.status_code != 403, f"{key} still refused the stepped-up admin: {response.text}"

    # The route flips the flag both ways, and records an explicit assertion each
    # time even when the value it lands on is the one it started from.
    off = request_id("policy-off")
    turned_off = client.post(
        "/settings/mfa", json={"require_admin": False}, headers={**headers, "X-Request-ID": off}
    )
    assert ok(turned_off).json() == {"require_admin": False}
    on = request_id("policy-on")
    turned_on = client.post("/settings/mfa", json={"require_admin": True}, headers={**headers, "X-Request-ID": on})
    assert ok(turned_on).json() == {"require_admin": True}
    assert [row.action for row in events_for(off)] == [audit.SETTINGS_MFA_REQUIRE_ADMIN_UPDATE]
    assert [row.action for row in events_for(on)] == [audit.SETTINGS_MFA_REQUIRE_ADMIN_UPDATE]
    assert json.loads(events_for(off)[0].detail_json) == {"from": True, "to": False}
    assert json.loads(events_for(on)[0].detail_json) == {"from": False, "to": True}
    assert ok(client.get("/users", headers=headers))


def test_ac4_an_admin_who_never_enrolled_is_told_to_enrol(
    client: TestClient, admin: Account
) -> None:
    """The 403 is one message for both cases; the header is the difference."""
    with Session(engine) as session:
        settings_service.set_mfa_require_admin(True, session=session)
        session.commit()

    response = client.get("/users", headers=bearer(admin.token))

    assert response.status_code == 403
    assert response.json()["detail"] == permissions.MFA_REQUIRED_DETAIL
    assert response.headers[permissions.MFA_ENROLMENT_HEADER] == "1"
    # The self-service routes stay reachable, so the hint is actionable.
    assert ok(client.get("/mfa", headers=bearer(admin.token))).json()["can_enrol"] is True


def test_ac4_an_admin_with_the_policy_on_cannot_disable_their_factor(
    client: TestClient, admin: Account
) -> None:
    headers = bearer(admin.token)
    enrol(client, headers, admin.password)
    with Session(engine) as session:
        settings_service.set_mfa_require_admin(True, session=session)
        session.commit()

    refused = client.request("DELETE", "/mfa", json={"password": admin.password}, headers=headers)

    assert refused.status_code == 409
    assert "cannot disable two-factor" in refused.json()["detail"]
    assert stored_user(admin.user_id).totp_secret is not None


# --- AC-5: one challenge, one burned step ----------------------------------


def test_ac5_a_replayed_challenge_cannot_burn_a_second_step(
    client: TestClient, admin: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    enrolled = enrol_account(client, admin.token)
    step_forward(monkeypatch)
    challenge = challenge_token(client, enrolled.username, enrolled.password)
    code = current_code(enrolled.secret)

    assert ok(client.post("/mfa/verify", json={"mfa_token": challenge, "code": code}))
    burned = stored_user(enrolled.user_id).totp_last_step

    replay = client.post("/mfa/verify", json={"mfa_token": challenge, "code": code})
    assert replay.status_code == 401
    assert replay.json()["detail"] == INVALID_CODE
    assert stored_user(enrolled.user_id).totp_last_step == burned

    # A fresh challenge for the same bucket is no better: the burn is per step.
    fresh = client.post(
        "/mfa/verify",
        json={"mfa_token": challenge_token(client, enrolled.username, enrolled.password), "code": code},
    )
    assert fresh.status_code == 401
    assert stored_user(enrolled.user_id).totp_last_step == burned


def test_ac5_a_skewed_code_burns_its_own_counter(
    client: TestClient, admin: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    enrolled = enrol_account(client, admin.token)
    # Confirm burned the counter it accepted (the unfrozen step); jump two
    # periods so the `step-1` and on-time codes here are both fresh.
    step_forward(monkeypatch, steps=2)
    on_time_step = mfa.current_step()
    early = mfa.totp_at(mfa.parse_secret(enrolled.secret), on_time_step - 1)

    assert ok(
        client.post(
            "/mfa/verify",
            json={"mfa_token": challenge_token(client, enrolled.username, enrolled.password), "code": early},
        )
    )
    assert stored_user(enrolled.user_id).totp_last_step == on_time_step - 1

    # Re-presenting the same skewed code is refused in whichever bucket it
    # arrives: `matching_step` always returns the code's own counter.
    replay = client.post(
        "/mfa/verify",
        json={"mfa_token": challenge_token(client, enrolled.username, enrolled.password), "code": early},
    )
    assert replay.status_code == 401
    assert stored_user(enrolled.user_id).totp_last_step == on_time_step - 1

    # A different, on-time code stays usable once: burning the early code does
    # not spend the current bucket.
    on_time = mfa.totp_at(mfa.parse_secret(enrolled.secret), on_time_step)
    assert ok(
        client.post(
            "/mfa/verify",
            json={"mfa_token": challenge_token(client, enrolled.username, enrolled.password), "code": on_time},
        )
    )
    assert stored_user(enrolled.user_id).totp_last_step == on_time_step


# --- AC-7: a failure is a 401 that still writes its row --------------------


def test_ac7_a_failed_verify_is_a_401_that_keeps_its_committed_row(
    client: TestClient, admin: Account
) -> None:
    enrolled = enrol_account(client, admin.token)
    wrong = never_valid_code(enrolled.secret)
    value = request_id("verify-failed")

    response = client.post(
        "/mfa/verify",
        json={"mfa_token": challenge_token(client, enrolled.username, enrolled.password), "code": wrong},
        headers={"X-Request-ID": value},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CODE
    rows = events_for(value)
    assert [row.action for row in rows] == [audit.MFA_VERIFY_FAILED]
    row = rows[0]
    assert row.target == enrolled.user_id
    assert row.actor == enrolled.username
    assert row.actor_kind == sessions.PASSWORD_KIND
    detail = json.loads(row.detail_json or "{}")
    assert detail["method"] == "unknown"
    assert detail["reason"] == "invalid_code"
    assert "client_ip" in detail
    # The submitted code itself never reaches the row.
    assert wrong not in (row.detail_json or "")


def test_ac7_an_unparseable_challenge_is_a_400_and_writes_nothing(
    client: TestClient, admin: Account
) -> None:
    value = request_id("bad-challenge")

    response = client.post(
        "/mfa/verify",
        json={"mfa_token": "not-a-token", "code": "123456"},
        headers={"X-Request-ID": value},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired challenge"
    assert events_for(value) == []


def test_a_failed_step_up_writes_nothing(client: TestClient, admin: Account) -> None:
    """`mfa.verify.failed` belongs to `/mfa/verify`; this session already exists."""
    headers = bearer(admin.token)
    secret, _codes = enrol(client, headers, admin.password)
    value = request_id("step-up-failed")

    response = client.post(
        "/mfa/step-up",
        json={"code": never_valid_code(secret)},
        headers={**headers, "X-Request-ID": value},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CODE
    assert events_for(value) == []


# --- AC-8: nothing else got weaker -----------------------------------------


def test_ac8_auth_disabled_answers_503_on_all_eight_routes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)

    for method, path in MFA_ROUTES:
        response = client.request(method, path, json=DISABLED_BODIES[(method, path)])
        assert response.status_code == 503, f"{method} {path} answered {response.status_code}"
        assert response.json()["detail"] == NOT_CONFIGURED

    assert client.get("/health").json()["auth_required"] is False


def test_ac8_break_glass_still_signs_in_and_is_exempt_with_the_policy_on(client: TestClient) -> None:
    with Session(engine) as session:
        settings_service.set_mfa_require_admin(True, session=session)
        session.commit()

    glass = break_glass(client)

    # Break-glass has no user row, so it can neither enrol nor step up; gating the
    # bootstrap path on a secret would be circular and unrecoverable.
    assert ok(client.get("/audit", headers=bearer(glass["token"])))


def test_ac8_the_password_throttle_still_locks_out(client: TestClient, admin: Account) -> None:
    username = "throttle-probe"

    for _attempt in range(config.LOGIN_MAX_FAILURES):
        assert sign_in(client, username, "wrong-password").status_code == 401

    locked = sign_in(client, username, "wrong-password")
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) >= 1


def test_ac8_the_second_limiter_buckets_totp_guesses_apart_from_passwords(
    client: TestClient, admin: Account
) -> None:
    enrolled = enrol_account(client, admin.token)

    for _attempt in range(config.LOGIN_MAX_FAILURES):
        challenge = challenge_token(client, enrolled.username, enrolled.password)
        guessed = client.post(
            "/mfa/verify",
            json={"mfa_token": challenge, "code": never_valid_code(enrolled.secret)},
        )
        assert guessed.status_code == 401, guessed.text

    locked = client.post(
        "/mfa/verify",
        json={"mfa_token": challenge_token(client, enrolled.username, enrolled.password), "code": never_valid_code(enrolled.secret)},
    )
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) >= 1

    # The password bucket for the same account was never touched: a spray of
    # wrong codes must not become a login denial-of-service lever.
    assert sign_in(client, enrolled.username, enrolled.password).status_code == 200


def test_ac8_step_up_shares_the_totp_limiter_with_verify(
    client: TestClient, admin: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    enrolled = enrol_account(client, admin.token)
    step_forward(monkeypatch)

    for _attempt in range(config.LOGIN_MAX_FAILURES):
        guessed = client.post(
            "/mfa/step-up",
            json={"code": never_valid_code(enrolled.secret)},
            headers=bearer(enrolled.token),
        )
        assert guessed.status_code == 401, guessed.text

    locked = client.post(
        "/mfa/step-up",
        json={"code": current_code(enrolled.secret)},
        headers=bearer(enrolled.token),
    )
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) >= 1

    # The password bucket for the same account was never touched.
    assert sign_in(client, enrolled.username, enrolled.password).status_code == 200


def test_ac8_the_oidc_exchange_is_unchanged_and_its_sessions_carry_no_marker(
    client: TestClient, admin: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "OIDC_ENABLED", True)
    monkeypatch.setattr(config, "OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setenv("PUBLIC_URL", "https://vault.example.com")
    code = oidc.park_handoff({"sub": "mfa-oidc-subject", "preferred_username": "sso-probe", "groups": []})

    response = client.post("/auth/oidc/exchange", json={"code": code})

    assert ok(response)
    body = response.json()
    assert body["mfa_required"] is False and body["mfa_token"] is None
    row = session_row(auth.decode_access_token(body["token"])["sid"])
    assert row.kind == sessions.OIDC_KIND
    assert row.mfa_verified_at is None, "an SSO login must not inherit a second factor"


def test_ac8_neither_a_file_grant_nor_require_auth_accepts_a_challenge_token(
    client: TestClient, admin: Account
) -> None:
    enrolled = enrol_account(client, admin.token)
    challenge = challenge_token(client, enrolled.username, enrolled.password)

    granted = client.get(f"/thumb/probe.jpg?sig={challenge}")

    assert granted.status_code == 401
    assert granted.json()["detail"] == "Invalid or expired token"
    assert client.get("/me", headers=bearer(challenge)).status_code == 401


def test_a_challenge_for_an_account_that_just_disabled_two_factor_is_a_401(
    client: TestClient, admin: Account
) -> None:
    """The factor can be removed between the challenge and its redemption.

    That must fail closed as a rejected credential; it must not raise through the
    handler on a `NULL` seed.
    """
    enrolled = enrol_account(client, admin.token)
    challenge = challenge_token(client, enrolled.username, enrolled.password)
    assert client.request("DELETE", "/mfa", json={"password": enrolled.password}, headers=bearer(enrolled.token)).status_code == 204

    response = client.post("/mfa/verify", json={"mfa_token": challenge, "code": current_code(enrolled.secret)})

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CODE


# --- the takeover vector ----------------------------------------------------


def test_a_hijacked_session_cannot_swap_or_add_a_second_factor(client: TestClient, admin: Account) -> None:
    enrolled = enrol_account(client, admin.token)
    hijacked = bearer(enrolled.token)

    # No password: the sudo gate refuses, so holding the session is not enough.
    assert client.post("/mfa/enrol", json={"password": "not-the-password"}, headers=hijacked).status_code == 403
    assert client.post(
        "/mfa/confirm",
        json={"password": "not-the-password", "secret": current_code(enrolled.secret), "code": "123456"},
        headers=hijacked,
    ).status_code == 403
    assert client.request("DELETE", "/mfa", json={"password": "not-the-password"}, headers=hijacked).status_code == 403
    assert client.post("/mfa/recovery-codes", json={"password": "not-the-password"}, headers=hijacked).status_code == 403

    # The password alone is not enough either: replacing a live factor is refused.
    for path in ("/mfa/enrol", "/mfa/confirm"):
        refusal = client.post(
            path,
            json={"password": enrolled.password, "secret": enrolled.secret, "code": current_code(enrolled.secret)},
            headers=hijacked,
        )
        assert refusal.status_code == 409, refusal.text
        assert refusal.json()["detail"] == ALREADY_ENROLLED

    # And the seeded factor is untouched.
    assert stored_user(enrolled.user_id).totp_secret is not None


# --- the SSO account --------------------------------------------------------


def test_an_sso_account_cannot_enrol_a_local_second_factor(client: TestClient) -> None:
    _user_id, token = sso_session()

    status = ok(client.get("/mfa", headers=bearer(token))).json()

    assert status["enrolled"] is False
    assert status["can_enrol"] is False, "the identity provider owns an SSO credential"
    refusal = client.post("/mfa/enrol", json={"password": "anything-at-all"}, headers=bearer(token))
    assert refusal.status_code == 409
    assert "SSO" in refusal.json()["detail"]


def test_a_not_enrolled_account_gets_409_from_every_factor_route(client: TestClient, admin: Account) -> None:
    create_user(client, admin.token, MFA_USERNAME, MFA_PASSWORD)
    headers = bearer(tokens(client, MFA_USERNAME, MFA_PASSWORD)["token"])
    body = {"password": MFA_PASSWORD, "code": "123456"}

    for method, path in (
        ("POST", "/mfa/step-up"),
        ("DELETE", "/mfa"),
        ("POST", "/mfa/recovery-codes"),
    ):
        response = client.request(method, path, json=body, headers=headers)
        assert response.status_code == 409, f"{method} {path} answered {response.status_code}"
        assert response.json()["detail"] == NOT_ENROLLED


def test_regenerating_codes_replaces_the_old_set(client: TestClient, admin: Account) -> None:
    enrolled = enrol_account(client, admin.token)
    headers = bearer(enrolled.token)

    fresh = ok(client.post("/mfa/recovery-codes", json={"password": enrolled.password}, headers=headers)).json()[
        "recovery_codes"
    ]

    assert len(fresh) == mfa.RECOVERY_CODE_COUNT
    assert not set(fresh) & set(enrolled.recovery_codes)
    assert ok(client.get("/mfa", headers=headers)).json()["recovery_codes_remaining"] == mfa.RECOVERY_CODE_COUNT
    spent = client.post(
        "/mfa/verify",
        json={"mfa_token": challenge_token(client, enrolled.username, enrolled.password), "code": enrolled.recovery_codes[0]},
    )
    assert spent.status_code == 401, "the replaced codes must be gone"
