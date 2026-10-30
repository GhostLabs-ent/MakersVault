"""The TOTP and recovery-code primitives (Mf-lg02), tested without a request.

Four properties are worth more than the rest and each gets its own test here:

* the OTP arithmetic is the RFC's, not ours: the vectors are the published ones;
* the seed is encrypted, not hashed, and a rotated `AUTH_SECRET` fails closed;
* a recovery code is peppered, and single use is a guarded UPDATE that survives
  two threads racing the same code;
* an accepted code burns its own counter, so it cannot be replayed in any
  wall-clock bucket.

The last test drives the API only to prove a negative: no secret, code or hash
ever reaches an audit `detail_json` or a log record.
"""

import hashlib
import logging
import re
import threading

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

import accounts
import audit
import auth
import login_throttle as login_throttle_module
import main
import mfa
import settings_service
from db import engine
from migrations import run_migrations
from models import AppConfig, AuditEvent, MfaRecoveryCode, User, UserSession

# RFC 4226 §4's recommended 160-bit seed, the one both RFC appendices use.
RFC_SEED = b"12345678901234567890"

# RFC 6238 Appendix B, SHA1 rows: (unix seconds, the eight-digit code). The
# module is pinned at six digits and an eight-digit code's last six digits are
# exactly the six-digit value of the same dynamic truncation, so the comparison
# is the published vector rather than one invented here.
RFC6238_SHA1_VECTORS = (
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
)

# RFC 4226 Appendix D: the same seed, counters 0-9, six digits.
RFC4226_VECTORS = (
    "755224",
    "287082",
    "359152",
    "969429",
    "338314",
    "254676",
    "287922",
    "162583",
    "399871",
    "520489",
)


# --- harness ----------------------------------------------------------------


def truncate_accounts() -> None:
    """Empty every auth table; recovery codes first, they hold the foreign key."""
    with Session(engine) as session:
        session.execute(delete(MfaRecoveryCode))
        session.execute(delete(UserSession))
        session.execute(delete(User))
        session.commit()


@pytest.fixture(autouse=True)
def clean_accounts():
    run_migrations(engine)
    truncate_accounts()
    login_throttle_module.limiter.reset()
    login_throttle_module.mfa_limiter.reset()
    yield
    truncate_accounts()
    login_throttle_module.limiter.reset()
    login_throttle_module.mfa_limiter.reset()


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argon2's floor parameters: this file creates accounts, it does not measure them."""
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture()
def client():
    with TestClient(main.app) as test_client:
        yield test_client


def create_user(username: str = "mfa-unit", password: str = "mfa-unit-password") -> str:
    """One committed account, so the guarded UPDATEs have a row to fight over."""
    with Session(engine) as session:
        user = accounts.create_user(session, username, password, role=accounts.DEFAULT_ROLE)
        session.commit()
        return user.id


def stored_step(user_id: str) -> int | None:
    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        return user.totp_last_step


def frozen_clock(monkeypatch: pytest.MonkeyPatch, moment: float) -> int:
    """Freeze `mfa._now`, the module's one clock seam; returns the current step."""
    monkeypatch.setattr(mfa, "_now", lambda: moment)
    return mfa.current_step()


# --- RFC conformance --------------------------------------------------------


def test_hotp_reproduces_the_rfc4226_appendix_d_vectors() -> None:
    for counter, expected in enumerate(RFC4226_VECTORS):
        assert mfa.hotp(RFC_SEED, counter) == expected, f"counter {counter}"


def test_totp_reproduces_the_rfc6238_sha1_vectors() -> None:
    for moment, eight_digits in RFC6238_SHA1_VECTORS:
        step = moment // mfa.TOTP_PERIOD
        # The 8-digit vector's tail is the 6-digit value of the same truncation.
        assert mfa.totp_at(RFC_SEED, step) == eight_digits[-6:], f"{moment}s"
        assert mfa.current_step(float(moment)) == step


def test_a_code_is_always_six_digits() -> None:
    secret = mfa.new_secret()
    for step in range(20):
        code = mfa.totp_at(secret, step)
        assert len(code) == mfa.TOTP_DIGITS
        assert code.isdigit()


# --- seed storage -----------------------------------------------------------


