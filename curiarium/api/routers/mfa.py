"""Two-factor self-service and the MFA challenge endpoint (Mf-lg02).

Every route here acts on the caller's own account, except `POST /settings/mfa`
which moves the admin-wide policy. They all 503 when auth is disabled, exactly
like `/login`: an MFA endpoint that kept answering on an auth-disabled deployment
would be a second, unaudited door.

`POST /mfa/verify` is the one public route: it runs *before* a session exists,
trading the short-lived challenge `/login` minted for the real token pair. The
challenge's `sub` is the throttle key, so TOTP guesses are rate-limited per
account by the second limiter (`login_throttle.mfa_limiter`) without touching the
password bucket.

The audit contract for this router is deliberate:

* a completed second factor is one `mfa.verify.succeeded` row (or
  `mfa.recovery_code.used`), written in the new session's transaction, so the
  login and its record commit together;
* a failed one is a `mfa.verify.failed` row staged and *committed* before the
  401, mirroring the `/refresh` replay precedent - raising first would roll the
  row back with the failed attempt and leave no trace;
* no secret, code or hash ever reaches a `detail`.
"""

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from jwt import PyJWTError
from sqlmodel import Session

import accounts
import audit
import auth
import login_throttle as login_throttle_module
import mfa
import sessions
import settings_service
from auth import AuthContext
from db import engine
from models import User
from permissions import require_admin, require_read
from schemas import (
    LoginResponse,
    MfaConfirmOut,
    MfaConfirmRequest,
    MfaEnrolOut,
    MfaEnrolRequest,
    MfaPasswordRequest,
    MfaPolicyOut,
    MfaPolicyUpdate,
    MfaRecoveryCodesOut,
    MfaStatusOut,
    MfaStepUpOut,
    MfaStepUpRequest,
    MfaVerifyRequest,
)

AUTH_NOT_CONFIGURED = "Authentication is not configured on the server"
SSO_DETAIL = "This account signs in with SSO; two-factor is managed by the identity provider"
PASSWORD_DETAIL = "Password confirmation failed"
ALREADY_ENROLLED = "Two-factor authentication is already enabled"
NOT_ENROLLED = "Two-factor authentication is not enabled for this account"
INVALID_CODE = "Invalid or expired code"
INVALID_CHALLENGE = "Invalid or expired challenge"
POLICY_NEEDS_MFA = "Enrol two-factor authentication and step up before turning this policy on"
ADMIN_DISABLE_REFUSED = "An administrator with the MFA policy on cannot disable two-factor authentication"
TOO_MANY_ATTEMPTS = "Too many failed login attempts. Try again later."

