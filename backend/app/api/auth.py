"""
JWT authentication endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..db import db
from ..models import LoginRequest, RefreshRequest
from ..observability import AUTH_LOGIN_TOTAL, AUTH_REVOKED_SESSIONS_TOTAL
from ..utils.auth import (
    issue_session_tokens,
    require_current_user,
    rotate_refresh_session,
    verify_password,
)


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
async def login(payload: LoginRequest, request: Request):
    """Exchange user credentials for access + refresh tokens."""
    user = await db.get_user_auth(payload.user_id)
    if not user or not user.get("is_active", True):
        AUTH_LOGIN_TOTAL.labels(outcome="invalid_credentials").inc()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not verify_password(payload.password, user.get("password_hash")):
        AUTH_LOGIN_TOTAL.labels(outcome="invalid_credentials").inc()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    tokens = await issue_session_tokens(user)
    AUTH_LOGIN_TOTAL.labels(outcome="success").inc()
    await db.insert_audit_log(
        {
            "action": "auth.login",
            "actor_id": user["user_id"],
            "actor_role": user["role"],
            "target_id": tokens["session_id"],
            "request_id": request.state.request_id,
        }
    )
    return tokens


@router.post("/refresh")
async def refresh_tokens(payload: RefreshRequest, request: Request):
    """Rotate a refresh token and issue a new token pair."""
    tokens = await rotate_refresh_session(payload.refresh_token)
    await db.insert_audit_log(
        {
            "action": "auth.refresh",
            "actor_id": tokens["user_id"],
            "actor_role": tokens["role"],
            "target_id": tokens["session_id"],
            "request_id": request.state.request_id,
        }
    )
    return tokens


@router.post("/logout")
async def logout(request: Request, current_user: dict = Depends(require_current_user)):
    """Revoke the current session so access and refresh tokens stop working."""
    session_id = current_user.get("session_id")
    if not session_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing active session")

    success = await db.revoke_auth_session(
        session_id=session_id,
        reason="User logout",
        revoked_by=current_user["user_id"],
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    AUTH_REVOKED_SESSIONS_TOTAL.labels(reason="logout").inc()
    await db.insert_audit_log(
        {
            "action": "auth.logout",
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
            "target_id": session_id,
            "request_id": request.state.request_id,
        }
    )
    return {"status": "success", "session_id": session_id}


@router.get("/me")
async def get_me(current_user: dict = Depends(require_current_user)):
    """Return the current authenticated user profile."""
    sanitized = await db.get_user(current_user["user_id"])
    if not sanitized:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return sanitized
