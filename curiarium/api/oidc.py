"""OIDC / SSO login: Authorization Code + PKCE against an external IdP.

The flow, and why each step is shaped this way:

- `GET /auth/oidc/start` mints `state`, `nonce` and a PKCE verifier and parks
  them in a capped, swept, single-use in-process store. The `state` is mirrored
  into a non-credential `HttpOnly; Secure; SameSite=Lax; Path=/auth/oidc` cookie
  so the callback can prove it is the same browser that started the flow.
- `GET /auth/oidc/callback` consumes the state, exchanges the code server-side
  (the client secret never reaches a browser), verifies the `id_token` against a
  cached JWKS with a pinned algorithm allow-list, checks issuer/audience/nonce,
  evaluates the allow-list, and parks a single-use 120-second handoff code. It
  writes no user, session or identity row.
- `POST /auth/oidc/exchange` is the one mutation: it provisions or links the
  account, opens a session and stages the audit event in a single transaction.

Identity binds ONLY on the persisted, unique `(issuer, subject)` pair. Matching
on username or email instead would let any account at the provider claim an
existing local account by naming it, which is an account-takeover path.

The two stores are in-process dicts: they die on restart and are not shared
across uvicorn workers. That is correct today because the deployment runs a
single process with no `--workers`, and it is written down as a latent contract
in ADR 0006 rather than left for someone to discover.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWTError
from sqlmodel import Session, select

import accounts
import auth
import config
from models import OidcIdentity, User

log = logging.getLogger(__name__)

# The state cookie is a binding value, not a credential: it is compared against
# the state in the URL and carries no authority on its own.
STATE_COOKIE_NAME = "mv_oidc_state"
STATE_COOKIE_PATH = "/auth/oidc"
STATE_TTL_SECONDS = 600
HANDOFF_TTL_SECONDS = 120
CALLBACK_PATH = "/auth/oidc/callback"

# The stores are bounded so the public `start` route cannot be turned into a
# memory-exhaustion button; `_StartLimiter` bounds the rate on top of that.
STORE_CAP = 1024
JWKS_CACHE_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 10

# `none` and every HMAC algorithm are refused: accepting a caller-chosen
# algorithm is the classic JWT confusion attack, and a symmetric algorithm here
# would let a leaked id_token be re-signed.
ALLOWED_ID_TOKEN_ALGS = frozenset({"RS256", "ES256"})

# The frozen `sso_error` vocabulary. Every rejection maps to exactly one of
# these, the web client owns a fixed sentence per value, and no provider free
# text ever reaches a URL, a log line or an audit row.
SSO_ERROR_STATE_MISSING = "state_missing"
SSO_ERROR_STATE_UNKNOWN = "state_unknown"
SSO_ERROR_STATE_REPLAYED = "state_replayed"
SSO_ERROR_STATE_EXPIRED = "state_expired"
SSO_ERROR_COOKIE_MISMATCH = "cookie_mismatch"
SSO_ERROR_NONCE_MISMATCH = "nonce_mismatch"
SSO_ERROR_TOKEN_INVALID = "token_invalid"
SSO_ERROR_PROVIDER_UNAVAILABLE = "provider_unavailable"
SSO_ERROR_PROVIDER_REJECTED = "provider_rejected"
SSO_ERROR_GROUP_NOT_ALLOWED = "group_not_allowed"
SSO_ERROR_DOMAIN_NOT_ALLOWED = "domain_not_allowed"
SSO_ERROR_NO_ADMIN_BOOTSTRAP = "no_admin_bootstrap"
SSO_ERROR_EXCHANGE_FAILED = "exchange_failed"
SSO_ERRORS = frozenset(
    {
        SSO_ERROR_STATE_MISSING,
        SSO_ERROR_STATE_UNKNOWN,
        SSO_ERROR_STATE_REPLAYED,
        SSO_ERROR_STATE_EXPIRED,
        SSO_ERROR_COOKIE_MISMATCH,
        SSO_ERROR_NONCE_MISMATCH,
        SSO_ERROR_TOKEN_INVALID,
        SSO_ERROR_PROVIDER_UNAVAILABLE,
        SSO_ERROR_PROVIDER_REJECTED,
        SSO_ERROR_GROUP_NOT_ALLOWED,
        SSO_ERROR_DOMAIN_NOT_ALLOWED,
        SSO_ERROR_NO_ADMIN_BOOTSTRAP,
        SSO_ERROR_EXCHANGE_FAILED,
    }
)

# Per-IP cap on `/auth/oidc/start`. The state store is bounded, so an uncapped
# start route would let one client fill it and lock every legitimate login out.
START_MAX_ATTEMPTS = 30
START_WINDOW_SECONDS = 60
START_MAX_BUCKETS = 1024

# Indirection so a test can move the clock without sleeping.
_now = time.monotonic


class ProviderError(Exception):
    """The identity provider could not be reached or answered unusably."""


class TokenRejected(Exception):
    """An id_token (or its absence) failed verification; carries the sso_error."""

    def __init__(self, sso_error: str) -> None:
        super().__init__(sso_error)
        self.sso_error = sso_error


class HandoffRejected(Exception):
    """The handoff code is unknown, already spent, expired or unusable."""


class NoAdminBootstrap(Exception):
    """Provisioning was refused because no enabled administrator exists."""


class StoreFull(Exception):
    """The bounded store is at capacity; the caller must refuse, not evict."""


@dataclass
class _PendingLogin:
    """One in-flight authorization request, keyed by its `state`."""

    nonce: str
    code_verifier: str


@dataclass
class _Handoff:
    """A verified identity waiting for the one request that will spend it."""

    issuer: str
    subject: str
    username: str
    email: Optional[str]
    role: str


class _ExpiringStore:
    """A capped, swept, single-use in-process store.

    Consumed entries are kept until their TTL so a replay is distinguishable
    from an unknown key - "someone already used this link" is a different answer
    from "this link was never ours", and the operator needs both. Expired entries
    are swept on every write and read, so the dict stays bounded by the TTL and
    the cap rather than by traffic.
    """

    def __init__(self, *, cap: int = STORE_CAP) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[Any, float, bool]] = {}
        self._cap = cap

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()

    def _sweep(self, now: float) -> None:
        """Drop every expired entry. Callers hold the lock."""
        expired = [key for key, (_, expires_at, _) in self._entries.items() if now >= expires_at]
        for key in expired:
            del self._entries[key]

    def put(self, key: str, value: Any, ttl: float) -> None:
        now = _now()
        with self._lock:
            self._sweep(now)
            if key not in self._entries and len(self._entries) >= self._cap:
                # Never evict a live entry to make room: displacing a login that
                # is mid-flight is worse than refusing a new one.
                raise StoreFull(key)
            self._entries[key] = (value, now + ttl, False)

    def consume(self, key: str) -> tuple[Optional[Any], Optional[str]]:
        """Spend an entry once; returns (value, reason) with reason in `replayed`/`expired`/`unknown`."""
        now = _now()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None, "unknown"
            value, expires_at, consumed = entry
            if consumed:
                return None, "replayed"
            if now >= expires_at:
                del self._entries[key]
                return None, "expired"
            self._entries[key] = (value, expires_at, True)
            return value, None


class _StartLimiter:
    """A fixed-window, per-IP cap on the public start route.

    Deliberately separate from `login_throttle.limiter`: that one counts
    credential failures per submitted username, and entangling a route that takes
    no credentials with it would let an SSO flood lock a local account out.
    """

    def __init__(self, *, limit: int = START_MAX_ATTEMPTS, window: int = START_WINDOW_SECONDS) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, tuple[int, float]] = {}
        self._limit = limit
        self._window = window

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _prune(self, now: float) -> None:
        stale = [key for key, (_, start) in self._hits.items() if now - start >= self._window]
        for key in stale:
            del self._hits[key]
        if len(self._hits) > START_MAX_BUCKETS:
            # One shared bucket for the overflow, so the table cannot grow with
            # the number of source addresses seen.
            self._hits.clear()
            self._hits["overflow"] = (self._limit, now)

    def retry_after(self, key: str) -> int:
        now = _now()
        with self._lock:
            self._prune(now)
            count, start = self._hits.get(key, (0, now))
            if now - start >= self._window:
                return 0
            if count < self._limit:
                return 0
            return int(self._window - (now - start)) + 1

    def record(self, key: str) -> None:
        now = _now()
        with self._lock:
            self._prune(now)
            count, start = self._hits.get(key, (0, now))
            if now - start >= self._window:
                count, start = 0, now
            self._hits[key] = (count + 1, start)


pending_logins = _ExpiringStore()
handoff_codes = _ExpiringStore()
start_limiter = _StartLimiter()

_discovery_cache: dict[str, tuple[float, dict]] = {}
_jwks_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def reset() -> None:
    """Clear every in-process store and cache.

    Called from `main.lifespan` so a restarted process never inherits a spent
    state, and by every OIDC test so one test cannot see another's login.
    """
    pending_logins.reset()
    handoff_codes.reset()
    start_limiter.reset()
    with _cache_lock:
        _discovery_cache.clear()
        _jwks_cache.clear()


# --- configuration ----------------------------------------------------------


def _csv(raw: str) -> tuple[str, ...]:
    """A comma-separated list, trimmed and without empty entries."""
    return tuple(item.strip() for item in (raw or "").split(",") if item.strip())


def issuer() -> str:
    """The configured issuer with no trailing slash, so comparisons are exact."""
    return (config.OIDC_ISSUER or "").strip().rstrip("/")


def public_url() -> str:
    """The browser-facing origin the web client is served from.

    Derived from `PUBLIC_URL` rather than added as a knob: the deployment already
    has to set that for CORS, and a second origin variable could disagree with
    it. Read lazily so a test can set it without a restart.
    """
    return os.getenv("PUBLIC_URL", "").strip().rstrip("/")


def redirect_uri() -> str:
    return f"{public_url()}{CALLBACK_PATH}"


def is_enabled() -> bool:
    """SSO is live only when it is switched on AND auth itself is on."""
    return bool(config.OIDC_ENABLED and auth.AUTH_ENABLED)


def allowed_groups() -> frozenset[str]:
    return frozenset(_csv(config.OIDC_ALLOWED_GROUPS))


def allowed_domains() -> frozenset[str]:
    return frozenset(domain.lower() for domain in _csv(config.OIDC_ALLOWED_DOMAINS))


def editor_groups() -> frozenset[str]:
    return frozenset(_csv(config.OIDC_EDITOR_GROUPS))


def validate_oidc_configuration() -> None:
    """Refuse to boot on a partial or fail-open SSO configuration.

    Same idiom as `auth.validate_auth_configuration`: collect every problem and
    raise one `RuntimeError`, so a single startup line shows the whole drift.
    Each check below is a class of mistake that would otherwise surface as a
    login path that breaks at the first request - or, worse, one that fails open.
    """
    if not config.OIDC_ENABLED:
        return

    problems: list[str] = []
    if not auth.AUTH_ENABLED:
        problems.append(
            "OIDC_ENABLED is set while AUTH_ENABLED is false: every route would be "
            "unauthenticated, so SSO would be a login page for a door with no lock"
        )
    missing = [
        name
        for name, value in (
            ("OIDC_ISSUER", config.OIDC_ISSUER),
            ("OIDC_CLIENT_ID", config.OIDC_CLIENT_ID),
            ("OIDC_CLIENT_SECRET", config.OIDC_CLIENT_SECRET),
        )
        if not (value or "").strip()
    ]
    if missing:
        problems.append(f"OIDC_ENABLED requires {', '.join(missing)}")
    if config.OIDC_ISSUER and not issuer().startswith("https://"):
        problems.append(f"OIDC_ISSUER must be an https:// URL; got {config.OIDC_ISSUER!r}")
    if not allowed_groups() and not allowed_domains():
        problems.append(
            "OIDC_ALLOWED_GROUPS and OIDC_ALLOWED_DOMAINS are both empty: an empty "
            "allow-list would admit every account the identity provider will authenticate"
        )
    if _csv(config.OIDC_ADMIN_GROUPS):
        problems.append(
            "OIDC_ADMIN_GROUPS is set: a claim must never grant admin, so remove it and "
            "create the administrator locally instead"
        )
    if default_role() == accounts.ADMIN_ROLE:
        problems.append(
            "OIDC_DEFAULT_ROLE is 'admin': a first sign-in must never earn admin, so "
            "remove it and create the administrator locally instead"
        )
    elif default_role() not in claim_grantable_roles():
        problems.append(
            f"OIDC_DEFAULT_ROLE is {config.OIDC_DEFAULT_ROLE!r}: it must name a role a "
            f"first sign-in may be provisioned with, one of {sorted(claim_grantable_roles())}"
        )
    if not public_url():
        problems.append(
            "OIDC_ENABLED requires PUBLIC_URL: the redirect URI is derived from it "
            f"({CALLBACK_PATH}) and an empty origin produces an invalid redirect"
        )
    if problems:
        raise RuntimeError("; ".join(problems) + ".")


# --- the outbound seam ------------------------------------------------------


def _http_get_json(url: str) -> dict:
    """The single outbound GET seam. Tests monkeypatch this; nothing else dials out.

    Nothing from the response is logged anywhere: an `httpx` exception embeds the
    request URL and the response body, and a discovery or token body is not ours
    to echo into a log line.
    """
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()


def _http_post_form_json(url: str, data: dict) -> dict:
    """The single outbound POST seam (the code exchange). Same logging rule."""
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = client.post(url, data=data, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()


def _cached_document(cache: dict[str, tuple[float, dict]], key: str, fetch: Any) -> dict:
    now = _now()
    with _cache_lock:
        cached = cache.get(key)
        if cached is not None and now < cached[0]:
            return cached[1]
    try:
        document = fetch()
    except (httpx.HTTPError, ValueError) as exc:
        # Deliberately no `exc` detail in the message: it embeds the URL and body.
        raise ProviderError("the identity provider did not answer usably") from exc
    with _cache_lock:
        cache[key] = (now + JWKS_CACHE_SECONDS, document)
    return document


def discovery_document() -> dict:
    """The provider's discovery document, cached for `JWKS_CACHE_SECONDS`."""

    def fetch() -> dict:
        return _http_get_json(f"{issuer()}/.well-known/openid-configuration")

    return _cached_document(_discovery_cache, issuer(), fetch)


