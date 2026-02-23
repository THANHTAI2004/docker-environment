"""
Alert management REST API endpoints.
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from ..db import db
from ..models import AlertAcknowledge


router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/users/{user_id}/alerts")
async def get_alerts(
    user_id: str,
    severity: Optional[str] = Query(None, regex="^(info|warning|critical)$"),
    acknowledged: Optional[bool] = None,
    limit: int = Query(default=100, le=1000)
):
    """Get alert history for a user."""
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
    ack: AlertAcknowledge
):
    """Acknowledge an alert."""
    success = await db.acknowledge_alert(
        alert_id=alert_id,
        acknowledged_by=ack.acknowledged_by,
        notes=ack.notes
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
    
    return {"status": "success", "alert_id": alert_id}
