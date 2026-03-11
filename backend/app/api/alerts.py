"""
Alert management REST API endpoints.
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from typing import Optional
from ..db import db
from ..models import AlertAcknowledge
from ..utils.access import ensure_alert_access, ensure_user_access
from ..utils.auth import require_current_user


router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/users/{user_id}/alerts")
async def get_alerts(
    user_id: str,
    severity: Optional[str] = Query(None, pattern="^(info|warning|critical)$"),
    acknowledged: Optional[bool] = None,
    limit: int = Query(default=100, le=1000),
    current_user: dict = Depends(require_current_user),
):
    """Get alert history for a user."""
    await ensure_user_access(current_user, user_id)
    items = await db.get_alerts(
        user_id=user_id,
        severity=severity,
        acknowledged=acknowledged,
        limit=limit
    )
    
    return {
        "user_id": user_id,
        "count": len(items),
        "items": items
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    ack: AlertAcknowledge,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Acknowledge an alert."""
    await ensure_alert_access(current_user, alert_id)
    success = await db.acknowledge_alert(
        alert_id=alert_id,
        acknowledged_by=current_user["user_id"],
        notes=ack.notes
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
    await db.insert_audit_log(
        {
            "action": "alert.acknowledge",
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
            "target_id": alert_id,
            "request_id": request.state.request_id,
        }
    )
    
    return {"status": "success", "alert_id": alert_id}