router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _confirmed_user(session: Session, context: AuthContext, password: str) -> User:
    """The caller's account, after their password is re-checked (the sudo gate).

    A NULL hash means an SSO account: its credential lives at the IdP, so there
    is no local password to confirm and the route refuses instead of guessing.
    This is why enrolment and disable each carry a password body at all - a
    hijacked session must not be able to swap or drop the second factor.
    """
    user = accounts.get_user(session, context.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.password_hash is None:
        raise HTTPException(status_code=409, detail=SSO_DETAIL)
    if not accounts.verify_password(user.password_hash, password):
        raise HTTPException(status_code=403, detail=PASSWORD_DETAIL)
    return user


def _present_second_factor(session: Session, user: User, code: str) -> str:
    """Try TOTP, then a recovery code; returns the method that succeeded.

    Both paths are guarded UPDATEs, so a code that matched but was already spent
    changes nothing and the other attempt still runs against empty rows.
    `"unknown"` means neither matched and the caller records a failure.

    A `NULL` seed is a real state, not an error: the factor may have been
    disabled between the challenge being minted and this request. It means there
    is no TOTP path, so only a recovery code can still win - and `decrypt_seed`
    takes a stored blob, so it must not be handed `None`.
    """
    secret = mfa.decrypt_seed(user.totp_secret) if user.totp_secret else None
    if secret is not None:
        matched = mfa.matching_step(secret, code)
        # `matching_step` returns the code's own counter C, never an offset, so
        # the same code can only ever match at wall steps C-1, C and C+1 - and
        # each time it returns C. Burning that value means the monotone guard
        # refuses the second presentation in every bucket, while a different,
        # on-time code stays usable.
        if matched is not None and mfa.consume_totp_step(session, user.id, matched):
            return "totp"
    if mfa.consume_recovery_code(session, user.id, code):
        return "recovery_code"
    return "unknown"


def _challenge_actor(challenge: dict, user: Optional[User]) -> audit.Actor:
    """Who this verify attempt belongs to, from the row or the challenge claims.

    A deleted or disabled account still leaves an attempt worth recording; the
    challenge's `username` is the only identity left, so it names the actor.
    """
    if user is not None:
        return audit.Actor(user.username, user.role, sessions.PASSWORD_KIND, user.id)
    return audit.Actor(
        str(challenge.get("username") or ""),
        accounts.DEFAULT_ROLE,
        sessions.PASSWORD_KIND,
        str(challenge.get("sub") or ""),
    )


@router.get("/mfa", response_model=MfaStatusOut)
def get_mfa_status(response: Response, context: Optional[AuthContext] = Depends(require_read)):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        user = accounts.get_user(s, context.user_id)
        enrolled = mfa.user_is_enrolled(user)
        remaining = mfa.remaining_recovery_codes(s, user.id) if user is not None else 0
        enrolled_at = user.totp_enrolled_at if enrolled else None
        # An SSO-only account cannot enrol: it has no local password to confirm.
        can_enrol = bool(user is not None and user.password_hash is not None and not enrolled)
    response.headers["Cache-Control"] = "no-store"
    return MfaStatusOut(
        enrolled=enrolled,
        enrolled_at=enrolled_at,
        recovery_codes_remaining=remaining,
        require_admin=settings_service.get_mfa_require_admin(),
        can_enrol=can_enrol,
    )


@router.post("/mfa/enrol", response_model=MfaEnrolOut)
def start_enrolment(
    body: MfaEnrolRequest,
    request: Request,
    response: Response,
    context: Optional[AuthContext] = Depends(require_read),
):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        user = _confirmed_user(s, context, body.password)
        if mfa.user_is_enrolled(user):
            raise HTTPException(status_code=409, detail=ALREADY_ENROLLED)
        # Persist nothing: the seed only becomes real when `/mfa/confirm` has
        # proved the caller can produce a code from it.
        secret = mfa.new_secret()
        username = user.username
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.MFA_ENROL_START, user.username, {"stage": "start"}),
        )
        s.commit()
    response.headers["Cache-Control"] = "no-store"
    return MfaEnrolOut(
        secret=mfa.base32_secret(secret),
        otpauth_uri=mfa.otpauth_uri(secret=secret, username=username),
        digits=mfa.TOTP_DIGITS,
        period=mfa.TOTP_PERIOD,
        algorithm=mfa.TOTP_ALGORITHM,
    )


@router.post("/mfa/confirm", response_model=MfaConfirmOut)
def confirm_enrolment(
    body: MfaConfirmRequest,
    request: Request,
    response: Response,
    context: Optional[AuthContext] = Depends(require_read),
):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        user = _confirmed_user(s, context, body.password)
        if mfa.user_is_enrolled(user):
            raise HTTPException(status_code=409, detail=ALREADY_ENROLLED)
        secret = mfa.parse_secret(body.secret)
        # 400, not 401: this is a bad enrolment request, not a rejected
        # credential. The matrix sweep runs as the fixture admin, who must never
        # be enrolled and so must never trip the 401 path here.
        if secret is None:
            raise HTTPException(status_code=400, detail="Invalid verification code")
        matched = mfa.matching_step(secret, body.code)
        if matched is None or not mfa.consume_totp_step(s, user.id, matched):
            raise HTTPException(status_code=400, detail="Invalid verification code")
        user.totp_secret = mfa.encrypt_seed(secret)
        user.totp_enrolled_at = mfa.now_iso()
        s.add(user)
        codes = mfa.create_recovery_codes(s, user.id)
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.MFA_ENROL, user.username, {"recovery_codes": len(codes)}),
        )
        s.commit()
    response.headers["Cache-Control"] = "no-store"
    return MfaConfirmOut(recovery_codes=codes)


