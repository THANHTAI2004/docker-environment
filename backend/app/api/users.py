"""
User management REST API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from ..db import db
from ..models import UserCreate, ThresholdsUpdate
from ..utils.auth import require_admin_api_key


router = APIRouter(prefix="/api/v1", tags=["users"])


@router.post("/users")
async def create_user(user: UserCreate, _: None = Depends(require_admin_api_key)):
    """Create a new user."""
    user_dict = user.model_dump(exclude_none=True)
    success = await db.create_user(user_dict)
    
    if not success:
        raise HTTPException(status_code=400, detail="User creation failed (may already exist)")
    
    return {"status": "success", "user_id": user.user_id}


@router.get("/users/{user_id}")
async def get_user(user_id: str):
    """Get user profile."""
    user = await db.get_user(user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user


@router.patch("/users/{user_id}/thresholds")
async def update_thresholds(
    user_id: str,
    thresholds: ThresholdsUpdate,
    _: None = Depends(require_admin_api_key),
):
    """Update user's alert thresholds."""
    # Only include non-None values
    threshold_dict = {k: v for k, v in thresholds.model_dump().items() if v is not None}
    
    if not threshold_dict:
        raise HTTPException(status_code=400, detail="No thresholds provided")
    
    success = await db.update_user_thresholds(user_id, threshold_dict)
    
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"status": "success", "user_id": user_id, "updated_thresholds": threshold_dict}
