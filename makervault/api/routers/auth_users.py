"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlmodel import Session

import accounts
import audit
import auth
import login_throttle as login_throttle_module
import sessions
from auth import AuthContext
from db import engine
from models import User
from permissions import require_admin, require_read
from schemas import LoginRequest, LoginResponse, MeOut, RefreshRequest, SessionOut, UserCreate, UserOut, UserUpdate

log = logging.getLogger(__name__)
AUTH_NOT_CONFIGURED = "Authentication is not configured on the server"

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    client_host = request.client.host if request.client else "unknown"
    username = login_throttle_module.normalize_username(body.username)
    retry_after = login_throttle_module.limiter.retry_after(username)
    if retry_after:
        log.warning("Login throttled for username %r from %s (retry after %ss)", username, client_host, retry_after)
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    with Session(engine) as s:
        result = auth.login(
            s,
            body.username,
            body.password,
            user_agent=request.headers.get("user-agent"),
            client_ip=client_host,
        )
        if result is not None:
            # The login route has no AuthContext (it creates the principal), so
            # the actor comes from the session row `auth.login` just wrote. No
            # password, token or refresh token ever reaches the row.
            actor = audit.Actor(result.username, result.role, result.kind, result.user_id)
            audit.stage(
                s,
                audit.context_for_actor(request, actor),
                audit.Event(audit.LOGIN_SUCCEEDED, result.username, {"kind": result.kind, "client_ip": client_host}),
            )
        s.commit()
    if result is None:
        lockout_seconds = login_throttle_module.limiter.record_failure(username)
        log.warning("Failed login attempt for username %r from %s", username, client_host)
        if lockout_seconds:
            log.warning("Login throttled for username %r from %s (retry after %ss)", username, client_host, lockout_seconds)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    login_throttle_module.limiter.record_success(username)
    return LoginResponse(
        token=result.token,
        expires_in=result.expires_in,
        refresh_token=result.refresh_token,
    )


def presented_refresh_token(
    body: Optional[RefreshRequest],
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    """The refresh token from the JSON body, or the documented Bearer fallback."""
    if body is not None and body.refresh_token:
        return body.refresh_token
    if credentials is not None:
        return credentials.credentials
    return None


@router.post("/refresh", response_model=LoginResponse)
def refresh_token(
    request: Request,
    body: Optional[RefreshRequest] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth.auth_scheme),
):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    presented = presented_refresh_token(body, credentials)
    if not presented:
        raise HTTPException(status_code=401, detail="Unauthorized")
    token_hash = sessions.hash_refresh_token(presented)
    with Session(engine) as s:
        session_row = sessions.find_by_presented_hash(s, token_hash)
        user = accounts.get_user(s, session_row.user_id) if session_row is not None else None
        if session_row is None or not sessions.is_refreshable(session_row, user):
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
        rotation = sessions.rotate(
            s, session_row, presented_hash=token_hash, access_ttl=auth.AUTH_ACCESS_TOKEN_TTL
        )
        actor = audit.Actor(session_row.username, sessions.role_for(session_row, user), session_row.kind, session_row.user_id)
        if rotation.outcome == sessions.ROTATE_REPLAYED:
            # The revoke and the row it explains must be one fact, so stage the
            # row and COMMIT before raising. `HTTPException` unwinds this `with`
            # block, and raising first would roll the revoke and the audit row
            # back together - a replay would then cost the attacker nothing and
            # leave the victim's session live.
            audit.stage(
                s,
                audit.context_for_actor(request, actor),
                audit.Event(audit.SESSION_REFRESH_REPLAYED, session_row.id, {"client_ip": session_row.client_ip}),
            )
            s.commit()
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
        if rotation.refresh_token is None:
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
        if rotation.outcome == sessions.ROTATE_GRACED:
            audit.stage(
                s,
                audit.context_for_actor(request, actor),
                audit.Event(audit.SESSION_REFRESH_GRACED, session_row.id, {"client_ip": session_row.client_ip}),
            )
        token = auth.create_access_token(session_row, sessions.role_for(session_row, user))
        s.commit()
    return LoginResponse(token=token, expires_in=auth.AUTH_ACCESS_TOKEN_TTL, refresh_token=rotation.refresh_token)


@router.post("/logout", status_code=204)
def logout(
    body: Optional[RefreshRequest] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth.auth_scheme),
):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    presented = presented_refresh_token(body, credentials)
    if presented:
        with Session(engine) as s:
            sessions.revoke_by_refresh_hash(s, sessions.hash_refresh_token(presented))
            s.commit()
    return Response(status_code=204)


