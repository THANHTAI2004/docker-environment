"""
Health data processing service.
Handles ingestion, normalization, persistence, and alert generation.
"""
import logging
import time
from datetime import datetime
from typing import Any, Dict

from ..db import db
from ..models import HealthReading
from .alert_service import alert_service

logger = logging.getLogger(__name__)


class HealthService:
    """Service for processing health data from devices."""

    async def process_health_reading(self, reading_data: Dict[str, Any]) -> bool:
        """
        Process one health reading from REST:
        - validate payload
        - normalize storage shape
        - store into MongoDB
        - generate alerts
        """
        try:
            reading_data = dict(reading_data)

            if not reading_data.get("device_type"):
                device_id = reading_data.get("device_id") or reading_data.get("device_uid")
                if device_id:
                    device = await db.get_device(device_id)
                    if device and device.get("device_type"):
                        reading_data["device_type"] = device["device_type"]

            if not reading_data.get("timestamp"):
                if reading_data.get("ts"):
                    reading_data["timestamp"] = reading_data["ts"]
                else:
                    reading_data["timestamp"] = time.time()

            reading = HealthReading(**reading_data)
            doc = self._normalize_for_storage(reading, reading_data)

            stored = await db.insert_health_reading(doc)
            if not stored:
                logger.error("Failed to insert health reading for %s", reading.device_id)
                return False

            await db.update_device_last_seen(reading.device_id)
            if doc.get("metadata"):
                await db.update_device_metadata(reading.device_id, doc["metadata"])

            user_thresholds = None
            if doc.get("user_id"):
                user = await db.get_user(doc["user_id"])
                if user and "alert_thresholds" in user:
                    user_thresholds = user["alert_thresholds"]

            await alert_service.check_health_reading(doc, user_thresholds)
            return True
        except Exception as exc:
            logger.error("Error processing health reading: %s", exc)
            return False

    async def process_ecg_data(self, ecg_data: Dict[str, Any]) -> bool:
        """ECG payloads use the same ingestion path."""
        return await self.process_health_reading(ecg_data)

    def _normalize_for_storage(self, reading: HealthReading, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize all supported payload variants to one DB document shape."""
        timestamp = float(reading.timestamp or time.time())
        received_at = datetime.utcnow()
        recorded_at = datetime.utcfromtimestamp(timestamp)

        vitals = {}
        if reading.vitals:
            vitals.update(reading.vitals.model_dump(exclude_none=True))

        for key in ("respiratory_rate", "heart_rate", "temperature", "spo2"):
            value = getattr(reading, key, None)
            if value is not None and key not in vitals:
                vitals[key] = value

        metadata = {}
        if reading.metadata:
            metadata.update(reading.metadata.model_dump(exclude_none=True))
        if reading.battery_level is not None and "battery_level" not in metadata:
            metadata["battery_level"] = reading.battery_level
        if reading.signal_strength is not None and "signal_strength" not in metadata:
            metadata["signal_strength"] = reading.signal_strength

        ecg = None
        if reading.ecg:
            ecg = reading.ecg.model_dump(exclude_none=True)
            if ecg.get("duration") is None and ecg.get("sampling_rate") and ecg.get("waveform"):
                ecg["duration"] = round(len(ecg["waveform"]) / float(ecg["sampling_rate"]), 3)

        doc: Dict[str, Any] = {
            "device_id": reading.device_id,
            "device_uid": reading.device_id,
            "device_type": reading.device_type,
            "timestamp": timestamp,
            "recorded_at": recorded_at,
            "received_at": received_at,
        }

        if reading.user_id:
            doc["user_id"] = reading.user_id
        if reading.seq is not None:
            doc["seq"] = reading.seq
        if vitals:
            doc["vitals"] = vitals
            # Keep flat fields for simple querying and backward compatibility.
            doc.update(vitals)
        if metadata:
            doc["metadata"] = metadata
            if metadata.get("battery_level") is not None:
                doc["battery_level"] = metadata["battery_level"]
            if metadata.get("signal_strength") is not None:
                doc["signal_strength"] = metadata["signal_strength"]
        if ecg:
            doc["ecg"] = ecg
        if reading.location:
            doc["location"] = reading.location.model_dump(exclude_none=True)

        if raw.get("topic"):
            doc["topic"] = raw["topic"]
        if raw.get("source"):
            doc["source"] = raw["source"]
        return doc


# Global health service instance
health_service = HealthService()
