"""
Push-token registration endpoints for authenticated app installations.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..db import db
from ..models import PushTokenUpsertRequest
from ..utils.auth import require_current_user


router = APIRouter(prefix="/api/v1", tags=["push"])


@router.post("/me/push-tokens")
async def register_push_token(
    payload: PushTokenUpsertRequest,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Register or refresh one push token for the current authenticated user."""
    result = await db.upsert_push_token(
        user_id=current_user["user_id"],
        installation_id=payload.installation_id,
        fcm_token=payload.fcm_token,
        platform=payload.platform,
        session_id=current_user.get("session_id"),
    )
    if result == "error":
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save push token")

    await db.insert_audit_log(
        {
            "action": "push_token.upsert",
            "actor_id": current_user["user_id"],
            "actor_role": current_user.get("role"),
            "target_id": payload.installation_id,
            "request_id": request.state.request_id,
            "details": {
                "platform": payload.platform,
                "result": result,
            },
        }
    )
    return {
        "status": "success",
        "result": result,
        "user_id": current_user["user_id"],
        "installation_id": payload.installation_id,
        "platform": payload.platform,
        "is_active": True,
    }


@router.delete("/me/push-tokens/{installation_id}")
async def delete_push_token(
    installation_id: str,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Deactivate one push token registration for the current authenticated user."""
    success = await db.deactivate_push_token(
        user_id=current_user["user_id"],
        installation_id=installation_id,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Push token not found")

    await db.insert_audit_log(
        {
            "action": "push_token.delete",
            "actor_id": current_user["user_id"],
            "actor_role": current_user.get("role"),
            "target_id": installation_id,
            "request_id": request.state.request_id,
        }
    )
    return {
        "status": "success",
        "user_id": current_user["user_id"],
        "installation_id": installation_id,
    }
