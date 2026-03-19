"""
User account REST API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from ..db import db
from ..models import UserCreate, ThresholdsUpdate
from ..utils.access import ensure_user_access
from ..utils.auth import (
    hash_password,
    require_bootstrap_admin_principal,
    require_current_user,
)


router = APIRouter(prefix="/api/v1", tags=["users"])


@router.post("/users")
async def create_user(
    user: UserCreate,
    request: Request,
    principal: dict = Depends(require_bootstrap_admin_principal),
):
    """Create a new user."""
    user_dict = user.model_dump(exclude_none=True)
    user_dict["password_hash"] = hash_password(user.password)
    user_dict.pop("password", None)
    success = await db.create_user(user_dict)
    
    if not success:
        raise HTTPException(status_code=400, detail="User creation failed (may already exist)")
    await db.insert_audit_log(
        {
            "action": "user.create",
            "actor_id": principal["user_id"],
            "actor_role": principal.get("role"),
            "target_id": user.user_id,
            "request_id": request.state.request_id,
            "details": {
                "auth_type": principal.get("auth_type"),
                "bootstrap_path": principal.get("auth_type") == "api_key",
            },
        }
    )
    
    return {"status": "success", "user_id": user.user_id}


@router.get("/me/devices")
async def get_my_devices(current_user: dict = Depends(require_current_user)):
    """List devices linked to the current authenticated user."""
    items = await db.list_devices_for_user(current_user["user_id"])
    return {
        "user_id": current_user["user_id"],
        "count": len(items),
        "items": items,
    }


@router.get("/users/{user_id}")
async def get_user(user_id: str, current_user: dict = Depends(require_current_user)):
    """Get user profile."""
    user = await ensure_user_access(current_user, user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user


@router.patch("/users/{user_id}/thresholds")
async def update_thresholds(
    user_id: str,
    thresholds: ThresholdsUpdate,
    current_user: dict = Depends(require_current_user),
):
    """Deprecated user-scoped thresholds endpoint."""
    _ = thresholds
    await ensure_user_access(current_user, user_id)
    raise HTTPException(
        status_code=410,
        detail="Threshold settings are device-scoped. Use /api/v1/devices/{device_id}/thresholds.",
    )
