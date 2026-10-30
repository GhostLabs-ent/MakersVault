"""The four browser-facing OIDC routes (Mf-4c24).

A separate router from `routers/auth_users.py` because the shape is different:
these routes run before a session exists, take no `Authorization` header, and the
only mutation is the final exchange. All four 503 when auth is disabled, exactly
like `POST /login` - an SSO endpoint that kept answering on an auth-disabled
deployment would be a second, unaudited door.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

import accounts
import audit
import auth
import oidc
import sessions
from db import engine
from schemas import LoginResponse, OidcExchangeRequest, OidcStatusOut

log = logging.getLogger(__name__)
AUTH_NOT_CONFIGURED = "Authentication is not configured on the server"
OIDC_NOT_CONFIGURED = "SSO is not configured on the server"

router = APIRouter()


def _require_oidc() -> None:
    """503 unless both auth and SSO are on, checked before anything is spent."""
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    if not oidc.is_enabled():
        raise HTTPException(status_code=503, detail=OIDC_NOT_CONFIGURED)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _fragment_redirect(key: str, value: str) -> RedirectResponse:
    """Send the browser back with one frozen value in the URL fragment.

    A fragment never reaches a server, a proxy access log or a Referer header, so
    neither the handoff code nor a rejection reason can leak through one. The
    only values this ever carries are a handoff code we minted and a member of
    `oidc.SSO_ERRORS`; provider free text is never forwarded.
    """
    return RedirectResponse(f"{oidc.public_url()}/#{key}={value}", status_code=302)


def _reject(request: Request, sso_error: str, client_ip: str) -> RedirectResponse:
    """Record a rejected attempt, then bounce the browser back with its code.

    `audit.record` owns its own transaction: this route mutates no user, session
    or identity row, so there is nothing to join. The detail carries the frozen
    enum and the issuer and nothing else - never the code, the state, the
    id_token or any provider text.
    """
    assert sso_error in oidc.SSO_ERRORS, f"undeclared sso_error {sso_error!r}"
    log.warning("OIDC sign-in rejected from %s: %s", client_ip, sso_error)
    actor = audit.Actor(oidc.issuer(), accounts.DEFAULT_ROLE, sessions.OIDC_KIND, None)
    try:
        audit.record(
            audit.Event(
                audit.LOGIN_OIDC_FAILED,
                oidc.issuer(),
                {
                    "kind": sessions.OIDC_KIND,
                    "client_ip": client_ip,
                    "issuer": oidc.issuer(),
                    "sso_error": sso_error,
                },
            ),
            ctx=audit.context_for_actor(request, actor),
        )
    except Exception:
        # `record` already logged the failure. A rejected login has nothing to
        # roll back, so the browser still gets its answer.
        log.warning("OIDC rejection audit write failed from %s", client_ip)
    return _fragment_redirect("sso_error", sso_error)


@router.get("/auth/oidc/status", response_model=OidcStatusOut)
def oidc_status():
    """Tell the web client whether to offer the SSO button; no other detail."""
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    return OidcStatusOut(enabled=oidc.is_enabled())


@router.get("/auth/oidc/start")
def oidc_start(request: Request):
    """Begin the flow: mint state/nonce/PKCE and redirect to the provider."""
    _require_oidc()
    client_ip = _client_ip(request)
    retry_after = oidc.start_limiter.retry_after(client_ip)
    if retry_after:
        log.warning("OIDC start throttled for %s (retry after %ss)", client_ip, retry_after)
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    try:
        state, nonce, challenge = oidc.begin_login()
        location = oidc.authorization_url(state=state, nonce=nonce, code_challenge=challenge)
    except (oidc.ProviderError, oidc.StoreFull):
        # Nothing from the provider response is logged: an httpx exception
        # embeds the request URL and body.
        log.warning("OIDC start failed for %s: the provider could not be reached", client_ip)
        raise HTTPException(status_code=502, detail="The identity provider is unavailable") from None
    oidc.start_limiter.record(client_ip)
    response = RedirectResponse(location, status_code=302)
    # A binding value, not a credential: HttpOnly so script cannot read it,
    # Secure so it never crosses plaintext, Lax so the provider's top-level
    # redirect back still carries it, and Path-scoped to this flow alone.
    response.set_cookie(
        oidc.STATE_COOKIE_NAME,
        state,
        max_age=oidc.STATE_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path=oidc.STATE_COOKIE_PATH,
    )
    return response


@router.get("/auth/oidc/callback")
def oidc_callback(
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
):
    """Verify the provider's answer and park a single-use handoff code.

    This route writes no user, session or identity row. A rejected attempt is the
    only thing it records, through `audit.record`.
    """
    _require_oidc()
    client_ip = _client_ip(request)
    if error:
        # The provider declined (typically the user cancelled). `error` is
        # provider-controlled text and is deliberately neither logged nor
        # forwarded.
        return _reject(request, oidc.SSO_ERROR_PROVIDER_REJECTED, client_ip)
    pending, sso_error = oidc.consume_state(state, request.cookies.get(oidc.STATE_COOKIE_NAME))
    if sso_error:
        return _reject(request, sso_error, client_ip)
    if not code:
        return _reject(request, oidc.SSO_ERROR_TOKEN_INVALID, client_ip)
    try:
        token_response = oidc.exchange_code(code, pending)
        id_token = token_response.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise oidc.TokenRejected(oidc.SSO_ERROR_TOKEN_INVALID)
        claims = oidc.verify_id_token(id_token, nonce=pending.nonce)
    except oidc.ProviderError:
        return _reject(request, oidc.SSO_ERROR_PROVIDER_UNAVAILABLE, client_ip)
    except oidc.TokenRejected as rejected:
        return _reject(request, rejected.sso_error, client_ip)
    sso_error = oidc.evaluate_allow_list(claims)
    if sso_error:
        return _reject(request, sso_error, client_ip)
    try:
        handoff = oidc.park_handoff(claims)
    except oidc.StoreFull:
        return _reject(request, oidc.SSO_ERROR_EXCHANGE_FAILED, client_ip)
    response = _fragment_redirect("sso_code", handoff)
    response.delete_cookie(oidc.STATE_COOKIE_NAME, path=oidc.STATE_COOKIE_PATH)
    return response


@router.post("/auth/oidc/exchange", response_model=LoginResponse)
def oidc_exchange(body: OidcExchangeRequest, request: Request):
    """The one mutation: provision/link, open a session, stage the audit event."""
    _require_oidc()
    client_ip = _client_ip(request)
    try:
        handoff = oidc.consume_handoff(body.code)
    except oidc.HandoffRejected:
        log.warning("OIDC exchange rejected for %s: the handoff code is not valid", client_ip)
        raise HTTPException(status_code=401, detail="Invalid or expired sign-in") from None
    with Session(engine) as s:
        try:
            user = oidc.provision_or_link(s, handoff)
        except oidc.NoAdminBootstrap:
            s.rollback()
            log.warning("OIDC provisioning refused for %s: no enabled administrator exists", client_ip)
            raise HTTPException(
                status_code=409,
                detail="An administrator must sign in locally before SSO can create accounts",
            ) from None
        except oidc.HandoffRejected:
            s.rollback()
            raise HTTPException(status_code=401, detail="Invalid or expired sign-in") from None
        except accounts.AccountError:
            s.rollback()
            log.warning("OIDC provisioning failed for %s: the account could not be created", client_ip)
            raise HTTPException(status_code=409, detail="The account could not be created") from None
        session_row, refresh_token = sessions.create(
            s,
            username=user.username,
            user_id=user.id,
            kind=sessions.OIDC_KIND,
            access_ttl=auth.AUTH_ACCESS_TOKEN_TTL,
            refresh_ttl=auth.AUTH_REFRESH_TTL_SECONDS,
            user_agent=request.headers.get("user-agent"),
            client_ip=client_ip,
        )
        role = sessions.role_for(session_row, user)
        token = auth.create_access_token(session_row, role)
        # Same actor-from-the-session-row shape as POST /login: no token, no
        # secret and no provider text ever reaches the row.
        actor = audit.Actor(user.username, role, sessions.OIDC_KIND, user.id)
        audit.stage(
            s,
            audit.context_for_actor(request, actor),
            audit.Event(
                audit.LOGIN_OIDC_SUCCEEDED,
                user.username,
                {"kind": sessions.OIDC_KIND, "client_ip": client_ip, "issuer": handoff.issuer},
            ),
        )
        s.commit()
    return LoginResponse(
        token=token,
        expires_in=auth.AUTH_ACCESS_TOKEN_TTL,
        refresh_token=refresh_token,
    )
