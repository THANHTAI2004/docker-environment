"""
User account REST API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from ..db import db
from ..models import UserCreate, ThresholdsUpdate
from ..utils.access import ensure_user_access
from ..utils.auth import (
    hash_password,
    require_admin_user,
    require_bootstrap_admin_principal,
    require_current_user,
)


router = APIRouter(prefix="/api/v1", tags=["users"])


@router.get("/admin/users")
async def list_admin_users(
    limit: int = Query(default=500, le=1000),
    user_id: str | None = Query(default=None),
    phone_number: str | None = Query(default=None),
    _: dict = Depends(require_admin_user),
):
    """List all users for admin management."""
    items = await db.list_admin_users(
        limit=limit,
        user_id=user_id.strip() if user_id else None,
        phone_number=phone_number.strip() if phone_number else None,
    )
    return {"count": len(items), "items": items}


@router.delete("/admin/users/{user_id}")
async def delete_admin_user(
    user_id: str,
    request: Request,
    principal: dict = Depends(require_admin_user),
):
    """Delete one user and related access/session records."""
    if user_id == principal["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot delete the current admin user")
    target = await db.get_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    result = await db.delete_admin_user(user_id)
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail="User not found")
    await db.insert_audit_log(
        {
            "action": "user.admin.delete",
            "actor_id": principal["user_id"],
            "actor_role": principal.get("role"),
            "target_id": user_id,
            "request_id": request.state.request_id,
            "details": result,
        }
    )
    return {"status": "deleted", "user_id": user_id, **result}


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