def test_a_seed_round_trips_through_encryption() -> None:
    secret = mfa.new_secret()

    blob = mfa.encrypt_seed(secret)

    assert mfa.decrypt_seed(blob) == secret
    assert mfa.base32_secret(secret) not in blob, "the base32 seed must not survive in the ciphertext"


def test_two_encryptions_of_one_seed_differ() -> None:
    secret = mfa.new_secret()

    first, second = mfa.encrypt_seed(secret), mfa.encrypt_seed(secret)

    assert first != second, "a reused nonce would be the whole failure mode of GCM"
    assert mfa.decrypt_seed(first) == mfa.decrypt_seed(second) == secret


def test_a_rotated_secret_fails_closed_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    blob = mfa.encrypt_seed(b"a stored seed")
    monkeypatch.setattr(auth, "AUTH_SECRET", "a-completely-different-secret")

    assert mfa.decrypt_seed(blob) is None


@pytest.mark.parametrize("junk", ["", "not-base64!!", "AAAA", "   "])
def test_junk_is_not_a_seed(junk: str) -> None:
    assert mfa.decrypt_seed(junk) is None


def test_base32_is_unpadded_uppercase_and_parses_back() -> None:
    secret = mfa.new_secret()

    encoded = mfa.base32_secret(secret)

    assert encoded == encoded.upper()
    assert "=" not in encoded
    assert mfa.parse_secret(encoded) == secret
    # Whitespace and lower case are presentation, not entropy.
    assert mfa.parse_secret(f" {encoded.lower()} ") == secret


@pytest.mark.parametrize("junk", ["", "   ", "!!!!", "A"])
def test_junk_is_not_a_base32_secret(junk: str) -> None:
    assert mfa.parse_secret(junk) is None


# --- the recovery-code pepper ----------------------------------------------


def test_a_recovery_code_hash_is_not_a_bare_sha256() -> None:
    code = mfa.new_recovery_code()

    peppered = mfa.hash_recovery_code(code)

    assert peppered != hashlib.sha256(code.encode()).hexdigest()
    assert peppered != hashlib.sha256(mfa.normalize_recovery_code(code).encode()).hexdigest()


def test_the_pepper_comes_from_auth_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    code = mfa.new_recovery_code()
    before = mfa.hash_recovery_code(code)

    monkeypatch.setattr(auth, "AUTH_SECRET", "a-rotated-auth-secret")

    assert mfa.hash_recovery_code(code) != before


def test_the_same_code_hashes_the_same_however_it_is_typed() -> None:
    code = mfa.new_recovery_code()
    shown = mfa.format_recovery_code(code)

    assert mfa.hash_recovery_code(shown) == mfa.hash_recovery_code(code)
    assert mfa.hash_recovery_code(shown.lower()) == mfa.hash_recovery_code(f" {shown} ")


def test_recovery_codes_avoid_ambiguous_characters_and_are_grouped() -> None:
    code = mfa.new_recovery_code()

    assert len(set(mfa.RECOVERY_CODE_ALPHABET)) == len(mfa.RECOVERY_CODE_ALPHABET) == 32
    assert len(code) == mfa.RECOVERY_CODE_LENGTH
    assert set(code) <= set(mfa.RECOVERY_CODE_ALPHABET)
    # The four characters a reader confuses, and nothing else, are missing.
    assert not set(code) & set("01IO")
    assert re.fullmatch(
        rf"[{mfa.RECOVERY_CODE_ALPHABET}]{{5}}-[{mfa.RECOVERY_CODE_ALPHABET}]{{5}}",
        mfa.format_recovery_code(code),
    )


def test_an_enrolment_generates_ten_codes_and_never_stores_them_in_the_clear() -> None:
    user_id = create_user()
    with Session(engine) as session:
        codes = mfa.create_recovery_codes(session, user_id)
        session.commit()
        remaining = mfa.remaining_recovery_codes(session, user_id)
        hashes = {row.code_hmac for row in session.exec(select(MfaRecoveryCode)).all()}

    assert len(codes) == len(set(codes)) == mfa.RECOVERY_CODE_COUNT
    assert remaining == mfa.RECOVERY_CODE_COUNT
    assert hashes == {mfa.hash_recovery_code(code) for code in codes}
    assert not set(codes) & hashes


