"""
JWT authentication endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from ..db import db
from ..models import LoginRequest
from ..utils.auth import create_access_token, require_current_user, verify_password


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
async def login(payload: LoginRequest):
    """Exchange user credentials for an access token."""
    user = await db.get_user_auth(payload.user_id)
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not verify_password(payload.password, user.get("password_hash")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token, expires_at = create_access_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user_id": user["user_id"],
        "role": user["role"],
        "scopes": [user["role"]],
    }


@router.get("/me")
async def get_me(current_user: dict = Depends(require_current_user)):
    """Return the current authenticated user profile."""
    sanitized = await db.get_user(current_user["user_id"])
    if not sanitized:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return sanitized