@router.get("/me", response_model=MeOut)
def me(context: Optional[AuthContext] = Depends(require_read)):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        user = accounts.get_user(s, context.user_id)
    return MeOut(
        id=context.user_id,
        username=context.username,
        email=user.email if user is not None else None,
        role=context.role,
        disabled=bool(user.disabled) if user is not None else False,
        kind=context.kind,
    )


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        disabled=bool(user.disabled),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def session_out(session_row: sessions.UserSession, *, current: bool) -> SessionOut:
    """One session row as the API reports it; never a refresh hash.

    `SessionOut` has no field for either hash, so there is nothing to remember
    to strip here: the model is the boundary.
    """
    return SessionOut(
        id=session_row.id,
        username=session_row.username,
        kind=session_row.kind,
        device=session_row.device,
        user_agent=session_row.user_agent,
        client_ip=session_row.client_ip,
        created_at=int(session_row.created_at),
        last_used_at=int(session_row.last_used_at),
        current=current,
    )


@router.get("/me/sessions", response_model=List[SessionOut])
def list_my_sessions(context: Optional[AuthContext] = Depends(require_read)):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        rows = sessions.list_for_user(s, user_id=context.user_id, username=context.username)
        return [session_out(row, current=row.id == context.session_id) for row in rows]


@router.delete("/me/sessions/{session_id}", status_code=204)
def revoke_my_session(
    session_id: str,
    request: Request,
    context: Optional[AuthContext] = Depends(require_read),
):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        row = sessions.get(s, session_id)
        # A foreign id is a 404, never a 403: ownership scoping must not become
        # an enumeration oracle that says somebody else's session exists.
        if row is None or row.user_id != context.user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        sessions.revoke(s, row)
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.SESSION_REVOKE, row.id, {"username": row.username, "kind": row.kind}),
        )
        s.commit()
    return Response(status_code=204)


@router.get("/users/{user_id}/sessions", response_model=List[SessionOut])
def list_user_sessions(user_id: str, context: Optional[AuthContext] = Depends(require_admin)):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        user = accounts.get_user(s, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        rows = sessions.list_for_user(s, user_id=user.id, username=user.username)
        return [session_out(row, current=row.id == context.session_id) for row in rows]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_user_session(
    session_id: str,
    request: Request,
    context: Optional[AuthContext] = Depends(require_admin),
):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        row = sessions.get(s, session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        sessions.revoke(s, row)
        # The row carries both the target username and the sid, so the audit
        # entry names the account without a second lookup and without trusting
        # the caller's path parameter.
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.SESSION_ADMIN_REVOKE, row.id, {"username": row.username, "kind": row.kind}),
        )
        s.commit()
    return Response(status_code=204)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, context: Optional[AuthContext] = Depends(require_admin)):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        try:
            user = accounts.create_user(s, body.username, body.password, body.email, body.role)
        except accounts.AccountError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.USER_CREATE, user.username, {"role": user.role, "user_id": user.id}),
        )
        # The first account replaces the env break-glass admin, so its sessions
        # die with it. Same transaction as the insert: either both or neither.
        sessions.revoke_break_glass(s)
        result = user_out(user)
        s.commit()
    return result


@router.get("/users", response_model=List[UserOut])
def list_users(_: Optional[AuthContext] = Depends(require_admin)):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        users = accounts.list_users(s)
    return [user_out(user) for user in users]


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, request: Request, context: Optional[AuthContext] = Depends(require_admin)):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        # Snapshot before the update: both reads share the session's identity map,
        # so the row object is mutated in place and the old values must be kept.
        before = accounts.get_user(s, user_id)
        previous_role = before.role if before is not None else None
        previous_disabled = bool(before.disabled) if before is not None else False
        try:
            user = accounts.update_user(s, user_id, disabled=body.disabled, role=body.role)
        except accounts.AccountError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
        events = []
        if previous_role is not None and user.role != previous_role:
            events.append(audit.Event(audit.USER_ROLE_CHANGE, user.username, {"from": previous_role, "to": user.role}))
        if bool(user.disabled) != previous_disabled:
            action = audit.USER_DISABLE if user.disabled else audit.USER_ENABLE
            events.append(
                audit.Event(action, user.username, {"from": previous_disabled, "to": bool(user.disabled)})
            )
        audit.stage(s, audit.context_for(request, context), *events)
        result = user_out(user)
        s.commit()
    return result
