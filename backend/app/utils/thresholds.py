"""
Helpers for device-level alert-threshold payloads.
"""
from typing import Any, Dict


DEVICE_THRESHOLD_FIELDS = (
    "spo2_low",
    "spo2_critical",
    "temp_high",
    "temp_critical",
    "temp_low",
    "hr_low",
    "hr_low_critical",
    "hr_high",
    "hr_critical",
)


def sanitize_device_thresholds(thresholds: Any) -> Dict[str, Any]:
    """Keep only supported threshold keys and drop null/legacy fields."""
    if hasattr(thresholds, "model_dump"):
        thresholds = thresholds.model_dump(exclude_none=True)
    elif hasattr(thresholds, "dict"):
        thresholds = thresholds.dict(exclude_none=True)

    if not isinstance(thresholds, dict):
        return {}

    return {
        key: thresholds[key]
        for key in DEVICE_THRESHOLD_FIELDS
        if thresholds.get(key) is not None
    }
