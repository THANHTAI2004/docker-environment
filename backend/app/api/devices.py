"""
Device management REST API endpoints.
"""
from datetime import datetime, timedelta
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
import uuid

from ..db import db
from ..models import DeviceRegistration, ECGRequestCommand, ThresholdsUpdate, DeviceLinkRequest
from ..utils.access import ensure_device_access, filter_device_response
from ..utils.auth import hash_device_token, require_current_user, require_admin_user
from ..config import settings

router = APIRouter(prefix="/api/v1", tags=["devices"])


@router.post("/devices/register")
async def register_device(
    device: DeviceRegistration,
    request: Request,
    principal: dict = Depends(require_admin_user),
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


@router.post("/devices/{device_id}/links")
async def link_device_to_user(
    device_id: str,
    payload: DeviceLinkRequest,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Link the current user, or a specified user, to one device."""
    device = await db.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    target_user_id = payload.user_id or current_user["user_id"]
    if target_user_id != current_user["user_id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can link another user")

    target_user = await db.get_user(target_user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.link_role == "owner":
        owner_link = await db.get_device_owner_link(device_id)
        if owner_link and owner_link.get("user_id") != target_user_id:
            raise HTTPException(status_code=409, detail="This device already has an owner")

    result = await db.upsert_device_link(
        device_id=device_id,
        user_id=target_user_id,
        link_role=payload.link_role,
        linked_by=current_user["user_id"],
    )
    if result == "error":
        raise HTTPException(status_code=500, detail="Failed to link device")

    await db.insert_audit_log(
        {
            "action": "device.link",
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
            "target_id": device_id,
            "request_id": request.state.request_id,
            "details": {
                "user_id": target_user_id,
                "link_role": payload.link_role,
                "result": result,
            },
        }
    )
    return {
        "status": result,
        "device_id": device_id,
        "user_id": target_user_id,
        "link_role": payload.link_role,
    }


@router.get("/devices/{device_id}/linked-users")
async def get_device_linked_users(
    device_id: str,
    current_user: dict = Depends(require_current_user),
):
    """List the users linked to one device."""
    await ensure_device_access(current_user, device_id)
    items = await db.list_users_for_device(device_id)
    return {"device_id": device_id, "count": len(items), "items": items}


@router.delete("/devices/{device_id}/links/{user_id}")
async def unlink_device_from_user(
    device_id: str,
    user_id: str,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Remove one user-device link."""
    if current_user.get("role") != "admin" and current_user.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if current_user.get("role") != "admin":
        await ensure_device_access(current_user, device_id)
    else:
        device = await db.get_device(device_id)
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

    success = await db.delete_device_link(device_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Link not found")

    await db.insert_audit_log(
        {
            "action": "device.unlink",
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
            "target_id": device_id,
            "request_id": request.state.request_id,
            "details": {"user_id": user_id},
        }
    )
    return {"status": "success", "device_id": device_id, "user_id": user_id}


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
    await ensure_device_access(current_user, device_id)

    request_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(seconds=settings.command_ttl_seconds)
    enqueue_result = await db.enqueue_device_command(
        {
            "device_id": device_id,
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


@router.patch("/devices/{device_id}/thresholds")
async def update_device_thresholds(
    device_id: str,
    thresholds: ThresholdsUpdate,
    request: Request,
    principal: dict = Depends(require_admin_user),
):
    """Update alert thresholds stored directly on one device."""
    threshold_dict = {k: v for k, v in thresholds.model_dump().items() if v is not None}
    if not threshold_dict:
        raise HTTPException(status_code=400, detail="No thresholds provided")

    success = await db.update_device_thresholds(device_id, threshold_dict)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")

    await db.insert_audit_log(
        {
            "action": "device.thresholds.update",
            "actor_id": principal["user_id"],
            "actor_role": principal["role"],
            "target_id": device_id,
            "request_id": request.state.request_id,
            "details": {"updated_fields": sorted(threshold_dict.keys())},
        }
    )
    return {"status": "success", "device_id": device_id, "updated_thresholds": threshold_dict}


@router.post("/devices/{device_id}/esp-token")
async def rotate_esp_token(
    device_id: str,
    request: Request,
    principal: dict = Depends(require_admin_user),
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


async def _build_device_summary(device_id: str, period: str, current_user: dict):
    """Build summary stats while tolerating small device clock drift."""
    import time

    device = await ensure_device_access(current_user, device_id)

    periods = {
        "1h": 3600,
        "6h": 21600,
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000,
    }
    skew_tolerance = max(0, settings.device_clock_skew_tolerance_seconds)
    now = time.time()
    start_time = now - periods[period]
    end_time = now + skew_tolerance

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
        "clock_skew_tolerance_seconds": skew_tolerance,
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
    return await _build_device_summary(device_id, period, current_user)


@router.get("/public/devices/{device_id}")
async def get_public_device(device_id: str, current_user: dict = Depends(require_current_user)):
    """Authenticated device profile alias kept for backward compatibility."""
    device = await ensure_device_access(current_user, device_id)
    return {
        "device_id": device.get("device_id"),
        "device_type": device.get("device_type"),
        "device_name": device.get("device_name"),
        "firmware_version": device.get("firmware_version"),
        "registered_at": device.get("registered_at"),
        "last_seen": device.get("last_seen"),
        "status": device.get("status"),
    }


@router.get("/public/devices/{device_id}/history")
async def get_public_device_history(
    device_id: str,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = Query(default=100, le=2000),
    current_user: dict = Depends(require_current_user),
):
    """Authenticated history alias kept for backward compatibility."""
    await ensure_device_access(current_user, device_id)
    items = await db.get_readings_by_device(
        device_id=device_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    return {"device_id": device_id, "count": len(items), "items": items}


@router.get("/public/devices/{device_id}/latest")
async def get_public_device_latest(
    device_id: str,
    current_user: dict = Depends(require_current_user),
):
    """Authenticated latest-reading alias kept for backward compatibility."""
    await ensure_device_access(current_user, device_id)
    latest = await db.get_latest_reading(device_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No data found for this device")
    return latest


@router.get("/public/devices/{device_id}/ecg")
async def get_public_device_ecg(
    device_id: str,
    quality_filter: Optional[str] = Query(default=None, pattern="^(good|fair|poor)$"),
    limit: int = Query(default=10, le=100),
    current_user: dict = Depends(require_current_user),
):
    """Authenticated ECG history alias kept for backward compatibility."""
    await ensure_device_access(current_user, device_id)
    items = await db.get_device_ecg_readings(
        device_id=device_id,
        quality_filter=quality_filter,
        limit=limit,
    )
    return {"device_id": device_id, "count": len(items), "items": items}


@router.get("/public/devices/{device_id}/alerts")
async def get_public_device_alerts(
    device_id: str,
    severity: Optional[str] = Query(default=None, pattern="^(info|warning|critical)$"),
    acknowledged: Optional[bool] = None,
    limit: int = Query(default=100, le=1000),
    current_user: dict = Depends(require_current_user),
):
    """Authenticated alert history alias kept for backward compatibility."""
    await ensure_device_access(current_user, device_id)
    items = await db.get_alerts_by_device(
        device_id=device_id,
        severity=severity,
        acknowledged=acknowledged,
        limit=limit,
    )
    return {"device_id": device_id, "count": len(items), "items": items}


@router.get("/public/devices/{device_id}/summary")
async def get_public_device_summary(
    device_id: str,
    period: str = Query(default="24h", pattern="^(1h|6h|24h|7d|30d)$"),
    current_user: dict = Depends(require_current_user),
):
    """Authenticated summary alias kept for backward compatibility."""
    return await _build_device_summary(device_id, period, current_user)


@router.post("/devices/{device_id}/commands/{command_id}/cancel")
async def cancel_device_command(
    device_id: str,
    command_id: str,
    request: Request,
    principal: dict = Depends(require_admin_user),
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