@router.post("/mfa/verify", response_model=LoginResponse)
def verify_mfa(body: MfaVerifyRequest, request: Request, response: Response):
    # A mode flip to `oidc` after the challenge was minted must not let the
    # challenge be spent: the challenge proves a password login that mode refuses.
    if not auth.AUTH_ENABLED or not auth.password_login_allowed():
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    client_host = _client_ip(request)
    # An unparseable token is a 400 (a bad request), not a 401: a *valid*
    # challenge with a *wrong code* is the 401 below.
    try:
        challenge = auth.decode_mfa_challenge(body.mfa_token)
    except PyJWTError:
        raise HTTPException(status_code=400, detail=INVALID_CHALLENGE) from None
    user_id = str(challenge["sub"])
    retry_after = login_throttle_module.mfa_limiter.retry_after(user_id)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail=TOO_MANY_ATTEMPTS,
            headers={"Retry-After": str(retry_after)},
        )
    with Session(engine) as s:
        user = accounts.get_user(s, user_id)
        method = "unknown"
        reason: Optional[str] = None
        if user is None:
            reason = "unknown_user"
        elif user.disabled:
            reason = "disabled"
        else:
            method = _present_second_factor(s, user, body.code)
            if method == "unknown":
                reason = "invalid_code"
        if reason is not None:
            login_throttle_module.mfa_limiter.record_failure(user_id)
            audit.stage(
                s,
                audit.context_for_actor(request, _challenge_actor(challenge, user)),
                audit.Event(
                    audit.MFA_VERIFY_FAILED,
                    user_id,
                    {"method": method, "reason": reason, "client_ip": client_host},
                ),
            )
            # The row must outlive the 401. `HTTPException` unwinds this `with`
            # block, so stage and COMMIT first, exactly like `/refresh` replay.
            s.commit()
            raise HTTPException(status_code=401, detail=INVALID_CODE)
        session_row, refresh_token = sessions.create(
            s,
            username=user.username,
            user_id=user.id,
            kind=sessions.PASSWORD_KIND,
            access_ttl=auth.AUTH_ACCESS_TOKEN_TTL,
            refresh_ttl=auth.AUTH_REFRESH_TTL_SECONDS,
            user_agent=request.headers.get("user-agent"),
            client_ip=client_host,
            mfa_verified_at=int(time.time()),
        )
        role = sessions.role_for(session_row, user)
        token = auth.create_access_token(session_row, role)
        action = (
            audit.MFA_RECOVERY_CODE_USED if method == "recovery_code" else audit.MFA_VERIFY_SUCCEEDED
        )
        audit.stage(
            s,
            audit.context_for_actor(
                request, audit.Actor(user.username, role, sessions.PASSWORD_KIND, user.id)
            ),
            audit.Event(action, user_id, {"kind": sessions.PASSWORD_KIND, "method": method, "client_ip": client_host}),
        )
        s.commit()
    login_throttle_module.mfa_limiter.record_success(user_id)
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(token=token, expires_in=auth.AUTH_ACCESS_TOKEN_TTL, refresh_token=refresh_token)


