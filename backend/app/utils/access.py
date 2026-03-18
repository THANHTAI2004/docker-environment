"""
Authorization helpers for user/device ownership and response filtering.
"""
from typing import Any, Dict

from fastapi import HTTPException, status

from ..db import db


async def ensure_user_access(principal: Dict[str, Any], target_user_id: str) -> Dict[str, Any]:
    """Ensure the actor can view or manage the target user."""
    user = await db.get_user(target_user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    actor_user_id = principal.get("user_id")
    if not actor_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if actor_user_id == target_user_id:
        return user
    if actor_user_id and await db.users_share_device_access(actor_user_id, target_user_id):
        return user

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


async def ensure_device_view_access(principal: Dict[str, Any], device_id: str) -> Dict[str, Any]:
    """Ensure the actor can view one device and return its record."""
    device = await db.get_device(device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    actor_user_id = principal.get("user_id")
    if not actor_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    link = await db.get_device_link(device_id, actor_user_id)
    if not link or link.get("link_role") not in {"owner", "viewer"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return device


async def ensure_device_owner(principal: Dict[str, Any], device_id: str) -> Dict[str, Any]:
    """Ensure the actor is the owner of one device and return its record."""
    device = await db.get_device(device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    actor_user_id = principal.get("user_id")
    if not actor_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    link = await db.get_device_link(device_id, actor_user_id)
    if not link or link.get("link_role") != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return device


async def ensure_device_manage_access(principal: Dict[str, Any], device_id: str) -> Dict[str, Any]:
    """Ensure the actor can manage one device and return its record."""
    return await ensure_device_owner(principal, device_id)


async def ensure_device_access(principal: Dict[str, Any], device_id: str) -> Dict[str, Any]:
    """Backward-compatible alias for device view access."""
    return await ensure_device_view_access(principal, device_id)


async def ensure_alert_access(principal: Dict[str, Any], alert_id: str) -> Dict[str, Any]:
    """Ensure the actor can access one alert."""
    alert = await db.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    await ensure_device_view_access(principal, alert["device_id"])
    return alert


def filter_device_response(device: Dict[str, Any], principal: Dict[str, Any]) -> Dict[str, Any]:
    """Hide device-internal fields from non-admin callers."""
    visible = {
        "device_id": device.get("device_id"),
        "device_type": device.get("device_type"),
        "device_name": device.get("device_name"),
        "firmware_version": device.get("firmware_version"),
        "registered_at": device.get("registered_at"),
        "last_seen": device.get("last_seen"),
        "status": device.get("status"),
        "alert_thresholds": device.get("alert_thresholds"),
    }
    if principal.get("role") == "admin":
        if "metadata" in device:
            visible["metadata"] = device["metadata"]
    return visible
