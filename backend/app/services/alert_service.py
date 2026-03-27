"""
Alert generation and management service.
Checks health metrics against thresholds and creates alerts.
"""
import logging
import time
from typing import Any, Dict, Optional

from ..config import settings
from ..db import db
from ..observability import ALERTS_CREATED_TOTAL

logger = logging.getLogger(__name__)


class AlertService:
    """Service for generating and managing health alerts."""

    def __init__(self):
        self.default_thresholds = {
            "spo2_low": settings.spo2_low_warning,
            "spo2_critical": settings.spo2_low_critical,
            "temp_high": settings.temp_high_warning,
            "temp_critical": settings.temp_high_critical,
            "temp_low": settings.temp_low_warning,
            "hr_low": settings.hr_low_warning,
            "hr_low_critical": settings.hr_low_critical,
            "hr_high": settings.hr_high_warning,
            "hr_critical": settings.hr_high_critical,
            "rr_low": settings.rr_low_warning,
            "rr_high": settings.rr_high_warning,
        }

    async def check_health_reading(
        self,
        reading: Dict[str, Any],
        device_thresholds: Optional[Dict[str, Any]] = None,
    ) -> list[Dict[str, Any]]:
        """
        Check a health reading against thresholds and generate alerts.
        Returns a list of newly generated alert documents.
        """
        alerts: list[Dict[str, Any]] = []
        thresholds = self._normalize_thresholds(device_thresholds)

        device_id = reading.get("device_id")
        timestamp = reading.get("timestamp", time.time())

        if not device_id:
            return alerts

        spo2 = self._get_metric(reading, "spo2")
        if spo2 is not None:
            if spo2 < thresholds["spo2_critical"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "spo2_low",
                        "critical",
                        "spo2",
                        spo2,
                        thresholds["spo2_critical"],
                        f"Blood oxygen critically low ({spo2}%)",
                    )
                )
            elif spo2 < thresholds["spo2_low"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "spo2_low",
                        "warning",
                        "spo2",
                        spo2,
                        thresholds["spo2_low"],
                        f"Blood oxygen below normal ({spo2}%)",
                    )
                )

        temp = self._get_metric(reading, "temperature")
        if temp is not None:
            if temp >= thresholds["temp_critical"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "temp_high",
                        "critical",
                        "temperature",
                        temp,
                        thresholds["temp_critical"],
                        f"Temperature critically high ({temp}C)",
                    )
                )
            elif temp >= thresholds["temp_high"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "temp_high",
                        "warning",
                        "temperature",
                        temp,
                        thresholds["temp_high"],
                        f"Temperature above normal ({temp}C)",
                    )
                )
            elif temp < thresholds["temp_low"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "temp_low",
                        "warning",
                        "temperature",
                        temp,
                        thresholds["temp_low"],
                        f"Temperature below normal ({temp}C)",
                    )
                )

        hr = self._get_metric(reading, "heart_rate")
        if hr is not None:
            if hr >= thresholds["hr_critical"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "hr_high",
                        "critical",
                        "heart_rate",
                        hr,
                        thresholds["hr_critical"],
                        f"Heart rate critically high ({hr} bpm)",
                    )
                )
            elif hr >= thresholds["hr_high"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "hr_high",
                        "warning",
                        "heart_rate",
                        hr,
                        thresholds["hr_high"],
                        f"Heart rate above normal ({hr} bpm)",
                    )
                )
            elif hr < thresholds["hr_low_critical"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "hr_low",
                        "critical",
                        "heart_rate",
                        hr,
                        thresholds["hr_low_critical"],
                        f"Heart rate critically low ({hr} bpm)",
                    )
                )
            elif hr < thresholds["hr_low"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "hr_low",
                        "warning",
                        "heart_rate",
                        hr,
                        thresholds["hr_low"],
                        f"Heart rate below normal ({hr} bpm)",
                    )
                )

        rr = self._get_metric(reading, "respiratory_rate")
        if rr is not None:
            if rr >= thresholds["rr_high"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "rr_high",
                        "warning",
                        "respiratory_rate",
                        rr,
                        thresholds["rr_high"],
                        f"Respiratory rate above normal ({rr} breaths/min)",
                    )
                )
            elif rr < thresholds["rr_low"]:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "rr_low",
                        "warning",
                        "respiratory_rate",
                        rr,
                        thresholds["rr_low"],
                        f"Respiratory rate below normal ({rr} breaths/min)",
                    )
                )

        ecg = reading.get("ecg")
        if ecg and settings.ecg_quality_alert:
            if ecg.get("lead_off") and settings.ecg_lead_off_alert:
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "ecg_lead_off",
                        "warning",
                        "ecg_quality",
                        1,
                        0,
                        "ECG lead disconnected",
                    )
                )
            elif ecg.get("quality") == "poor":
                alerts.append(
                    self._create_alert(
                        device_id,
                        timestamp,
                        "ecg_quality",
                        "info",
                        "ecg_quality",
                        0,
                        0,
                        "ECG signal quality is poor",
                    )
                )

        inserted_alerts: list[Dict[str, Any]] = []
        for alert in alerts:
            alert["recipient_user_ids"] = await db.get_alert_recipient_user_ids(alert["device_id"])
            alert_id = await db.insert_alert(alert)
            if alert_id:
                logger.info("Alert generated: %s - %s", alert["alert_type"], alert["message"])
                ALERTS_CREATED_TOTAL.labels(
                    severity=alert["severity"],
                    alert_type=alert["alert_type"],
                ).inc()
                inserted_alerts.append(alert)

        return inserted_alerts

    def _normalize_thresholds(self, user_thresholds: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge user thresholds over defaults and return a plain dict."""
        merged = dict(self.default_thresholds)
        if not user_thresholds:
            return merged

        if hasattr(user_thresholds, "model_dump"):
            user_thresholds = user_thresholds.model_dump(exclude_none=True)
        elif hasattr(user_thresholds, "dict"):
            user_thresholds = user_thresholds.dict(exclude_none=True)

        for key, value in user_thresholds.items():
            if value is not None:
                merged[key] = value
        return merged

    def _get_metric(self, reading: Dict[str, Any], key: str) -> Optional[float]:
        """Support both nested vitals and flat fields."""
        vitals = reading.get("vitals")
        if isinstance(vitals, dict) and vitals.get(key) is not None:
            return vitals.get(key)
        value = reading.get(key)
        return value

    def _create_alert(
        self,
        device_id: str,
        timestamp: float,
        alert_type: str,
        severity: str,
        metric: str,
        value: float,
        threshold: float,
        message: str,
    ) -> Dict[str, Any]:
        """Create an alert document."""
        alert = {
            "device_id": device_id,
            "timestamp": timestamp,
            "alert_type": alert_type,
            "severity": severity,
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "message": message,
            "acknowledged": False,
        }
        return alert


# Global alert service instance
alert_service = AlertService()
