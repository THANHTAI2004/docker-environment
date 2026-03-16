"""
ESP-facing REST API endpoints.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from ..db import db
from ..models import ESPCommandAck, HealthReading
from ..observability import ESP_VALIDATION_FAILURE_TOTAL
from ..services import health_service
from ..utils.auth import require_device_token


router = APIRouter(prefix="/api/v1/esp", tags=["esp"])


@router.post("/devices/{device_id}/readings")
async def ingest_reading(
    device_id: str,
    payload: Dict[str, Any],
    device: Dict[str, Any] = Depends(require_device_token),
):
    """Receive one ESP health reading via HTTPS and store in MongoDB."""
    reading = dict(payload)
    reading["device_id"] = device_id

    try:
        validated = HealthReading(**reading)
    except ValidationError as exc:
        ESP_VALIDATION_FAILURE_TOTAL.inc()
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    success = await health_service.process_health_reading(
        validated.model_dump(exclude_none=True)
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to process reading")

    return {"status": "success", "device_id": device_id}


@router.get("/devices/{device_id}/commands/next")
async def poll_next_command(
    device_id: str,
    _: Dict[str, Any] = Depends(require_device_token),
):
    """Poll one pending command for ESP device."""
    command = await db.claim_next_device_command(device_id)
    if not command:
        return {"status": "idle"}

    return {
        "status": "ok",
        "command_id": command.get("_id"),
        "request_id": command.get("request_id"),
        "command": command.get("command"),
        "payload": command.get("payload", {}),
        "created_at": command.get("created_at"),
        "expires_at": command.get("expires_at"),
    }


@router.post("/devices/{device_id}/commands/{command_id}/ack")
async def acknowledge_command(
    device_id: str,
    command_id: str,
    ack: ESPCommandAck,
    _: Dict[str, Any] = Depends(require_device_token),
):
    """Acknowledge command completion from ESP."""
    success = await db.acknowledge_device_command(
        device_id=device_id,
        command_id=command_id,
        status=ack.status,
        message=ack.message,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Command not found")
    return {"status": "success", "command_id": command_id}
