"""
JWT authentication endpoints.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..db import db
from ..models import PhoneLoginRequest, RefreshRequest, RegisterRequest
from ..observability import AUTH_LOGIN_TOTAL, AUTH_REVOKED_SESSIONS_TOTAL
from ..utils.auth import (
    hash_password,
    issue_session_tokens,
    require_current_user,
    rotate_refresh_session,
    verify_password,
)
from ..utils.phone import normalize_phone_number


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register")
async def register(payload: RegisterRequest, request: Request):
    """Register a new user account using a phone number and password."""
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name must be at least 2 characters",
        )
    if payload.date_of_birth > date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Date of birth cannot be in the future",
        )

    try:
        normalized_phone = normalize_phone_number(payload.phone_number)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if await db.phone_exists(normalized_phone):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number already registered")

    user_id = await db.generate_user_id()
    created = await db.create_user_with_phone(
        {
            "user_id": user_id,
            "name": name,
            "phone_number": normalized_phone,
            "date_of_birth": payload.date_of_birth.isoformat(),
            "password_hash": hash_password(payload.password),
            "role": "user",
            "is_active": True,
        }
    )
    if not created:
        if await db.phone_exists(normalized_phone):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number already registered")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User registration failed")

    await db.insert_audit_log(
        {
            "action": "auth.register",
            "actor_id": user_id,
            "actor_role": "user",
            "target_id": user_id,
            "request_id": request.state.request_id,
        }
    )
    return {"status": "success", "user_id": user_id}


@router.post("/login")
async def login(payload: PhoneLoginRequest, request: Request):
    """Exchange user credentials for access + refresh tokens."""
    try:
        normalized_phone = normalize_phone_number(payload.phone_number)
    except ValueError as exc:
        AUTH_LOGIN_TOTAL.labels(outcome="invalid_request").inc()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    user = await db.get_user_auth_by_phone(normalized_phone)
    password = payload.password

    if not user or not user.get("is_active", True):
        AUTH_LOGIN_TOTAL.labels(outcome="invalid_credentials").inc()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not verify_password(password, user.get("password_hash")):
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
    user = await db.get_user_auth(tokens["user_id"])
    await db.insert_audit_log(
        {
            "action": "auth.refresh",
            "actor_id": tokens["user_id"],
            "actor_role": user.get("role", "user") if user else "user",
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
