"""
Alert management REST API endpoints.
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from typing import Optional
from ..db import db
from ..models import AlertAcknowledge
from ..observability import ALERTS_ACKNOWLEDGED_TOTAL
from ..utils.access import ensure_user_access, require_alert_owner_access, require_device_read_access
from ..utils.auth import require_current_user


router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/me/alerts")
async def get_my_alerts(
    severity: Optional[str] = Query(None, pattern="^(info|warning|critical)$"),
    acknowledged: Optional[bool] = None,
    limit: int = Query(default=100, le=1000),
    current_user: dict = Depends(require_current_user),
):
    """Get alert history across every device linked to the current user."""
    items = await db.get_alerts(
        user_id=current_user["user_id"],
        severity=severity,
        acknowledged=acknowledged,
        limit=limit,
    )
    return {
        "user_id": current_user["user_id"],
        "count": len(items),
        "items": items,
    }


@router.get("/devices/{device_id}/alerts")
async def get_device_alerts(
    device_id: str,
    severity: Optional[str] = Query(None, pattern="^(info|warning|critical)$"),
    acknowledged: Optional[bool] = None,
    limit: int = Query(default=100, le=1000),
    current_user: dict = Depends(require_current_user),
):
    """Get alert history for one device."""
    await require_device_read_access(current_user, device_id)
    items = await db.get_alerts_by_device(
        device_id=device_id,
        severity=severity,
        acknowledged=acknowledged,
        limit=limit,
    )
    return {
        "device_id": device_id,
        "count": len(items),
        "items": items,
    }


@router.get("/users/{user_id}/alerts")
async def get_alerts(
    user_id: str,
    severity: Optional[str] = Query(None, pattern="^(info|warning|critical)$"),
    acknowledged: Optional[bool] = None,
    limit: int = Query(default=100, le=1000),
    current_user: dict = Depends(require_current_user),
):
    """Backward-compatible alias for user-scoped alert history."""
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
    """Acknowledge an alert as the owner of the underlying device."""
    alert = await require_alert_owner_access(current_user, alert_id)
    success = await db.acknowledge_alert(
        alert_id=alert_id,
        acknowledged_by=current_user["user_id"],
        notes=ack.notes
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
    ALERTS_ACKNOWLEDGED_TOTAL.labels(severity=alert.get("severity", "unknown")).inc()
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