# --- single use -------------------------------------------------------------


def test_a_recovery_code_is_spent_exactly_once() -> None:
    user_id = create_user()
    with Session(engine) as session:
        codes = mfa.create_recovery_codes(session, user_id)
        session.commit()
        assert mfa.consume_recovery_code(session, user_id, codes[0]) is True
        session.commit()
        assert mfa.consume_recovery_code(session, user_id, codes[0]) is False
        session.commit()
        assert mfa.remaining_recovery_codes(session, user_id) == mfa.RECOVERY_CODE_COUNT - 1


def test_two_threads_spending_one_recovery_code_produce_exactly_one_winner() -> None:
    """The single-use guard is an UPDATE, not a read-modify-write.

    Both sessions hold no prior state, so the two statements genuinely race for
    the write lock; the `used_at IS NULL` predicate is what makes the loser see
    zero rows no matter how the interleaving lands.
    """
    user_id = create_user()
    with Session(engine) as session:
        codes = mfa.create_recovery_codes(session, user_id)
        session.commit()
    code = codes[0]
    barrier = threading.Barrier(2)
    results: list[bool] = []
    results_lock = threading.Lock()

    def spend() -> None:
        with Session(engine) as session:
            barrier.wait(timeout=10)
            won = mfa.consume_recovery_code(session, user_id, code)
            session.commit()
            with results_lock:
                results.append(won)

    threads = [threading.Thread(target=spend) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == [False, True], results
    with Session(engine) as session:
        assert mfa.remaining_recovery_codes(session, user_id) == mfa.RECOVERY_CODE_COUNT - 1


def test_a_consumed_recovery_code_is_refused_for_another_account() -> None:
    owner = create_user("mfa-owner")
    other = create_user("mfa-other")
    with Session(engine) as session:
        codes = mfa.create_recovery_codes(session, owner)
        session.commit()
        assert mfa.consume_recovery_code(session, other, codes[0]) is False


# --- one step, one acceptance ----------------------------------------------


def test_a_time_step_is_burned_exactly_once() -> None:
    user_id = create_user()
    step = mfa.current_step()

    with Session(engine) as session:
        assert mfa.consume_totp_step(session, user_id, step) is True
        session.commit()
    assert stored_step(user_id) == step

    with Session(engine) as session:
        assert mfa.consume_totp_step(session, user_id, step) is False
        session.commit()
    assert stored_step(user_id) == step, "the losing attempt must not move the column"


def test_the_step_column_never_goes_backwards() -> None:
    user_id = create_user()
    with Session(engine) as session:
        assert mfa.consume_totp_step(session, user_id, 1000) is True
        session.commit()

    with Session(engine) as session:
        assert mfa.consume_totp_step(session, user_id, 999) is False
        session.commit()

    assert stored_step(user_id) == 1000


def test_the_skew_window_is_one_step_either_side(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = mfa.new_secret()
    step = frozen_clock(monkeypatch, 1_700_000_000.0)

    assert mfa.matching_step(secret, mfa.totp_at(secret, step - 1)) == step - 1
    assert mfa.matching_step(secret, mfa.totp_at(secret, step)) == step
    assert mfa.matching_step(secret, mfa.totp_at(secret, step + 1)) == step + 1
    assert mfa.matching_step(secret, mfa.totp_at(secret, step - 2)) is None
    assert mfa.matching_step(secret, mfa.totp_at(secret, step + 2)) is None


def test_a_skewed_code_burns_its_own_counter_not_the_wall_clock_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tolerance for clock error must not become a replay window (AC-6).

    `matching_step` always returns the code's own counter, so burning it means
    the `step-1` code is accepted once and refused if presented again in the
    next bucket, while the on-time `step` code - a different code - is still
    accepted once.
    """
    secret = mfa.new_secret()
    user_id = create_user()
    step = frozen_clock(monkeypatch, 1_700_000_000.0)
    early = mfa.totp_at(secret, step - 1)

    matched = mfa.matching_step(secret, early)
    assert matched == step - 1
    with Session(engine) as session:
        assert mfa.consume_totp_step(session, user_id, matched) is True
        session.commit()
    assert stored_step(user_id) == step - 1

    on_time = mfa.totp_at(secret, step)
    matched_on_time = mfa.matching_step(secret, on_time)
    assert matched_on_time == step
    with Session(engine) as session:
        assert mfa.consume_totp_step(session, user_id, matched_on_time) is True
        session.commit()
    assert stored_step(user_id) == step


def test_a_code_cannot_be_replayed_in_the_next_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ±1 window is tolerance for clock error, not a replay window.

    A code for counter C is still accepted at wall step C+1 as the `-1` offset,
    but `matching_step` returns C both times and C is already burned, so the
    second presentation is refused and the column does not move.
    """
    secret = mfa.new_secret()
    user_id = create_user()
    step = frozen_clock(monkeypatch, 1_700_000_000.0)
    code = mfa.totp_at(secret, step)

    matched = mfa.matching_step(secret, code)
    assert matched == step
    with Session(engine) as session:
        assert mfa.consume_totp_step(session, user_id, matched) is True
        session.commit()
    assert stored_step(user_id) == step

    frozen_clock(monkeypatch, 1_700_000_000.0 + mfa.TOTP_PERIOD)
    replay = mfa.matching_step(secret, code)
    assert replay == step, "the same code still matches one bucket later"
    with Session(engine) as session:
        assert mfa.consume_totp_step(session, user_id, replay) is False
    assert stored_step(user_id) == step, "a refused replay must not move the column"


def test_a_plus_one_code_cannot_be_replayed_across_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `+1` code is accepted as the `+1` offset once, then refused twice more."""
    secret = mfa.new_secret()
    user_id = create_user()
    step = frozen_clock(monkeypatch, 1_700_000_000.0)
    code = mfa.totp_at(secret, step + 1)

    matched = mfa.matching_step(secret, code)
    assert matched == step + 1
    with Session(engine) as session:
        assert mfa.consume_totp_step(session, user_id, matched) is True
        session.commit()
    assert stored_step(user_id) == step + 1

    # The code is still inside the window at wall steps C and C+1, but both
    # presentations return its own counter and lose to the monotone guard.
    for offset in (1, 2):
        frozen_clock(monkeypatch, 1_700_000_000.0 + offset * mfa.TOTP_PERIOD)
        replay = mfa.matching_step(secret, code)
        assert replay == step + 1
        with Session(engine) as session:
            assert mfa.consume_totp_step(session, user_id, replay) is False
        assert stored_step(user_id) == step + 1


def test_a_submitted_code_is_compared_after_trimming_only() -> None:
    secret = mfa.new_secret()
    step = mfa.current_step()
    code = mfa.totp_at(secret, step)

    assert mfa.matching_step(secret, f"  {code} ") == step
    assert mfa.matching_step(secret, "") is None
    assert mfa.matching_step(secret, code[:-1]) is None


# --- enrolment state helpers ------------------------------------------------


def test_enrolment_and_session_helpers_read_the_stored_state() -> None:
    user_id = create_user()
    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        assert mfa.user_is_enrolled(user) is False
        user.totp_secret = mfa.encrypt_seed(mfa.new_secret())
        session.commit()

        session_row = UserSession(
            user_id=user.id,
            username=user.username,
            kind="password",
            refresh_token_hash="hash",
            created_at=0,
            last_used_at=0,
            access_expires_at=0,
            refresh_expires_at=0,
        )
        assert mfa.mfa_ok(session_row) is False
        assert mfa.mfa_ok(None) is False
        session_row.mfa_verified_at = 1
        assert mfa.mfa_ok(session_row) is True

    assert mfa.user_is_enrolled(None) is False


def test_the_otpauth_uri_is_what_an_authenticator_scans() -> None:
    secret = mfa.new_secret()

    uri = mfa.otpauth_uri(secret=secret, username="jane doe@example.com")

    assert uri.startswith("otpauth://totp/Curiarium:jane%20doe%40example.com?")
    assert f"secret={mfa.base32_secret(secret)}" in uri
    for parameter in ("issuer=Curiarium", "algorithm=SHA1", "digits=6", "period=30"):
        assert parameter in uri


# --- nothing sensitive is written down -------------------------------------


def test_no_secret_code_or_hash_reaches_an_audit_row_or_a_log_record(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The one test here that needs a request: the audit row is the router's.

    A whole enrolment is driven through the API and then every `detail_json` and
    every captured log record is searched for the seed, each recovery code and
    each hash of them. Asserting absence is the only honest form of this check.
    """
    caplog.set_level(logging.DEBUG)
    glass = client.post("/login", json={"username": "admin", "password": "super-secret"})
    assert glass.status_code == 200, glass.text
    admin_token = glass.json()["token"]
    created = client.post(
        "/users",
        json={"username": "mfa-leak", "password": "mfa-leak-password", "role": "viewer"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert created.status_code == 201, created.text
    token = client.post("/login", json={"username": "mfa-leak", "password": "mfa-leak-password"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    secret = client.post("/mfa/enrol", json={"password": "mfa-leak-password"}, headers=headers).json()["secret"]
    code = mfa.totp_at(mfa.parse_secret(secret), mfa.current_step())
    confirmed = client.post(
        "/mfa/confirm",
        json={"password": "mfa-leak-password", "secret": secret, "code": code},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    recovery_codes = confirmed.json()["recovery_codes"]

    with Session(engine) as session:
        seeded = session.get(User, created.json()["id"])
        assert seeded is not None
        stored_secret = seeded.totp_secret
    assert stored_secret is not None and secret not in stored_secret

    rows = audit_rows()
    haystacks = [f"{row.action} {row.target} {row.detail_json or ''}" for row in rows]
    haystacks.append(" ".join(record.getMessage() for record in caplog.records))
    haystacks.append(" ".join(str(record.args) for record in caplog.records))
    assert haystacks, "the enrolment must have written something to search"
    for haystack in haystacks:
        assert secret not in haystack
        assert stored_secret not in haystack
        assert mfa.hash_recovery_code(secret) not in haystack
        for recovery_code in recovery_codes:
            assert recovery_code not in haystack
            assert mfa.hash_recovery_code(recovery_code) not in haystack


def audit_rows() -> list[AuditEvent]:
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent)).all())


def test_the_policy_setting_round_trips_through_one_owner() -> None:
    """`settings_service` owns the key and `mfa` names it, so they cannot drift."""
    assert settings_service.MFA_REQUIRE_ADMIN_KEY == mfa.MFA_REQUIRE_ADMIN_KEY == "mfa_require_admin"

    with Session(engine) as session:
        existing = session.get(AppConfig, mfa.MFA_REQUIRE_ADMIN_KEY)
        previous = None if existing is None else existing.value
    try:
        settings_service.set_mfa_require_admin(True)
        assert settings_service.get_mfa_require_admin() is True
        settings_service.set_mfa_require_admin(False)
        assert settings_service.get_mfa_require_admin() is False
    finally:
        # Raw restore, not a write-back: a configuration with no row keeps none.
        with Session(engine) as session:
            row = session.get(AppConfig, mfa.MFA_REQUIRE_ADMIN_KEY)
            if previous is None:
                if row is not None:
                    session.delete(row)
            elif row is None:
                session.add(AppConfig(key=mfa.MFA_REQUIRE_ADMIN_KEY, value=previous))
            else:
                row.value = previous
            session.commit()


def test_the_audit_actions_this_module_can_emit_are_declared() -> None:
    declared = {
        audit.MFA_ENROL_START,
        audit.MFA_ENROL,
        audit.MFA_VERIFY_SUCCEEDED,
        audit.MFA_VERIFY_FAILED,
        audit.MFA_RECOVERY_CODE_USED,
        audit.MFA_STEP_UP,
        audit.MFA_DISABLE,
        audit.MFA_RECOVERY_CODES_REGENERATE,
        audit.SETTINGS_MFA_REQUIRE_ADMIN_UPDATE,
    }

    assert declared <= audit.ACTIONS
    assert len({action for action in declared}) == len(declared)
    for key in (
        ("POST", "/mfa/enrol"),
        ("POST", "/mfa/confirm"),
        ("POST", "/mfa/verify"),
        ("POST", "/mfa/step-up"),
        ("DELETE", "/mfa"),
        ("POST", "/mfa/recovery-codes"),
        ("POST", "/settings/mfa"),
    ):
        assert key in audit.ROUTE_ACTIONS
