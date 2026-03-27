"""
ESP-facing REST API endpoints.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from ..models import HealthReading
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
