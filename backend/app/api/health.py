"""
Health data REST API endpoints.
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from ..db import db
from ..models import HealthReading
from ..services import health_service


router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/users/{user_id}/vitals")
async def get_vitals(
    user_id: str,
    device_id: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = Query(default=100, le=1000)
):
    """Get vital signs for a user."""
    items = await db.get_health_readings(
        user_id=user_id,
        device_id=device_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit
    )
    
    return {
        "user_id": user_id,
        "count": len(items),
        "items": items
    }


@router.get("/users/{user_id}/latest")
async def get_latest_user_vitals(user_id: str, device_id: Optional[str] = None):
    """Get latest reading for a user (optionally filtered by device)."""
    item = await db.get_latest_user_reading(user_id=user_id, device_id=device_id)
    if not item:
        raise HTTPException(status_code=404, detail="No data found")
    return item


@router.get("/users/{user_id}/ecg")
async def get_ecg(
    user_id: str,
    quality_filter: Optional[str] = Query(None, regex="^(good|fair|poor)$"),
    limit: int = Query(default=10, le=100)
):
    """Get ECG waveform data for a user."""
    items = await db.get_ecg_readings(
        user_id=user_id,
        quality_filter=quality_filter,
        limit=limit
    )
    
    return {
        "user_id": user_id,
        "count": len(items),
        "items": items
    }


@router.get("/users/{user_id}/summary")
async def get_summary(
    user_id: str,
    period: str = Query(default="24h", regex="^(1h|6h|24h|7d|30d)$")
):
    """Get health summary statistics for a period."""
    # Calculate time range
    import time
    periods = {
        "1h": 3600,
        "6h": 21600,
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000
    }
    
    end_time = time.time()
    start_time = end_time - periods[period]
    
    # Get readings
    items = await db.get_health_readings(
        user_id=user_id,
        start_time=start_time,
        end_time=end_time,
        limit=10000
    )
    
    if not items:
        return {
            "user_id": user_id,
            "period": period,
            "error": "No data available for this period"
        }
    
    # Calculate summary statistics
    def calc_stats(values):
        if not values:
            return None
        return {
            "avg": round(sum(values) / len(values), 2),
            "min": min(values),
            "max": max(values)
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
        "user_id": user_id,
        "period": period,
        "summary": {
            "spo2": calc_stats(spo2_values),
            "temperature": calc_stats(temp_values),
            "heart_rate": calc_stats(hr_values),
            "respiratory_rate": calc_stats(rr_values)
        },
        "total_readings": len(items),
        "data_coverage": round(len(items) / (periods[period] / 60) * 100, 2) if periods[period] >= 3600 else 100
    }


@router.post("/health/readings")
async def post_health_reading(reading: HealthReading):
    """Manually post a health reading (for testing)."""
    reading_dict = reading.model_dump(exclude_none=True)
    success = await health_service.process_health_reading(reading_dict)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to process health reading")
    
    return {"status": "success", "device_id": reading.device_id}
