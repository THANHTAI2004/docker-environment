"""
JWT authentication endpoints.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..db import db
from ..models import (
    ChangePasswordRequest,
    PhoneLoginRequest,
    RefreshRequest,
    RegisterRequest,
    UpdateProfileRequest,
)
from ..observability import AUTH_CHANGE_PASSWORD_TOTAL, AUTH_LOGIN_TOTAL, AUTH_REVOKED_SESSIONS_TOTAL
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
            "actor_role": None,
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
            "actor_role": user.get("role"),
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
            "actor_role": user.get("role") if user else None,
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
            "actor_role": current_user.get("role"),
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


@router.patch("/me")
async def update_me(
    payload: UpdateProfileRequest,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Update the current authenticated user profile fields."""
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name must be at least 2 characters after trimming",
        )
    if payload.date_of_birth > date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Date of birth cannot be in the future",
        )

    user_id = current_user["user_id"]
    existing_user = await db.get_user_auth(user_id)
    if not existing_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        updated_user = await db.update_user_profile(
            user_id,
            {
                "name": name,
                "date_of_birth": payload.date_of_birth.isoformat(),
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user profile",
        ) from exc

    if not updated_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await db.insert_audit_log(
        {
            "action": "auth.profile_update",
            "actor_id": user_id,
            "actor_role": current_user.get("role"),
            "target_id": user_id,
            "request_id": request.state.request_id,
        }
    )
    return updated_user


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Change the current authenticated user's password."""
    user_id = current_user["user_id"]

    async def _audit_failure(reason: str) -> None:
        await db.insert_audit_log(
            {
                "action": "auth.change_password_failed",
                "actor_id": user_id,
                "actor_role": current_user.get("role"),
                "target_id": user_id,
                "request_id": request.state.request_id,
                "reason": reason,
            }
        )

    if not payload.current_password.strip():
        AUTH_CHANGE_PASSWORD_TOTAL.labels(outcome="invalid_request").inc()
        await _audit_failure("empty_current_password")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Current password is required",
        )
    if payload.new_password == payload.current_password:
        AUTH_CHANGE_PASSWORD_TOTAL.labels(outcome="same_password").inc()
        await _audit_failure("same_password")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )

    user_auth = await db.get_user_auth(user_id)
    if not user_auth:
        AUTH_CHANGE_PASSWORD_TOTAL.labels(outcome="user_not_found").inc()
        await _audit_failure("user_not_found")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not verify_password(payload.current_password, user_auth.get("password_hash")):
        AUTH_CHANGE_PASSWORD_TOTAL.labels(outcome="invalid_current_password").inc()
        await _audit_failure("invalid_current_password")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    new_password_hash = hash_password(payload.new_password)
    try:
        updated = await db.update_user_password_hash(user_id, new_password_hash)
    except Exception as exc:
        AUTH_CHANGE_PASSWORD_TOTAL.labels(outcome="error").inc()
        await _audit_failure("update_error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update password",
        ) from exc

    if not updated:
        AUTH_CHANGE_PASSWORD_TOTAL.labels(outcome="user_not_found").inc()
        await _audit_failure("user_not_found_after_update")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    current_session_id = current_user.get("session_id")
    revoked_other_sessions = 0
    if current_session_id:
        revoked_other_sessions = await db.revoke_user_other_auth_sessions(
            user_id=user_id,
            keep_session_id=current_session_id,
            reason="Password changed",
            revoked_by=user_id,
        )

    AUTH_CHANGE_PASSWORD_TOTAL.labels(outcome="success").inc()

    await db.insert_audit_log(
        {
            "action": "auth.change_password",
            "actor_id": user_id,
            "actor_role": current_user.get("role"),
            "target_id": user_id,
            "request_id": request.state.request_id,
            "details": {
                "revoked_other_sessions": revoked_other_sessions,
            },
        }
    )
    return {"status": "success"}