@router.post("/mfa/step-up", response_model=MfaStepUpOut)
def step_up(
    body: MfaStepUpRequest,
    request: Request,
    context: Optional[AuthContext] = Depends(require_read),
):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    # A wrong guess costs the same here as at `/mfa/verify`, so both routes
    # share one bucket: an attacker cannot split their budget across the two.
    retry_after = login_throttle_module.mfa_limiter.retry_after(context.user_id)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail=TOO_MANY_ATTEMPTS,
            headers={"Retry-After": str(retry_after)},
        )
    with Session(engine) as s:
        user = accounts.get_user(s, context.user_id)
        if not mfa.user_is_enrolled(user):
            raise HTTPException(status_code=409, detail=NOT_ENROLLED)
        secret = mfa.decrypt_seed(user.totp_secret)
        matched = mfa.matching_step(secret, body.code) if secret is not None else None
        if matched is None:
            # Both a wrong code and a lost consume race are a failed guess.
            login_throttle_module.mfa_limiter.record_failure(context.user_id)
            # A failed step-up writes nothing: `mfa.verify.failed` belongs to
            # `/mfa/verify`, and this session already exists.
            raise HTTPException(status_code=401, detail=INVALID_CODE)
        if not mfa.consume_totp_step(s, user.id, matched):
            login_throttle_module.mfa_limiter.record_failure(context.user_id)
            raise HTTPException(status_code=401, detail=INVALID_CODE)
        session_row = sessions.get(s, context.session_id)
        if session_row is not None:
            session_row.mfa_verified_at = int(time.time())
            s.add(session_row)
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.MFA_STEP_UP, context.session_id, {"username": context.username}),
        )
        s.commit()
    login_throttle_module.mfa_limiter.record_success(context.user_id)
    return MfaStepUpOut(mfa_verified=True)


@router.delete("/mfa", status_code=204)
def disable_mfa(
    body: MfaPasswordRequest,
    request: Request,
    context: Optional[AuthContext] = Depends(require_read),
):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        user = _confirmed_user(s, context, body.password)
        if not mfa.user_is_enrolled(user):
            raise HTTPException(status_code=409, detail=NOT_ENROLLED)
        # The code guard that makes "no lockout reachable" true: while the policy
        # is on, an admin cannot disable the factor their own admin access now
        # depends on.
        if context.role == accounts.ADMIN_ROLE and settings_service.get_mfa_require_admin():
            raise HTTPException(status_code=409, detail=ADMIN_DISABLE_REFUSED)
        user.totp_secret = None
        user.totp_enrolled_at = None
        user.totp_last_step = None
        s.add(user)
        deleted = mfa.delete_recovery_codes(s, user.id)
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.MFA_DISABLE, user.username, {"recovery_codes_deleted": deleted}),
        )
        s.commit()
    return Response(status_code=204)


@router.post("/mfa/recovery-codes", response_model=MfaRecoveryCodesOut)
def regenerate_recovery_codes(
    body: MfaPasswordRequest,
    request: Request,
    response: Response,
    context: Optional[AuthContext] = Depends(require_read),
):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        user = _confirmed_user(s, context, body.password)
        if not mfa.user_is_enrolled(user):
            raise HTTPException(status_code=409, detail=NOT_ENROLLED)
        mfa.delete_recovery_codes(s, user.id)
        codes = mfa.create_recovery_codes(s, user.id)
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.MFA_RECOVERY_CODES_REGENERATE, user.username, {"count": len(codes)}),
        )
        s.commit()
    response.headers["Cache-Control"] = "no-store"
    return MfaRecoveryCodesOut(recovery_codes=codes)


@router.post("/settings/mfa", response_model=MfaPolicyOut)
def update_mfa_policy(
    body: MfaPolicyUpdate,
    request: Request,
    context: Optional[AuthContext] = Depends(require_admin),
):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        user = accounts.get_user(s, context.user_id)
        session_row = sessions.get(s, context.session_id)
        # Enabling the policy while the caller cannot satisfy it would lock every
        # admin out, so the two preconditions are checked here, not in prose.
        if body.require_admin and not (mfa.mfa_ok(session_row) and mfa.user_is_enrolled(user)):
            raise HTTPException(status_code=409, detail=POLICY_NEEDS_MFA)
        previous = settings_service.get_mfa_require_admin()
        settings_service.set_mfa_require_admin(body.require_admin, session=s)
        # Unconditionally, even when the value is unchanged: this is an explicit
        # policy assertion and the audit sweep needs a row for it (like /login).
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(
                audit.SETTINGS_MFA_REQUIRE_ADMIN_UPDATE,
                "mfa_require_admin",
                {"from": previous, "to": body.require_admin},
            ),
        )
        s.commit()
    return MfaPolicyOut(require_admin=body.require_admin)