def jwks_document() -> dict:
    """The provider's signing keys, cached for `JWKS_CACHE_SECONDS`."""

    def fetch() -> dict:
        document = discovery_document()
        uri = document.get("jwks_uri")
        if not isinstance(uri, str) or not uri:
            raise ProviderError("discovery document has no jwks_uri")
        return _http_get_json(uri)

    return _cached_document(_jwks_cache, issuer(), fetch)


# --- the flow ---------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """A PKCE verifier and its S256 challenge (43..128 verifier characters)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def begin_login() -> tuple[str, str, str]:
    """Mint `state`, `nonce` and a PKCE challenge; returns (state, nonce, challenge)."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    pending_logins.put(state, _PendingLogin(nonce=nonce, code_verifier=verifier), STATE_TTL_SECONDS)
    return state, nonce, challenge


def authorization_url(*, state: str, nonce: str, code_challenge: str) -> str:
    """The IdP's authorize URL for this login, with `code_challenge_method=S256`."""
    endpoint = discovery_document().get("authorization_endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        raise ProviderError("discovery document has no authorization_endpoint")
    params = {
        "response_type": "code",
        "client_id": config.OIDC_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "scope": config.OIDC_SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{endpoint}?{urlencode(params)}"


def consume_state(state: str, cookie_state: Optional[str]) -> tuple[Optional[_PendingLogin], Optional[str]]:
    """Spend the `state` and prove the callback came from the same browser.

    The cookie is checked first, and the state is spent either way: a state that
    arrives from a different browser is burnt rather than left live, so a stolen
    `state` cannot be retried.
    """
    if not state:
        return None, SSO_ERROR_STATE_MISSING
    if not cookie_state or not constant_time_equal(state, cookie_state):
        pending_logins.consume(state)
        return None, SSO_ERROR_COOKIE_MISMATCH
    pending, reason = pending_logins.consume(state)
    if reason == "replayed":
        return None, SSO_ERROR_STATE_REPLAYED
    if reason == "expired":
        return None, SSO_ERROR_STATE_EXPIRED
    if pending is None:
        return None, SSO_ERROR_STATE_UNKNOWN
    return pending, None


def exchange_code(code: str, pending: _PendingLogin) -> dict:
    """Redeem the authorization code server-side, with the client secret.

    The secret and the PKCE verifier never leave this process, and the token
    response is a credential: it is returned to the caller and never logged.
    """
    endpoint = discovery_document().get("token_endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        raise ProviderError("discovery document has no token_endpoint")
    return _http_post_form_json(
        endpoint,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
            "client_id": config.OIDC_CLIENT_ID,
            "client_secret": config.OIDC_CLIENT_SECRET,
            "code_verifier": pending.code_verifier,
        },
    )


def _signing_key(kid: Optional[str], algorithm: str) -> Any:
    """The JWKS key that matches this id_token's `kid` and pinned algorithm."""
    keys = jwks_document().get("keys")
    if not isinstance(keys, list):
        raise ProviderError("the JWKS document has no keys")
    for candidate in keys:
        if not isinstance(candidate, dict):
            continue
        if kid and candidate.get("kid") != kid:
            continue
        declared = candidate.get("alg")
        if declared and declared != algorithm:
            continue
        if candidate.get("use") not in (None, "sig"):
            continue
        try:
            return jwt.PyJWK(candidate, algorithm=algorithm).key
        except PyJWTError as exc:
            raise TokenRejected(SSO_ERROR_TOKEN_INVALID) from exc
    raise TokenRejected(SSO_ERROR_TOKEN_INVALID)


def verify_id_token(id_token: str, *, nonce: str) -> dict:
    """Verify signature, algorithm, issuer, audience, lifetime and the nonce.

    Every failure raises `TokenRejected` carrying a frozen `sso_error`; the
    reason is never provider text, so it is safe to log and to put in a URL.
    """
    try:
        header = jwt.get_unverified_header(id_token)
    except PyJWTError as exc:
        raise TokenRejected(SSO_ERROR_TOKEN_INVALID) from exc
    algorithm = header.get("alg")
    if algorithm not in ALLOWED_ID_TOKEN_ALGS:
        raise TokenRejected(SSO_ERROR_TOKEN_INVALID)
    key = _signing_key(header.get("kid"), algorithm)
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=[algorithm],
            audience=config.OIDC_CLIENT_ID,
            issuer=issuer(),
            options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
        )
    except PyJWTError as exc:
        raise TokenRejected(SSO_ERROR_TOKEN_INVALID) from exc
    if not constant_time_equal(str(claims.get("nonce", "")), nonce):
        raise TokenRejected(SSO_ERROR_NONCE_MISMATCH)
    if not str(claims.get("sub", "")).strip():
        raise TokenRejected(SSO_ERROR_TOKEN_INVALID)
    return claims


def groups_from(claims: dict) -> tuple[str, ...]:
    """The group membership the configured claim carries, however it is shaped."""
    raw = claims.get(config.OIDC_GROUPS_CLAIM)
    if isinstance(raw, str):
        return _csv(raw)
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def email_from(claims: dict) -> Optional[str]:
    value = claims.get("email")
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def evaluate_allow_list(claims: dict) -> Optional[str]:
    """The frozen `sso_error` for a rejected claim, or None when it is allowed.

    The two allow-lists compose with AND. A security control must compose
    restrictively: OR would mean a principal in an allowed group *or* on an
    allowed domain passes, so configuring the second list would widen the door
    instead of narrowing it.
    """
    groups_allowed = allowed_groups()
    if groups_allowed and not (set(groups_from(claims)) & groups_allowed):
        return SSO_ERROR_GROUP_NOT_ALLOWED
    domains_allowed = allowed_domains()
    if domains_allowed:
        email = email_from(claims) or ""
        domain = email.rpartition("@")[2]
        if not domain or domain not in domains_allowed:
            return SSO_ERROR_DOMAIN_NOT_ALLOWED
    return None


def claim_grantable_roles() -> frozenset[str]:
    """Roles a first sign-in may be provisioned with, derived from the role list.

    `admin` is excluded structurally by subtracting `accounts.ADMIN_ROLE`, not by
    a second hard-coded tuple: adding a role to `accounts.ROLES` makes it
    defaultable here and nowhere else, and this is the single place to exclude a
    future role if that policy changes.
    """
    return frozenset(accounts.ROLES) - {accounts.ADMIN_ROLE}


def default_role() -> str:
    """The configured first-login role, resolved to a usable role.

    One resolver, shared by the boot validator and the flow: an empty or blank
    value resolves to `accounts.DEFAULT_ROLE` in both, so a configuration can
    never pass the validator and then provision something else. Reading it
    lazily also lets a test set it without a restart, like `public_url()`.
    """
    return (config.OIDC_DEFAULT_ROLE or "").strip().lower() or accounts.DEFAULT_ROLE


def role_for_claims(claims: dict) -> str:
    """The most a claim can grant is `editor`.

    `admin` has no slot in this mapping, so it is structurally unreachable from a
    claim. A group claim that could mint an administrator would make the identity
    provider's group membership the deployment's root credential.
    """
    if set(groups_from(claims)) & editor_groups():
        return accounts.EDITOR_ROLE
    return default_role()


def preferred_username(claims: dict) -> str:
    """A human-readable name for a new account; never used to match one."""
    for claim in ("preferred_username", "email", "name"):
        value = claims.get(claim)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"sso-{str(claims.get('sub', 'user'))[:32]}"


def park_handoff(claims: dict) -> str:
    """Park a verified identity behind a single-use, short-lived handoff code."""
    code = secrets.token_urlsafe(32)
    handoff_codes.put(
        code,
        _Handoff(
            issuer=issuer(),
            subject=str(claims["sub"]),
            username=preferred_username(claims),
            email=email_from(claims),
            role=role_for_claims(claims),
        ),
        HANDOFF_TTL_SECONDS,
    )
    return code


def consume_handoff(code: str) -> _Handoff:
    """Spend a handoff code exactly once."""
    if not code:
        raise HandoffRejected("missing")
    handoff, reason = handoff_codes.consume(code)
    if handoff is None:
        raise HandoffRejected(reason or "unknown")
    return handoff


def constant_time_equal(left: str, right: str) -> bool:
    """`hmac.compare_digest` for two `str`s, including non-ASCII input.

    `compare_digest` raises `TypeError` when either side has non-ASCII
    characters. The `state` arrives straight from the query string, so a
    `?state=<non-ascii>` would otherwise be an unhandled 500 on a public route:
    the fail is closed, but it breaks the "every rejection maps to a frozen
    `sso_error`" contract and writes no `login.oidc.failed` row. Comparing the
    UTF-8 encoding keeps the constant-time property without the exception.
    """
    return hmac.compare_digest(left.encode("utf-8", "surrogatepass"), right.encode("utf-8", "surrogatepass"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def find_identity(session: Session, *, issuer_value: str, subject: str) -> Optional[OidcIdentity]:
    statement = select(OidcIdentity).where(
        OidcIdentity.issuer == issuer_value,
        OidcIdentity.subject == subject,
    )
    return session.exec(statement).first()


def _free_username(session: Session, preferred: str) -> str:
    """A free username for a new account; a collision never links two accounts.

    Reusing an existing local account because a claim happened to name it is the
    takeover path this module exists to avoid, so the new account gets a suffix
    instead.
    """
    base = (preferred or "sso-user").strip()[:48] or "sso-user"
    candidate = base
    for suffix in range(2, 100):
        if accounts.get_user_by_username(session, candidate) is None:
            return candidate
        candidate = f"{base}-{suffix}"
    return f"{base}-{secrets.token_hex(4)}"


def provision_or_link(session: Session, handoff: _Handoff) -> User:
    """Bind this principal to a local account, provisioning one if needed.

    Identity binds only on the persisted `(issuer, subject)` pair. An existing
    account's stored role is returned unchanged: a claim never rewrites it.
    """
    identity = find_identity(session, issuer_value=handoff.issuer, subject=handoff.subject)
    if identity is not None:
        user = accounts.get_user(session, identity.user_id)
        if user is None:
            raise HandoffRejected("identity points at a missing account")
        if user.disabled:
            raise HandoffRejected("account is disabled")
        return user

    # Provisioning is refused unless an enabled administrator already exists. An
    # SSO-provisioned account empties the break-glass path, so without this guard
    # a deployment could reach zero administrators with no way back in.
    if accounts.count_enabled_admins(session) == 0:
        raise NoAdminBootstrap("no enabled administrator exists")

    # The parked handoff role is re-validated here, never trusted: a handoff
    # carrying a role this deployment may not provision collapses to `viewer`.
    role = handoff.role if handoff.role in claim_grantable_roles() else accounts.DEFAULT_ROLE
    user = accounts.create_sso_user(
        session,
        username=_free_username(session, handoff.username),
        email=handoff.email,
        role=role,
    )
    session.add(
        OidcIdentity(
            id=str(uuid.uuid4()),
            issuer=handoff.issuer,
            subject=handoff.subject,
            user_id=user.id,
            created_at=_now_iso(),
        )
    )
    session.flush()
    return user
