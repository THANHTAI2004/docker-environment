"""
Device management REST API endpoints.
"""
import logging
from datetime import datetime, timedelta
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
import uuid

from ..db import db
from ..models import DeviceCaregiverRequest, DeviceRegistration, DeviceViewerRequest, ECGRequestCommand, ThresholdsUpdate, DeviceLinkRequest
from ..utils.access import (
    filter_device_response,
    require_device_owner,
    require_device_read_access,
)
from ..utils.auth import hash_device_token, require_current_user, require_admin_user
from ..config import settings

router = APIRouter(prefix="/api/v1", tags=["devices"])
logger = logging.getLogger(__name__)


def _permission_of_link(link: Optional[dict]) -> Optional[str]:
    """Read one link permission from canonical or legacy shapes."""
    if not link:
        return None
    return link.get("permission") or link.get("link_role")


async def _link_device_viewer(
    device_id: str,
    target_user_id: str,
    request: Request,
    current_user: dict,
    *,
    action: str,
    legacy_path: bool = False,
):
    """Attach one viewer to a device owned by the caller."""
    await require_device_owner(current_user, device_id)

    target_user = await db.get_user(target_user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing_link = await db.get_device_link(device_id, target_user_id)
    if existing_link and _permission_of_link(existing_link) == "owner":
        raise HTTPException(status_code=400, detail="Owner cannot be changed via viewer link endpoint")

    result = await db.upsert_device_link(
        device_id=device_id,
        user_id=target_user_id,
        permission="viewer",
        added_by_user_id=current_user["user_id"],
    )
    if result == "error":
        raise HTTPException(status_code=500, detail="Failed to link viewer")

    details = {"user_id": target_user_id, "permission": "viewer", "result": result}
    if legacy_path:
        details["legacy_path"] = True
    await db.insert_audit_log(
        {
            "action": action,
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
            "target_id": device_id,
            "request_id": request.state.request_id,
            "details": details,
        }
    )
    return {
        "status": "linked",
        "device_id": device_id,
        "user_id": target_user_id,
        "permission": "viewer",
        "link_role": "viewer",
    }


async def _remove_device_viewer(
    device_id: str,
    user_id: str,
    request: Request,
    current_user: dict,
    *,
    action: str,
    legacy_path: bool = False,
):
    """Remove one viewer link from a device owned by the caller."""
    await require_device_owner(current_user, device_id)

    link = await db.get_device_link(device_id, user_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    if _permission_of_link(link) == "owner":
        raise HTTPException(status_code=400, detail="Owner cannot be removed from this endpoint")
    if _permission_of_link(link) != "viewer":
        raise HTTPException(status_code=400, detail="Target user is not a viewer on this device")

    success = await db.delete_device_link(device_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Link not found")

    details = {"user_id": user_id, "permission": "viewer"}
    if legacy_path:
        details["legacy_path"] = True
    await db.insert_audit_log(
        {
            "action": action,
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
            "target_id": device_id,
            "request_id": request.state.request_id,
            "details": details,
        }
    )
    return {"status": "success", "device_id": device_id, "user_id": user_id}


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
    """Backward-compatible alias for linking one viewer to a device."""
    if payload.permission == "owner":
        raise HTTPException(status_code=400, detail="Use /claim for owner assignment")
    target_user_id = payload.user_id
    if not target_user_id:
        raise HTTPException(status_code=422, detail="user_id is required")
    return await _link_device_viewer(
        device_id,
        target_user_id,
        request,
        current_user,
        action="device.link",
        legacy_path=True,
    )


@router.post("/devices/{device_id}/claim")
async def claim_device(
    device_id: str,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Claim a device as its owner when it has not been claimed yet."""
    device = await db.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    owner_link = await db.get_device_owner_link(device_id)
    if owner_link:
        raise HTTPException(status_code=409, detail="This device already has an owner")

    result = await db.upsert_device_link(
        device_id=device_id,
        user_id=current_user["user_id"],
        permission="owner",
        added_by_user_id=current_user["user_id"],
    )
    if result == "error":
        raise HTTPException(status_code=500, detail="Failed to claim device")

    await db.insert_audit_log(
        {
            "action": "device.claim",
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
            "target_id": device_id,
            "request_id": request.state.request_id,
        }
    )
    return {
        "status": "claimed",
        "device_id": device_id,
        "user_id": current_user["user_id"],
        "permission": "owner",
        "link_role": "owner",
    }


@router.post("/devices/{device_id}/caregivers")
async def add_device_caregiver(
    device_id: str,
    payload: DeviceCaregiverRequest,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Backward-compatible alias for adding one viewer to a device."""
    return await _link_device_viewer(
        device_id,
        payload.user_id,
        request,
        current_user,
        action="device.viewer.link",
        legacy_path=True,
    )


@router.post("/devices/{device_id}/viewers")
async def add_device_viewer(
    device_id: str,
    payload: DeviceViewerRequest,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Add one viewer to a device."""
    return await _link_device_viewer(
        device_id,
        payload.user_id,
        request,
        current_user,
        action="device.viewer.link",
    )


@router.get("/devices/{device_id}/viewers")
async def get_device_viewers(
    device_id: str,
    current_user: dict = Depends(require_current_user),
):
    """List viewer links for one device."""
    await require_device_owner(current_user, device_id)
    items = [
        item
        for item in await db.list_users_for_device(device_id)
        if (item.get("permission") or item.get("link_role")) == "viewer"
    ]
    return {"device_id": device_id, "count": len(items), "items": items}


@router.get("/devices/{device_id}/linked-users")
async def get_device_linked_users(
    device_id: str,
    current_user: dict = Depends(require_current_user),
):
    """List the users linked to one device."""
    await require_device_read_access(current_user, device_id)
    items = await db.list_users_for_device(device_id)
    return {"device_id": device_id, "count": len(items), "items": items}


@router.delete("/devices/{device_id}/links/{user_id}")
async def unlink_device_from_user(
    device_id: str,
    user_id: str,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Backward-compatible alias for removing a viewer link."""
    return await _remove_device_viewer(
        device_id,
        user_id,
        request,
        current_user,
        action="device.unlink",
        legacy_path=True,
    )


@router.delete("/devices/{device_id}/caregivers/{user_id}")
async def remove_device_caregiver(
    device_id: str,
    user_id: str,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Backward-compatible alias for removing one viewer from a device."""
    return await _remove_device_viewer(
        device_id,
        user_id,
        request,
        current_user,
        action="device.viewer.unlink",
        legacy_path=True,
    )


@router.delete("/devices/{device_id}/viewers/{user_id}")
async def remove_device_viewer(
    device_id: str,
    user_id: str,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Remove one viewer from a device."""
    return await _remove_device_viewer(
        device_id,
        user_id,
        request,
        current_user,
        action="device.viewer.unlink",
    )


@router.get("/devices/{device_id}")
async def get_device(device_id: str, current_user: dict = Depends(require_current_user)):
    """Get device details."""
    device = await require_device_read_access(current_user, device_id)
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
    await require_device_owner(current_user, device_id)

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
    current_user: dict = Depends(require_current_user),
):
    """Update alert thresholds stored directly on one device."""
    await require_device_owner(current_user, device_id)
    threshold_dict = {k: v for k, v in thresholds.model_dump().items() if v is not None}
    if not threshold_dict:
        raise HTTPException(status_code=400, detail="No thresholds provided")

    success = await db.update_device_thresholds(device_id, threshold_dict)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")

    await db.insert_audit_log(
        {
            "action": "device.thresholds.update",
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
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
    current_user: dict = Depends(require_current_user),
):
    """Generate and set new ESP token for a device (shown only once)."""
    await require_device_owner(current_user, device_id)

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
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
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
    await require_device_read_access(current_user, device_id)
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

    device = await require_device_read_access(current_user, device_id)

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
    await require_device_read_access(current_user, device_id)
    latest = await db.get_latest_reading(device_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No data found for this device")
    return latest


@router.get("/devices/{device_id}/ecg")
async def get_device_ecg(
    device_id: str,
    quality_filter: Optional[str] = Query(default=None, pattern="^(good|fair|poor)$"),
    limit: int = Query(default=10, le=100),
    current_user: dict = Depends(require_current_user),
):
    """Get ECG waveform history for one device."""
    await require_device_read_access(current_user, device_id)
    items = await db.get_device_ecg_readings(
        device_id=device_id,
        quality_filter=quality_filter,
        limit=limit,
    )
    return {
        "device_id": device_id,
        "count": len(items),
        "items": items,
    }


@router.get("/devices/{device_id}/summary")
async def get_device_summary(
    device_id: str,
    period: str = Query(default="24h", pattern="^(1h|6h|24h|7d|30d)$"),
    current_user: dict = Depends(require_current_user),
):
    """Get aggregate summary statistics for one device."""
    return await _build_device_summary(device_id, period, current_user)


# Deprecated aliases kept temporarily for older clients.
# New mobile app must use /api/v1/devices/{device_id}/...
@router.get("/public/devices/{device_id}", deprecated=True)
async def get_public_device(device_id: str, current_user: dict = Depends(require_current_user)):
    """Authenticated device profile alias kept for backward compatibility."""
    logger.warning("Deprecated public device endpoint used for device=%s", device_id)
    device = await require_device_read_access(current_user, device_id)
    return {
        "device_id": device.get("device_id"),
        "device_type": device.get("device_type"),
        "device_name": device.get("device_name"),
        "firmware_version": device.get("firmware_version"),
        "registered_at": device.get("registered_at"),
        "last_seen": device.get("last_seen"),
        "status": device.get("status"),
    }


@router.get("/public/devices/{device_id}/history", deprecated=True)
async def get_public_device_history(
    device_id: str,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = Query(default=100, le=2000),
    current_user: dict = Depends(require_current_user),
):
    """Authenticated history alias kept for backward compatibility."""
    logger.warning("Deprecated public device history endpoint used for device=%s", device_id)
    await require_device_read_access(current_user, device_id)
    items = await db.get_readings_by_device(
        device_id=device_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    return {"device_id": device_id, "count": len(items), "items": items}


@router.get("/public/devices/{device_id}/latest", deprecated=True)
async def get_public_device_latest(
    device_id: str,
    current_user: dict = Depends(require_current_user),
):
    """Authenticated latest-reading alias kept for backward compatibility."""
    logger.warning("Deprecated public device latest endpoint used for device=%s", device_id)
    await require_device_read_access(current_user, device_id)
    latest = await db.get_latest_reading(device_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No data found for this device")
    return latest


@router.get("/public/devices/{device_id}/ecg", deprecated=True)
async def get_public_device_ecg(
    device_id: str,
    quality_filter: Optional[str] = Query(default=None, pattern="^(good|fair|poor)$"),
    limit: int = Query(default=10, le=100),
    current_user: dict = Depends(require_current_user),
):
    """Authenticated ECG history alias kept for backward compatibility."""
    logger.warning("Deprecated public device ECG endpoint used for device=%s", device_id)
    await require_device_read_access(current_user, device_id)
    items = await db.get_device_ecg_readings(
        device_id=device_id,
        quality_filter=quality_filter,
        limit=limit,
    )
    return {"device_id": device_id, "count": len(items), "items": items}


@router.get("/public/devices/{device_id}/alerts", deprecated=True)
async def get_public_device_alerts(
    device_id: str,
    severity: Optional[str] = Query(default=None, pattern="^(info|warning|critical)$"),
    acknowledged: Optional[bool] = None,
    limit: int = Query(default=100, le=1000),
    current_user: dict = Depends(require_current_user),
):
    """Authenticated alert history alias kept for backward compatibility."""
    logger.warning("Deprecated public device alerts endpoint used for device=%s", device_id)
    await require_device_read_access(current_user, device_id)
    items = await db.get_alerts_by_device(
        device_id=device_id,
        severity=severity,
        acknowledged=acknowledged,
        limit=limit,
    )
    return {"device_id": device_id, "count": len(items), "items": items}


@router.get("/public/devices/{device_id}/summary", deprecated=True)
async def get_public_device_summary(
    device_id: str,
    period: str = Query(default="24h", pattern="^(1h|6h|24h|7d|30d)$"),
    current_user: dict = Depends(require_current_user),
):
    """Authenticated summary alias kept for backward compatibility."""
    logger.warning("Deprecated public device summary endpoint used for device=%s", device_id)
    return await _build_device_summary(device_id, period, current_user)


@router.post("/devices/{device_id}/commands/{command_id}/cancel")
async def cancel_device_command(
    device_id: str,
    command_id: str,
    request: Request,
    current_user: dict = Depends(require_current_user),
):
    """Cancel a queued or in-flight command."""
    await require_device_owner(current_user, device_id)
    success = await db.cancel_device_command(device_id, command_id, "Cancelled by device owner")
    if not success:
        raise HTTPException(status_code=404, detail="Command not found or already finished")
    await db.insert_audit_log(
        {
            "action": "device.command.cancel",
            "actor_id": current_user["user_id"],
            "actor_role": current_user["role"],
            "target_id": command_id,
            "request_id": request.state.request_id,
            "details": {"device_id": device_id},
        }
    )
    return {"status": "cancelled", "command_id": command_id}
