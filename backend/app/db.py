"""
MongoDB database operations for health monitoring.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import motor.motor_asyncio
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .config import settings

logger = logging.getLogger(__name__)


class Database:
    """MongoDB database manager with health monitoring support."""

    def __init__(self):
        self.client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
        self.db = None

        # Legacy collection (backward compatibility)
        self.collection = None

        # Health monitoring collections
        self.health_readings = None
        self.alerts = None
        self.devices = None
        self.users = None
        self.device_commands = None

    def connect(self):
        """Initialize MongoDB connection and collection references."""
        self.client = motor.motor_asyncio.AsyncIOMotorClient(settings.mongo_uri)
        self.db = self.client[settings.mongo_db]
        self.collection = self.db[settings.mongo_collection]
        self.health_readings = self.db[settings.mongo_health_collection]
        self.alerts = self.db[settings.mongo_alerts_collection]
        self.devices = self.db[settings.mongo_devices_collection]
        self.users = self.db[settings.mongo_users_collection]
        self.device_commands = self.db[settings.mongo_commands_collection]

    async def _ensure_ttl_index(
        self,
        collection,
        key_spec,
        ttl_seconds: int,
    ) -> None:
        """
        Ensure one TTL index exists with the expected expireAfterSeconds.
        If an index with the same key exists but without TTL options, replace it.
        """
        target_name = "_".join(f"{field}_{direction}" for field, direction in key_spec)
        existing = None
        async for idx in collection.list_indexes():
            if idx.get("name") == target_name:
                existing = idx
                break

        if existing is not None:
            if existing.get("expireAfterSeconds") == ttl_seconds:
                return
            await collection.drop_index(target_name)
            logger.info("Replaced index %s with TTL=%s", target_name, ttl_seconds)

        await collection.create_index(key_spec, expireAfterSeconds=ttl_seconds)

    async def create_indexes(self):
        """Create database indexes for query speed and retention."""
        if self.collection is None:
            return

        try:
            # Legacy collection
            await self.collection.create_index([("device_id", 1)])
            await self.collection.create_index([("ts", -1)])

            # Health readings
            await self.health_readings.create_index([("user_id", 1), ("timestamp", -1)])
            await self.health_readings.create_index([("device_id", 1), ("timestamp", -1)])
            await self.health_readings.create_index([("device_uid", 1), ("timestamp", -1)])
            await self.health_readings.create_index([("device_type", 1)])
            await self.health_readings.create_index([("recorded_at", 1)], expireAfterSeconds=7776000)
            # QoS1 de-duplication: same (device_id, seq) only stored once when seq exists.
            await self.health_readings.create_index(
                [("device_id", 1), ("seq", 1)],
                unique=True,
                partialFilterExpression={"seq": {"$type": "number"}},
            )

            # Alerts
            await self.alerts.create_index([("user_id", 1), ("timestamp", -1)])
            await self.alerts.create_index([("severity", 1), ("acknowledged", 1)])
            await self.alerts.create_index([("device_id", 1)])
            await self.alerts.create_index([("recorded_at", 1)], expireAfterSeconds=15552000)

            # Devices
            await self.devices.create_index([("device_id", 1)], unique=True)
            await self.devices.create_index([("user_id", 1)])
            await self.devices.create_index([("status", 1)])
            await self.devices.create_index([("esp_token_hash", 1)], unique=True, sparse=True)

            # Users
            await self.users.create_index([("user_id", 1)], unique=True)
            await self.users.create_index([("email", 1)], unique=True, sparse=True)
            await self.users.create_index([("role", 1)])

            # Device commands (ESP polling)
            await self.device_commands.create_index([("device_id", 1), ("status", 1), ("created_at", 1)])
            await self.device_commands.create_index([("request_id", 1)], unique=True, sparse=True)
            # Auto-clean commands when expires_at is reached.
            await self._ensure_ttl_index(
                self.device_commands,
                [("expires_at", 1)],
                ttl_seconds=0,
            )

            logger.info("MongoDB indexes created successfully")
        except Exception as exc:
            logger.error("Index creation error: %s", exc)

    # ===== Utility serialization =====

    def _serialize_doc(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Convert ObjectId and datetime fields for API responses."""
        output = dict(doc)
        output["_id"] = str(output.get("_id"))
        for field in (
            "received_at",
            "recorded_at",
            "registered_at",
            "last_seen",
            "created_at",
            "acknowledged_at",
            "expires_at",
            "dispatched_at",
            "completed_at",
        ):
            if isinstance(output.get(field), datetime):
                output[field] = output[field].isoformat()
        output.pop("esp_token_hash", None)
        return output

    # ===== Legacy methods =====

    async def insert_reading(self, doc: Dict[str, Any]) -> bool:
        """Insert a legacy reading into the original collection."""
        if self.collection is None:
            return False
        try:
            await self.collection.insert_one(doc)
            return True
        except Exception as exc:
            logger.error("Insert error: %s", exc)
            return False

    async def get_legacy_readings_by_device(self, device_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Query legacy readings for a specific device."""
        if self.collection is None:
            return []
        try:
            cursor = self.collection.find({"device_id": device_id}).sort("ts", -1).limit(limit)
            return [self._serialize_doc(doc) async for doc in cursor]
        except Exception as exc:
            logger.error("Legacy query error: %s", exc)
            return []

    # ===== Health reading methods =====

    async def insert_health_reading(self, doc: Dict[str, Any]) -> bool:
        """Insert one normalized health reading document."""
        if self.health_readings is None:
            return False

        try:
            doc = dict(doc)
            doc.setdefault("received_at", datetime.utcnow())
            if "recorded_at" not in doc and doc.get("timestamp"):
                doc["recorded_at"] = datetime.utcfromtimestamp(float(doc["timestamp"]))
            await self.health_readings.insert_one(doc)
            return True
        except DuplicateKeyError:
            # Duplicate QoS1 retransmission (same device_id + seq)
            logger.info("Duplicate reading ignored for device=%s seq=%s", doc.get("device_id"), doc.get("seq"))
            return True
        except Exception as exc:
            logger.error("Health reading insert error: %s", exc)
            return False

    async def get_health_readings(
        self,
        user_id: str,
        device_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query health readings for a user."""
        if self.health_readings is None:
            return []

        try:
            query: Dict[str, Any] = {"user_id": user_id}
            if device_id:
                query["$or"] = [{"device_id": device_id}, {"device_uid": device_id}]
            if start_time or end_time:
                query["timestamp"] = {}
                if start_time is not None:
                    query["timestamp"]["$gte"] = float(start_time)
                if end_time is not None:
                    query["timestamp"]["$lte"] = float(end_time)

            cursor = self.health_readings.find(query).sort("timestamp", -1).limit(limit)
            return [self._serialize_doc(doc) async for doc in cursor]
        except Exception as exc:
            logger.error("Health reading query error: %s", exc)
            return []

    async def get_readings_by_device(
        self,
        device_id: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query health readings by device ID/UID."""
        if self.health_readings is None:
            return []
        try:
            query: Dict[str, Any] = {"$or": [{"device_id": device_id}, {"device_uid": device_id}]}
            if start_time or end_time:
                query["timestamp"] = {}
                if start_time is not None:
                    query["timestamp"]["$gte"] = float(start_time)
                if end_time is not None:
                    query["timestamp"]["$lte"] = float(end_time)

            cursor = self.health_readings.find(query).sort("timestamp", -1).limit(limit)
            return [self._serialize_doc(doc) async for doc in cursor]
        except Exception as exc:
            logger.error("Device reading query error: %s", exc)
            return []

    async def get_latest_reading(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get most recent health reading from a device."""
        if self.health_readings is None:
            return None
        try:
            doc = await self.health_readings.find_one(
                {"$or": [{"device_id": device_id}, {"device_uid": device_id}]},
                sort=[("timestamp", -1)],
            )
            return self._serialize_doc(doc) if doc else None
        except Exception as exc:
            logger.error("Latest reading query error: %s", exc)
            return None

    async def get_latest_user_reading(
        self,
        user_id: str,
        device_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get most recent health reading for a user (optionally by device)."""
        if self.health_readings is None:
            return None
        try:
            query: Dict[str, Any] = {"user_id": user_id}
            if device_id:
                query["$or"] = [{"device_id": device_id}, {"device_uid": device_id}]
            doc = await self.health_readings.find_one(query, sort=[("timestamp", -1)])
            return self._serialize_doc(doc) if doc else None
        except Exception as exc:
            logger.error("Latest user reading query error: %s", exc)
            return None

    async def get_ecg_readings(
        self,
        user_id: str,
        quality_filter: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Query ECG readings for a user with optional quality filter."""
        if self.health_readings is None:
            return []
        try:
            query: Dict[str, Any] = {"user_id": user_id, "ecg": {"$exists": True, "$ne": None}}
            if quality_filter:
                query["ecg.quality"] = quality_filter
            cursor = self.health_readings.find(query).sort("timestamp", -1).limit(limit)
            return [self._serialize_doc(doc) async for doc in cursor]
        except Exception as exc:
            logger.error("ECG reading query error: %s", exc)
            return []

    # ===== Alert methods =====

    async def insert_alert(self, doc: Dict[str, Any]) -> Optional[str]:
        """Insert alert and return inserted alert ID."""
        if self.alerts is None:
            return None
        try:
            doc = dict(doc)
            if "recorded_at" not in doc and doc.get("timestamp"):
                doc["recorded_at"] = datetime.utcfromtimestamp(float(doc["timestamp"]))
            result = await self.alerts.insert_one(doc)
            return str(result.inserted_id)
        except Exception as exc:
            logger.error("Alert insert error: %s", exc)
            return None

    async def get_alerts(
        self,
        user_id: str,
        severity: Optional[str] = None,
        acknowledged: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query alert history for a user."""
        if self.alerts is None:
            return []
        try:
            query: Dict[str, Any] = {"user_id": user_id}
            if severity:
                query["severity"] = severity
            if acknowledged is not None:
                query["acknowledged"] = acknowledged
            cursor = self.alerts.find(query).sort("timestamp", -1).limit(limit)
            return [self._serialize_doc(doc) async for doc in cursor]
        except Exception as exc:
            logger.error("Alert query error: %s", exc)
            return []

    async def acknowledge_alert(
        self,
        alert_id: str,
        acknowledged_by: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Mark alert as acknowledged."""
        if self.alerts is None:
            return False
        try:
            from bson import ObjectId

            update = {
                "$set": {
                    "acknowledged": True,
                    "acknowledged_by": acknowledged_by,
                    "acknowledged_at": datetime.utcnow(),
                    "notes": notes,
                }
            }
            result = await self.alerts.update_one({"_id": ObjectId(alert_id)}, update)
            return result.modified_count > 0
        except Exception as exc:
            logger.error("Alert acknowledge error: %s", exc)
            return False

    # ===== Device methods =====

    async def register_device(self, doc: Dict[str, Any]) -> bool:
        """Register or upsert a device."""
        if self.devices is None:
            return False
        try:
            doc = dict(doc)
            now = datetime.utcnow()
            device_id = doc["device_id"]
            doc.setdefault("status", "active")
            doc.setdefault("device_name", device_id)
            doc["last_seen"] = now

            result = await self.devices.update_one(
                {"device_id": device_id},
                {"$set": doc, "$setOnInsert": {"registered_at": now}},
                upsert=True,
            )
            # matched_count>0 with modified_count=0 means idempotent register call.
            return result.modified_count > 0 or result.upserted_id is not None or result.matched_count > 0
        except Exception as exc:
            logger.error("Device registration error: %s", exc)
            return False

    async def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get device by ID."""
        if self.devices is None:
            return None
        try:
            doc = await self.devices.find_one({"device_id": device_id})
            return self._serialize_doc(doc) if doc else None
        except Exception as exc:
            logger.error("Device query error: %s", exc)
            return None

    async def set_device_token_hash(self, device_id: str, token_hash: str) -> bool:
        """Set or rotate one ESP device token hash."""
        if self.devices is None:
            return False
        try:
            result = await self.devices.update_one(
                {"device_id": device_id},
                {"$set": {"esp_token_hash": token_hash, "last_seen": datetime.utcnow()}},
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.error("Set device token hash error: %s", exc)
            return False

    async def get_device_by_token_hash(self, device_id: str, token_hash: str) -> Optional[Dict[str, Any]]:
        """Validate device token hash and return device document."""
        if self.devices is None:
            return None
        try:
            doc = await self.devices.find_one(
                {
                    "device_id": device_id,
                    "esp_token_hash": token_hash,
                    "status": {"$ne": "inactive"},
                }
            )
            return self._serialize_doc(doc) if doc else None
        except Exception as exc:
            logger.error("Device token query error: %s", exc)
            return None

    async def update_device_last_seen(self, device_id: str) -> bool:
        """Update device last_seen timestamp."""
        if self.devices is None:
            return False
        try:
            result = await self.devices.update_one(
                {"device_id": device_id},
                {"$set": {"last_seen": datetime.utcnow()}},
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.error("Device update error: %s", exc)
            return False

    async def update_device_metadata(self, device_id: str, metadata: Dict[str, Any]) -> bool:
        """Update device metadata and last_seen."""
        if self.devices is None:
            return False
        try:
            result = await self.devices.update_one(
                {"device_id": device_id},
                {"$set": {"metadata": metadata, "last_seen": datetime.utcnow()}},
                upsert=True,
            )
            return result.modified_count > 0 or result.upserted_id is not None
        except Exception as exc:
            logger.error("Device metadata update error: %s", exc)
            return False

    # ===== Device command methods =====

    async def enqueue_device_command(self, doc: Dict[str, Any]) -> Optional[str]:
        """Insert one command for ESP polling and return command id."""
        if self.device_commands is None:
            return None
        try:
            payload = dict(doc)
            payload.setdefault("created_at", datetime.utcnow())
            payload.setdefault("status", "pending")
            payload.setdefault("dispatch_count", 0)
            result = await self.device_commands.insert_one(payload)
            return str(result.inserted_id)
        except DuplicateKeyError:
            logger.warning("Duplicate command request_id=%s", doc.get("request_id"))
            existing = await self.device_commands.find_one({"request_id": doc.get("request_id")})
            return str(existing["_id"]) if existing else None
        except Exception as exc:
            logger.error("Enqueue device command error: %s", exc)
            return None

    async def claim_next_device_command(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Claim next pending command for one ESP device."""
        if self.device_commands is None:
            return None
        try:
            now = datetime.utcnow()
            query: Dict[str, Any] = {
                "device_id": device_id,
                "status": "pending",
                "$or": [
                    {"expires_at": {"$exists": False}},
                    {"expires_at": None},
                    {"expires_at": {"$gt": now}},
                ],
            }
            update = {
                "$set": {"status": "dispatched", "dispatched_at": now},
                "$inc": {"dispatch_count": 1},
            }
            doc = await self.device_commands.find_one_and_update(
                query,
                update,
                sort=[("created_at", 1)],
                return_document=ReturnDocument.AFTER,
            )
            return self._serialize_doc(doc) if doc else None
        except Exception as exc:
            logger.error("Claim device command error: %s", exc)
            return None

    async def acknowledge_device_command(
        self,
        device_id: str,
        command_id: str,
        status: str,
        message: Optional[str] = None,
    ) -> bool:
        """Acknowledge one command from ESP device."""
        if self.device_commands is None:
            return False
        try:
            from bson import ObjectId

            update = {
                "$set": {
                    "status": status,
                    "completed_at": datetime.utcnow(),
                    "ack_message": message,
                }
            }
            result = await self.device_commands.update_one(
                {"_id": ObjectId(command_id), "device_id": device_id},
                update,
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.error("Acknowledge device command error: %s", exc)
            return False

    # ===== User methods =====

    async def create_user(self, doc: Dict[str, Any]) -> bool:
        """Create a new user."""
        if self.users is None:
            return False
        try:
            doc = dict(doc)
            doc["created_at"] = datetime.utcnow()
            await self.users.insert_one(doc)
            return True
        except DuplicateKeyError:
            return False
        except Exception as exc:
            logger.error("User creation error: %s", exc)
            return False

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        if self.users is None:
            return None
        try:
            doc = await self.users.find_one({"user_id": user_id})
            return self._serialize_doc(doc) if doc else None
        except Exception as exc:
            logger.error("User query error: %s", exc)
            return None

    async def update_user_thresholds(self, user_id: str, thresholds: Dict[str, Any]) -> bool:
        """Update user alert thresholds."""
        if self.users is None:
            return False
        try:
            result = await self.users.update_one(
                {"user_id": user_id},
                {"$set": {"alert_thresholds": thresholds}},
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.error("User threshold update error: %s", exc)
            return False

    # ===== Utility methods =====

    async def ping(self) -> bool:
        """Check database connectivity."""
        if self.client is None:
            return False
        try:
            await self.client.admin.command("ping")
            return True
        except Exception:
            return False


# Global database instance
db = Database()
