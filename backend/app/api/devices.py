"""
Device management REST API endpoints.
"""
from datetime import datetime, timedelta
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
import uuid

from ..db import db
from ..models import DeviceRegistration, ECGRequestCommand
from ..utils.access import ensure_device_access, filter_device_response
from ..utils.auth import hash_device_token, require_admin_principal, require_current_user
from ..config import settings

router = APIRouter(prefix="/api/v1", tags=["devices"])


@router.post("/devices/register")
async def register_device(
    device: DeviceRegistration,
    request: Request,
    principal: dict = Depends(require_admin_principal),
):
    """Register or update one device."""
    device_dict = device.model_dump(exclude_none=True)
    success = await db.register_device(device_dict)
    if not success:
        raise HTTPException(status_code=400, detail="Device registration failed")
    await db.insert_audit_log(
        {
            "action": "device.register",
            "actor_id": principal["user_id"],
            "actor_role": principal["role"],
            "target_id": device.device_id,
            "request_id": request.state.request_id,
        }
    )
    return {"status": "success", "device_id": device.device_id}


@router.get("/devices/{device_id}")
async def get_device(device_id: str, current_user: dict = Depends(require_current_user)):
    """Get device details."""
    device = await ensure_device_access(current_user, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return filter_device_response(device, current_user)


@router.post("/devices/{device_id}/ecg/request")
async def request_ecg(
    device_id: str,
    command: ECGRequestCommand,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Queue ECG command; ESP will receive it via REST polling."""
    device = await ensure_device_access(current_user, device_id)

    user_id = command.user_id or device.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="user_id is required (provide in request body or register device with user_id)",
        )
    if device.get("user_id") and user_id != device.get("user_id"):
        raise HTTPException(status_code=400, detail="user_id does not match device ownership")

    request_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(seconds=settings.command_ttl_seconds)
    enqueue_result = await db.enqueue_device_command(
        {
            "device_id": device_id,
            "user_id": user_id,
            "request_id": request_id,
            "command": "ecg_request",
            "payload": {
                "duration_seconds": command.duration_seconds,
                "sampling_rate": command.sampling_rate,
            },
            "expires_at": expires_at,
        }
    )
    if enqueue_result["status"] == "limit_reached":
        raise HTTPException(status_code=409, detail="Too many pending commands for this device")
    if enqueue_result["status"] == "error":
        raise HTTPException(status_code=500, detail="Failed to enqueue command")
    if enqueue_result["status"] == "duplicate":
        return {
            "status": "already_queued",
            "delivery": "rest_polling",
            "request_id": enqueue_result.get("request_id"),
            "command_id": enqueue_result.get("command_id"),
            "expires_at": enqueue_result.get("expires_at").isoformat()
            if enqueue_result.get("expires_at")
            else None,
        }

    await db.insert_audit_log(
        {
            "action": "device.ecg.request",
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
            "target_id": device_id,
            "request_id": request.state.request_id,
            "details": {
                "user_id": user_id,
                "duration_seconds": command.duration_seconds,
                "sampling_rate": command.sampling_rate,
            },
        }
    )

    return {
        "status": "queued",
        "delivery": "rest_polling",
        "request_id": request_id,
        "command_id": enqueue_result["command_id"],
        "expires_at": expires_at.isoformat(),
    }


@router.post("/devices/{device_id}/esp-token")
async def rotate_esp_token(
    device_id: str,
    request: Request,
    principal: dict = Depends(require_admin_principal),
):
    """Generate and set new ESP token for a device (shown only once)."""
    device = await db.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    token = secrets.token_urlsafe(32)
    token_hash = hash_device_token(token)
    success = await db.set_device_token_hash(
        device_id=device_id,
        token_hash=token_hash,
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set ESP token")
    await db.insert_audit_log(
        {
            "action": "device.esp_token.rotate",
            "actor_id": principal["user_id"],
            "actor_role": principal["role"],
            "target_id": device_id,
            "request_id": request.state.request_id,
        }
    )
    return {"device_id": device_id, "esp_token": token}


async def _get_device_history(
    device_id: str,
    start_time: Optional[float],
    end_time: Optional[float],
    limit: int,
    current_user: dict,
):
    await ensure_device_access(current_user, device_id)
    items = await db.get_readings_by_device(
        device_id=device_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    return {
        "device_id": device_id,
        "count": len(items),
        "items": items,
    }


@router.get("/devices/{device_id}/history")
async def get_device_history(
    device_id: str,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = Query(default=100, le=2000),
    current_user: dict = Depends(require_current_user),
):
    """Get historical readings for one device."""
    return await _get_device_history(device_id, start_time, end_time, limit, current_user)


@router.get("/devices/{device_id}/vitals")
async def get_device_vitals(
    device_id: str,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = Query(default=100, le=2000),
    current_user: dict = Depends(require_current_user),
):
    """Backward-compatible alias for /history."""
    return await _get_device_history(device_id, start_time, end_time, limit, current_user)


@router.get("/devices/{device_id}/latest")
async def get_device_latest(device_id: str, current_user: dict = Depends(require_current_user)):
    """Get most recent reading from one device."""
    await ensure_device_access(current_user, device_id)
    latest = await db.get_latest_reading(device_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No data found for this device")
    return latest


@router.get("/devices/{device_id}/summary")
async def get_device_summary(
    device_id: str,
    period: str = Query(default="24h", pattern="^(1h|6h|24h|7d|30d)$"),
    current_user: dict = Depends(require_current_user),
):
    """Get aggregate summary statistics for one device."""
    import time
    device = await ensure_device_access(current_user, device_id)

    periods = {
        "1h": 3600,
        "6h": 21600,
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000,
    }

    end_time = time.time()
    start_time = end_time - periods[period]
    items = await db.get_readings_by_device(
        device_id=device_id,
        start_time=start_time,
        end_time=end_time,
        limit=10000,
    )

    if not items:
        return {
            "device_id": device_id,
            "period": period,
            "error": "No data available for this period",
        }

    def calc_stats(values):
        if not values:
            return None
        return {
            "avg": round(sum(values) / len(values), 2),
            "min": min(values),
            "max": max(values),
        }

    def get_vital(item, key):
        if "vitals" in item and item["vitals"] and key in item["vitals"]:
            return item["vitals"][key]
        return item.get(key)

    spo2_values = [v for item in items if (v := get_vital(item, "spo2")) is not None]
    temp_values = [v for item in items if (v := get_vital(item, "temperature")) is not None]
    hr_values = [v for item in items if (v := get_vital(item, "heart_rate")) is not None]
    rr_values = [v for item in items if (v := get_vital(item, "respiratory_rate")) is not None]

    return {
        "device_id": device_id,
        "period": period,
        "device_type": device.get("device_type"),
        "summary": {
            "spo2": calc_stats(spo2_values),
            "temperature": calc_stats(temp_values),
            "heart_rate": calc_stats(hr_values),
            "respiratory_rate": calc_stats(rr_values),
        },
        "total_readings": len(items),
        "reading_density_per_hour": round(len(items) / (periods[period] / 3600), 2),
    }


@router.post("/devices/{device_id}/commands/{command_id}/cancel")
async def cancel_device_command(
    device_id: str,
    command_id: str,
    request: Request,
    principal: dict = Depends(require_admin_principal),
):
    """Cancel a queued or in-flight command."""
    success = await db.cancel_device_command(device_id, command_id, "Cancelled by admin")
    if not success:
        raise HTTPException(status_code=404, detail="Command not found or already finished")
    await db.insert_audit_log(
        {
            "action": "device.command.cancel",
            "actor_id": principal["user_id"],
            "actor_role": principal["role"],
            "target_id": command_id,
            "request_id": request.state.request_id,
            "details": {"device_id": device_id},
        }
    )
    return {"status": "cancelled", "command_id": command_id}
