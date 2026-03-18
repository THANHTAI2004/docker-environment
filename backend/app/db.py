"""
MongoDB database operations for health monitoring.
"""
import hashlib
import json
import logging
import secrets
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

import motor.motor_asyncio
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .config import settings
from .observability import (
    DEVICE_COMMAND_COMPLETED_TOTAL,
    DEVICE_COMMAND_DISPATCHED_TOTAL,
    DEVICE_COMMAND_FAILED_TOTAL,
    DEVICE_COMMAND_QUEUE_LATENCY,
    DEVICE_COMMAND_RETRY_TOTAL,
    DEVICE_COMMAND_TIMEOUT_TOTAL,
)

logger = logging.getLogger(__name__)

COMMAND_STATUS_QUEUED = "queued"
COMMAND_STATUS_DISPATCHED = "dispatched"
COMMAND_STATUS_ACKED = "acked"
COMMAND_STATUS_COMPLETED = "completed"
COMMAND_STATUS_FAILED = "failed"
COMMAND_STATUS_EXPIRED = "expired"
COMMAND_STATUS_CANCELLED = "cancelled"

ACTIVE_COMMAND_STATUSES = (COMMAND_STATUS_QUEUED, COMMAND_STATUS_DISPATCHED)


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
        self.audit_logs = None
        self.device_links = None
        self.auth_sessions = None

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
        self.audit_logs = self.db[settings.mongo_audit_collection]
        self.device_links = self.db[settings.mongo_device_links_collection]
        self.auth_sessions = self.db[settings.mongo_auth_sessions_collection]

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
            await self.alerts.create_index([("severity", 1), ("acknowledged", 1)])
            await self.alerts.create_index([("device_id", 1)])
            await self.alerts.create_index([("device_id", 1), ("alert_type", 1), ("timestamp", -1)])
            await self.alerts.create_index([("recorded_at", 1)], expireAfterSeconds=15552000)
            await self.alerts.create_index(
                [("device_id", 1), ("seq", 1), ("alert_type", 1)],
                unique=True,
                partialFilterExpression={"seq": {"$type": "number"}},
            )

            # Devices
            await self.devices.create_index([("device_id", 1)], unique=True)
            await self.devices.create_index([("status", 1)])
            await self.devices.create_index([("owner_user_id", 1)], sparse=True)
            await self.devices.create_index([("esp_token_hash", 1)], unique=True, sparse=True)

            # Users
            await self.users.create_index([("user_id", 1)], unique=True)
            await self.users.create_index([("phone_number", 1)], unique=True, sparse=True)
            await self.users.create_index([("email", 1)], unique=True, sparse=True)
            await self.users.create_index([("role", 1)])

            # Device commands (ESP polling)
            await self.device_commands.create_index([("device_id", 1), ("status", 1), ("created_at", 1)])
            await self.device_commands.create_index([("device_id", 1), ("dedupe_key", 1), ("created_at", -1)])
            await self.device_commands.create_index([("request_id", 1)], unique=True, sparse=True)
            # Auto-clean commands when expires_at is reached.
            await self._ensure_ttl_index(
                self.device_commands,
                [("expires_at", 1)],
                ttl_seconds=0,
            )

            # Audit logs
            await self.audit_logs.create_index([("timestamp", -1)])
            await self.audit_logs.create_index([("actor_id", 1), ("timestamp", -1)])
            await self.audit_logs.create_index([("action", 1), ("timestamp", -1)])
            await self.audit_logs.create_index([("target_id", 1), ("timestamp", -1)])

            # User-device links
            await self.device_links.create_index([("device_id", 1), ("user_id", 1)], unique=True)
            await self.device_links.create_index([("user_id", 1), ("is_active", 1), ("created_at", -1)])
            await self.device_links.create_index([("device_id", 1), ("is_active", 1), ("created_at", -1)])
            await self.device_links.create_index([("device_id", 1), ("permission", 1), ("is_active", 1)])
            await self._normalize_existing_device_links()

            # Auth sessions
            await self.auth_sessions.create_index([("session_id", 1)], unique=True)
            await self.auth_sessions.create_index([("user_id", 1), ("created_at", -1)])
            await self.auth_sessions.create_index([("refresh_token_hash", 1)], unique=True, sparse=True)
            await self._ensure_ttl_index(
                self.auth_sessions,
                [("expires_at", 1)],
                ttl_seconds=0,
            )

            logger.info("MongoDB indexes created successfully")
        except Exception as exc:
            logger.error("Index creation error: %s", exc)
            raise

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
            "acked_at",
            "expires_at",
            "dispatched_at",
            "last_dispatched_at",
            "completed_at",
            "linked_at",
            "updated_at",
            "last_refreshed_at",
            "revoked_at",
            "next_retry_at",
        ):
            if isinstance(output.get(field), datetime):
                output[field] = output[field].isoformat()
        if isinstance(output.get("date_of_birth"), date):
            output["date_of_birth"] = output["date_of_birth"].isoformat()
        output.pop("esp_token_hash", None)
        output.pop("password_hash", None)
        return output

    def _normalize_device_permission(self, permission: Optional[str]) -> Optional[str]:
        """Map legacy permission aliases to the canonical owner/viewer model."""
        if permission == "caregiver":
            return "viewer"
        return permission

    def _normalize_link_role(self, link_role: Optional[str]) -> Optional[str]:
        """Backward-compatible alias for permission normalization."""
        return self._normalize_device_permission(link_role)

    def _normalize_device_link(self, doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Normalize one serialized device-link document."""
        if not doc:
            return None
        normalized = dict(doc)
        permission = self._normalize_device_permission(
            normalized.get("permission") or normalized.get("link_role")
        )
        created_at = normalized.get("created_at") or normalized.get("linked_at")
        added_by_user_id = normalized.get("added_by_user_id") or normalized.get("linked_by")
        revoked_at = normalized.get("revoked_at")
        is_active = normalized.get("is_active")
        if is_active is None:
            is_active = revoked_at is None

        normalized["permission"] = permission
        normalized["added_by_user_id"] = added_by_user_id
        normalized["created_at"] = created_at
        normalized["revoked_at"] = revoked_at
        normalized["is_active"] = bool(is_active)

        # Legacy aliases kept temporarily for older clients/tests.
        normalized["link_role"] = permission
        normalized["linked_by"] = added_by_user_id
        normalized["linked_at"] = created_at
        return normalized

    def _expand_permissions(self, permissions: Optional[List[str]]) -> Optional[List[str]]:
        """Expand canonical permission filters so legacy viewer aliases still match."""
        if not permissions:
            return None

        expanded: List[str] = []
        for permission in permissions:
            normalized = self._normalize_device_permission(permission)
            if normalized == "viewer":
                expanded.extend(["viewer", "caregiver"])
            elif normalized:
                expanded.append(normalized)

        deduped: List[str] = []
        for permission in expanded:
            if permission not in deduped:
                deduped.append(permission)
        return deduped

    def _device_link_sort_key(self, item: Dict[str, Any]) -> tuple[int, str]:
        """Sort owner permissions before viewer permissions, then by creation time."""
        permission = item.get("permission") or item.get("link_role")
        return (0 if permission == "owner" else 1, item.get("created_at") or item.get("linked_at") or "")

    def _active_device_link_filter(self) -> Dict[str, Any]:
        """Match currently active device links across new and legacy records."""
        return {
            "$or": [
                {"is_active": True},
                {
                    "$and": [
                        {"is_active": {"$exists": False}},
                        {
                            "$or": [
                                {"revoked_at": {"$exists": False}},
                                {"revoked_at": None},
                            ]
                        },
                    ]
                },
            ]
        }

    def _active_device_link_query(self, query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Combine a device-link query with the active-link predicate."""
        active_filter = self._active_device_link_filter()
        if not query:
            return active_filter
        return {"$and": [query, active_filter]}

    async def _normalize_existing_device_links(self) -> None:
        """Backfill canonical permission fields on existing device-link documents."""
        if self.device_links is None:
            return

        normalized_count = 0
        async for doc in self.device_links.find({}):
            updates: Dict[str, Any] = {}
            permission = self._normalize_device_permission(doc.get("permission") or doc.get("link_role"))
            created_at = doc.get("created_at") or doc.get("linked_at")
            added_by_user_id = doc.get("added_by_user_id") or doc.get("linked_by")
            is_active = doc.get("is_active")
            if is_active is None:
                is_active = doc.get("revoked_at") is None

            if permission and doc.get("permission") != permission:
                updates["permission"] = permission
            if permission and doc.get("link_role") != permission:
                updates["link_role"] = permission
            if created_at is not None and doc.get("created_at") != created_at:
                updates["created_at"] = created_at
            if created_at is not None and doc.get("linked_at") != created_at:
                updates["linked_at"] = created_at
            if added_by_user_id is not None and doc.get("added_by_user_id") != added_by_user_id:
                updates["added_by_user_id"] = added_by_user_id
            if added_by_user_id is not None and doc.get("linked_by") != added_by_user_id:
                updates["linked_by"] = added_by_user_id
            if doc.get("is_active") != bool(is_active):
                updates["is_active"] = bool(is_active)

            if updates:
                await self.device_links.update_one({"_id": doc["_id"]}, {"$set": updates})
                normalized_count += 1

        if normalized_count > 0:
            logger.info("Normalized %s device-link documents to canonical permission fields", normalized_count)

        device_ids = await self.device_links.distinct("device_id")
        for device_id in device_ids:
            await self._sync_device_owner_cache(device_id)

    async def _sync_device_owner_cache(self, device_id: str) -> None:
        """Cache the active owner user ID on the device document for fast lookups."""
        if self.devices is None:
            return

        owner_link = await self.get_device_owner_link(device_id)
        if owner_link and owner_link.get("user_id"):
            await self.devices.update_one(
                {"device_id": device_id},
                {"$set": {"owner_user_id": owner_link["user_id"]}},
            )
            return

        await self.devices.update_one(
            {"device_id": device_id},
            {"$unset": {"owner_user_id": ""}},
        )

    def _make_command_dedupe_key(self, payload: Dict[str, Any]) -> str:
        """Create a stable dedupe key for logically identical commands."""
        fingerprint = json.dumps(
            {
                "device_id": payload.get("device_id"),
                "command": payload.get("command"),
                "payload": payload.get("payload", {}),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()

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

    async def insert_health_reading(self, doc: Dict[str, Any]) -> Literal["inserted", "duplicate", "error"]:
        """Insert one normalized health reading document."""
        if self.health_readings is None:
            return "error"

        try:
            doc = dict(doc)
            doc.setdefault("received_at", datetime.utcnow())
            if "recorded_at" not in doc and doc.get("timestamp"):
                doc["recorded_at"] = datetime.utcfromtimestamp(float(doc["timestamp"]))
            await self.health_readings.insert_one(doc)
            return "inserted"
        except DuplicateKeyError:
            # Duplicate QoS1 retransmission (same device_id + seq)
            logger.info("Duplicate reading ignored for device=%s seq=%s", doc.get("device_id"), doc.get("seq"))
            return "duplicate"
        except Exception as exc:
            logger.error("Health reading insert error: %s", exc)
            return "error"

    async def get_health_readings(
        self,
        user_id: str,
        device_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Legacy user-based query kept for backward compatibility."""
        if self.health_readings is None:
            return []

        try:
            accessible_device_ids = await self.get_device_ids_for_user(user_id, permissions=["owner", "viewer"])
            if device_id:
                if device_id not in accessible_device_ids:
                    return []
                target_device_ids = [device_id]
            else:
                target_device_ids = accessible_device_ids
            if not target_device_ids:
                return []
            query: Dict[str, Any] = {
                "$or": [
                    {"device_id": {"$in": target_device_ids}},
                    {"device_uid": {"$in": target_device_ids}},
                ]
            }
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

    async def get_device_ecg_readings(
        self,
        device_id: str,
        quality_filter: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Query ECG readings for one device."""
        if self.health_readings is None:
            return []
        try:
            query: Dict[str, Any] = {
                "$or": [{"device_id": device_id}, {"device_uid": device_id}],
                "ecg": {"$exists": True, "$ne": None},
            }
            if quality_filter:
                query["ecg.quality"] = quality_filter
            cursor = self.health_readings.find(query).sort("timestamp", -1).limit(limit)
            return [self._serialize_doc(doc) async for doc in cursor]
        except Exception as exc:
            logger.error("Device ECG query error: %s", exc)
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
            accessible_device_ids = await self.get_device_ids_for_user(user_id, permissions=["owner", "viewer"])
            if device_id:
                if device_id not in accessible_device_ids:
                    return None
                target_device_ids = [device_id]
            else:
                target_device_ids = accessible_device_ids
            if not target_device_ids:
                return None
            query: Dict[str, Any] = {
                "$or": [
                    {"device_id": {"$in": target_device_ids}},
                    {"device_uid": {"$in": target_device_ids}},
                ]
            }
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
            accessible_device_ids = await self.get_device_ids_for_user(user_id, permissions=["owner", "viewer"])
            if not accessible_device_ids:
                return []
            query: Dict[str, Any] = {
                "$or": [
                    {"device_id": {"$in": accessible_device_ids}},
                    {"device_uid": {"$in": accessible_device_ids}},
                ],
                "ecg": {"$exists": True, "$ne": None},
            }
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
            if doc.get("seq") is None and doc.get("timestamp") is not None:
                window = settings.alert_dedupe_window_seconds
                existing = await self.alerts.find_one(
                    {
                        "device_id": doc.get("device_id"),
                        "alert_type": doc.get("alert_type"),
                        "timestamp": {
                            "$gte": float(doc["timestamp"]) - window,
                            "$lte": float(doc["timestamp"]) + window,
                        },
                    }
                )
                if existing:
                    logger.info(
                        "Soft-duplicate alert ignored for device=%s type=%s window=%ss",
                        doc.get("device_id"),
                        doc.get("alert_type"),
                        window,
                    )
                    return None
            result = await self.alerts.insert_one(doc)
            return str(result.inserted_id)
        except DuplicateKeyError:
            logger.info(
                "Duplicate alert ignored for device=%s seq=%s type=%s",
                doc.get("device_id"),
                doc.get("seq"),
                doc.get("alert_type"),
            )
            return None
        except Exception as exc:
            logger.error("Alert insert error: %s", exc)
            return None

    async def get_alert(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one alert by ID."""
        if self.alerts is None:
            return None
        try:
            from bson import ObjectId

            doc = await self.alerts.find_one({"_id": ObjectId(alert_id)})
            return self._serialize_doc(doc) if doc else None
        except Exception as exc:
            logger.error("Alert get error: %s", exc)
            return None

    async def get_alerts(
        self,
        user_id: str,
        severity: Optional[str] = None,
        acknowledged: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Legacy user-based alert query kept for backward compatibility."""
        if self.alerts is None:
            return []
        try:
            accessible_device_ids = await self.get_device_ids_for_user(user_id, permissions=["owner", "viewer"])
            query: Dict[str, Any] = {
                "$or": [
                    {"recipient_user_ids": user_id},
                    {"device_id": {"$in": accessible_device_ids}},
                ]
            }
            if severity:
                query["severity"] = severity
            if acknowledged is not None:
                query["acknowledged"] = acknowledged
            cursor = self.alerts.find(query).sort("timestamp", -1).limit(limit)
            return [self._serialize_doc(doc) async for doc in cursor]
        except Exception as exc:
            logger.error("Alert query error: %s", exc)
            return []

    async def get_alerts_by_device(
        self,
        device_id: str,
        severity: Optional[str] = None,
        acknowledged: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query alert history for one device."""
        if self.alerts is None:
            return []
        try:
            query: Dict[str, Any] = {"device_id": device_id}
            if severity:
                query["severity"] = severity
            if acknowledged is not None:
                query["acknowledged"] = acknowledged
            cursor = self.alerts.find(query).sort("timestamp", -1).limit(limit)
            return [self._serialize_doc(doc) async for doc in cursor]
        except Exception as exc:
            logger.error("Device alert query error: %s", exc)
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
            if doc.get("settings") is None and doc.get("alert_thresholds") is not None:
                doc["settings"] = {"alert_thresholds": doc["alert_thresholds"]}
            elif isinstance(doc.get("settings"), dict) and doc.get("alert_thresholds") is None:
                alert_thresholds = doc["settings"].get("alert_thresholds")
                if alert_thresholds is not None:
                    doc["alert_thresholds"] = alert_thresholds
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

    async def get_device_command(self, command_id: str, device_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch one device command by ID."""
        if self.device_commands is None:
            return None
        try:
            from bson import ObjectId

            query: Dict[str, Any] = {"_id": ObjectId(command_id)}
            if device_id:
                query["device_id"] = device_id
            doc = await self.device_commands.find_one(query)
            return self._serialize_doc(doc) if doc else None
        except Exception as exc:
            logger.error("Device command get error: %s", exc)
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

    async def update_device_thresholds(self, device_id: str, thresholds: Dict[str, Any]) -> bool:
        """Update alert thresholds stored directly on a device."""
        if self.devices is None:
            return False
        try:
            result = await self.devices.update_one(
                {"device_id": device_id},
                {
                    "$set": {
                        "settings.alert_thresholds": thresholds,
                        "alert_thresholds": thresholds,
                        "last_seen": datetime.utcnow(),
                    }
                },
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.error("Device threshold update error: %s", exc)
            return False

    # ===== Device link methods =====

    async def get_device_link(self, device_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Return one user-device link."""
        if self.device_links is None:
            return None
        try:
            doc = await self.device_links.find_one(
                self._active_device_link_query({"device_id": device_id, "user_id": user_id})
            )
            return self._normalize_device_link(self._serialize_doc(doc)) if doc else None
        except Exception as exc:
            logger.error("Device link query error: %s", exc)
            return None

    async def get_device_owner_link(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Return the owner link for one device, if any."""
        if self.device_links is None:
            return None
        try:
            doc = await self.device_links.find_one(
                self._active_device_link_query(
                    {
                        "device_id": device_id,
                        "$or": [
                            {"permission": {"$in": self._expand_permissions(["owner"]) or ["owner"]}},
                            {"link_role": {"$in": self._expand_permissions(["owner"]) or ["owner"]}},
                        ],
                    }
                )
            )
            return self._normalize_device_link(self._serialize_doc(doc)) if doc else None
        except Exception as exc:
            logger.error("Device owner link query error: %s", exc)
            return None

    async def list_device_links(self, device_id: str) -> List[Dict[str, Any]]:
        """Return all links for one device."""
        if self.device_links is None:
            return []
        try:
            links = [
                self._normalize_device_link(self._serialize_doc(doc))
                async for doc in self.device_links.find(
                    self._active_device_link_query({"device_id": device_id})
                )
            ]
            links.sort(key=self._device_link_sort_key)
            return links
        except Exception as exc:
            logger.error("Device links query error: %s", exc)
            return []

    async def get_device_link_by_role(
        self,
        device_id: str,
        user_id: str,
        link_role: str,
    ) -> Optional[Dict[str, Any]]:
        """Return one user-device link with the expected link role."""
        if self.device_links is None:
            return None
        try:
            expanded_roles = self._expand_permissions([link_role]) or [link_role]
            doc = await self.device_links.find_one(
                self._active_device_link_query(
                    {
                        "device_id": device_id,
                        "user_id": user_id,
                        "$or": [
                            {"permission": {"$in": expanded_roles}},
                            {"link_role": {"$in": expanded_roles}},
                        ],
                    }
                )
            )
            return self._normalize_device_link(self._serialize_doc(doc)) if doc else None
        except Exception as exc:
            logger.error("Device link role query error: %s", exc)
            return None

    async def list_device_links_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """Return all device links for one user."""
        if self.device_links is None:
            return []
        try:
            return [
                self._normalize_device_link(self._serialize_doc(doc))
                async for doc in self.device_links.find(
                    self._active_device_link_query({"user_id": user_id})
                )
            ]
        except Exception as exc:
            logger.error("User device links query error: %s", exc)
            return []

    async def get_device_ids_for_user(
        self,
        user_id: str,
        permissions: Optional[List[str]] = None,
    ) -> List[str]:
        """Return linked device IDs for one user, optionally filtered by permission."""
        if self.device_links is None:
            return []
        try:
            query: Dict[str, Any] = {"user_id": user_id}
            expanded_roles = self._expand_permissions(permissions)
            if expanded_roles:
                query["$or"] = [
                    {"permission": {"$in": expanded_roles}},
                    {"link_role": {"$in": expanded_roles}},
                ]
            links = [doc async for doc in self.device_links.find(self._active_device_link_query(query))]
            return [doc["device_id"] for doc in links if doc.get("device_id")]
        except Exception as exc:
            logger.error("Device IDs for user query error: %s", exc)
            return []

    async def users_share_device_access(self, actor_user_id: str, target_user_id: str) -> bool:
        """Return True when two users are linked to at least one common device."""
        actor_device_ids = set(await self.get_device_ids_for_user(actor_user_id))
        if not actor_device_ids:
            return False
        target_device_ids = set(await self.get_device_ids_for_user(target_user_id))
        return bool(actor_device_ids.intersection(target_device_ids))

    async def get_alert_recipient_user_ids(self, device_id: str) -> List[str]:
        """Return owner + viewer user IDs for one device."""
        links = await self.list_device_links(device_id)
        return [
            link["user_id"]
            for link in links
            if link.get("permission") in {"owner", "viewer"} and link.get("user_id")
        ]

    async def upsert_device_link(
        self,
        device_id: str,
        user_id: str,
        permission: str,
        added_by_user_id: Optional[str],
    ) -> str:
        """Create or update one user-device link."""
        if self.device_links is None:
            return "error"
        try:
            now = datetime.utcnow()
            permission = self._normalize_device_permission(permission) or permission
            existing = await self.device_links.find_one({"device_id": device_id, "user_id": user_id})
            if existing:
                await self.device_links.update_one(
                    {"_id": existing["_id"]},
                    {
                        "$set": {
                            "permission": permission,
                            "link_role": permission,
                            "added_by_user_id": added_by_user_id,
                            "linked_by": added_by_user_id,
                            "created_at": existing.get("created_at") or existing.get("linked_at") or now,
                            "linked_at": existing.get("created_at") or existing.get("linked_at") or now,
                            "is_active": True,
                            "revoked_at": None,
                            "updated_at": now,
                        }
                    },
                )
                await self._sync_device_owner_cache(device_id)
                return "updated"

            await self.device_links.insert_one(
                {
                    "device_id": device_id,
                    "user_id": user_id,
                    "permission": permission,
                    "link_role": permission,
                    "created_at": now,
                    "linked_at": now,
                    "added_by_user_id": added_by_user_id,
                    "linked_by": added_by_user_id,
                    "is_active": True,
                    "revoked_at": None,
                    "updated_at": now,
                }
            )
            await self._sync_device_owner_cache(device_id)
            return "linked"
        except DuplicateKeyError:
            return "updated"
        except Exception as exc:
            logger.error("Device link upsert error: %s", exc)
            return "error"

    async def delete_device_link(self, device_id: str, user_id: str) -> bool:
        """Soft-revoke one user-device link."""
        if self.device_links is None:
            return False
        try:
            existing = await self.get_device_link(device_id, user_id)
            result = await self.device_links.update_one(
                self._active_device_link_query({"device_id": device_id, "user_id": user_id}),
                {
                    "$set": {
                        "is_active": False,
                        "revoked_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            if result.modified_count > 0:
                await self._sync_device_owner_cache(device_id)
            return result.modified_count > 0
        except Exception as exc:
            logger.error("Device link delete error: %s", exc)
            return False

    async def list_devices_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """List devices linked to one user with link metadata."""
        if self.device_links is None or self.devices is None or self.users is None:
            return []
        try:
            links = [
                self._normalize_device_link(self._serialize_doc(doc))
                async for doc in self.device_links.find(
                    self._active_device_link_query({"user_id": user_id})
                ).sort("created_at", -1)
            ]
            if not links:
                return []

            device_ids = [link["device_id"] for link in links]
            devices = {
                doc["device_id"]: self._serialize_doc(doc)
                async for doc in self.devices.find({"device_id": {"$in": device_ids}})
            }
            device_links = [
                self._normalize_device_link(self._serialize_doc(doc))
                async for doc in self.device_links.find(
                    self._active_device_link_query({"device_id": {"$in": device_ids}})
                ).sort(
                    [("permission", 1), ("created_at", 1)]
                )
            ]
            linked_user_ids = list({link["user_id"] for link in device_links})
            users = {
                doc["user_id"]: self._serialize_doc(doc)
                async for doc in self.users.find({"user_id": {"$in": linked_user_ids}})
            }
            linked_users_by_device: Dict[str, List[Dict[str, Any]]] = {}
            for device_link in device_links:
                linked_user = users.get(device_link["user_id"])
                if not linked_user:
                    continue
                linked_users_by_device.setdefault(device_link["device_id"], []).append(
                    {
                        "user_id": linked_user.get("user_id"),
                        "name": linked_user.get("name"),
                        "phone_number": linked_user.get("phone_number") or linked_user.get("phone"),
                        "permission": device_link.get("permission"),
                        "link_role": device_link.get("permission"),
                    }
                )
            for linked_items in linked_users_by_device.values():
                linked_items.sort(
                    key=lambda item: (0 if item.get("permission") == "owner" else 1, item.get("user_id") or "")
                )

            results: List[Dict[str, Any]] = []
            for link in links:
                device = devices.get(link["device_id"])
                if not device:
                    continue
                results.append(
                    {
                        "device_id": device.get("device_id"),
                        "device_type": device.get("device_type"),
                        "device_name": device.get("device_name"),
                        "firmware_version": device.get("firmware_version"),
                        "registered_at": device.get("registered_at"),
                        "last_seen": device.get("last_seen"),
                        "status": device.get("status"),
                        "owner_user_id": device.get("owner_user_id"),
                        "permission": link.get("permission"),
                        "link_role": link.get("permission"),
                        "created_at": link.get("created_at"),
                        "linked_at": link.get("created_at"),
                        "added_by_user_id": link.get("added_by_user_id"),
                        "linked_by": link.get("added_by_user_id"),
                        "is_active": link.get("is_active"),
                        "settings": device.get("settings") or (
                            {"alert_thresholds": device.get("alert_thresholds")}
                            if device.get("alert_thresholds")
                            else None
                        ),
                        "linked_users": linked_users_by_device.get(link["device_id"], []),
                    }
                )
            return results
        except Exception as exc:
            logger.error("List devices for user error: %s", exc)
            return []

    async def list_users_for_device(self, device_id: str) -> List[Dict[str, Any]]:
        """List users linked to one device with link metadata."""
        if self.device_links is None or self.users is None:
            return []
        try:
            links = [
                self._normalize_device_link(self._serialize_doc(doc))
                async for doc in self.device_links.find(
                    self._active_device_link_query({"device_id": device_id})
                ).sort(
                    [("permission", 1), ("created_at", 1)]
                )
            ]
            if not links:
                return []

            user_ids = [link["user_id"] for link in links]
            users = {
                doc["user_id"]: self._serialize_doc(doc)
                async for doc in self.users.find({"user_id": {"$in": user_ids}})
            }

            results: List[Dict[str, Any]] = []
            for link in links:
                user = users.get(link["user_id"])
                if not user:
                    continue
                results.append(
                    {
                        "user_id": user.get("user_id"),
                        "name": user.get("name"),
                        "phone_number": user.get("phone_number") or user.get("phone"),
                        "permission": link.get("permission"),
                        "link_role": link.get("permission"),
                        "created_at": link.get("created_at"),
                        "linked_at": link.get("created_at"),
                        "added_by_user_id": link.get("added_by_user_id"),
                        "linked_by": link.get("added_by_user_id"),
                        "is_active": link.get("is_active"),
                    }
                )
            results.sort(key=lambda item: (0 if item.get("permission") == "owner" else 1, item.get("created_at") or ""))
            return results
        except Exception as exc:
            logger.error("List users for device error: %s", exc)
            return []

    # ===== Device command methods =====

    async def enqueue_device_command(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Insert one command for ESP polling with dedupe and pending limits."""
        if self.device_commands is None:
            return {"status": "error"}
        try:
            now = datetime.utcnow()
            payload = dict(doc)
            payload.setdefault("created_at", now)
            payload.setdefault("status", COMMAND_STATUS_QUEUED)
            payload.setdefault("dispatch_count", 0)
            payload.setdefault("next_retry_at", now)
            payload["dedupe_key"] = self._make_command_dedupe_key(payload)

            pending_filter = {
                "device_id": payload["device_id"],
                "status": {"$in": list(ACTIVE_COMMAND_STATUSES)},
            }
            pending_count = await self.device_commands.count_documents(pending_filter)
            if pending_count >= settings.command_max_pending_per_device:
                return {"status": "limit_reached", "pending_count": pending_count}

            duplicate = await self.device_commands.find_one(
                {
                    "device_id": payload["device_id"],
                    "dedupe_key": payload["dedupe_key"],
                    "status": {"$in": list(ACTIVE_COMMAND_STATUSES)},
                    "created_at": {
                        "$gte": now - timedelta(seconds=settings.command_dedupe_window_seconds),
                    },
                },
                sort=[("created_at", -1)],
            )
            if duplicate:
                return {
                    "status": "duplicate",
                    "command_id": str(duplicate["_id"]),
                    "request_id": duplicate.get("request_id"),
                    "expires_at": duplicate.get("expires_at"),
                }

            result = await self.device_commands.insert_one(payload)
            return {
                "status": "queued",
                "command_id": str(result.inserted_id),
                "request_id": payload.get("request_id"),
                "expires_at": payload.get("expires_at"),
            }
        except DuplicateKeyError:
            logger.warning("Duplicate command request_id=%s", doc.get("request_id"))
            existing = await self.device_commands.find_one({"request_id": doc.get("request_id")})
            if existing:
                return {
                    "status": "duplicate",
                    "command_id": str(existing["_id"]),
                    "request_id": existing.get("request_id"),
                    "expires_at": existing.get("expires_at"),
                }
            return {"status": "error"}
        except Exception as exc:
            logger.error("Enqueue device command error: %s", exc)
            return {"status": "error"}

    async def claim_next_device_command(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Claim next pending command for one ESP device."""
        if self.device_commands is None:
            return None
        try:
            now = datetime.utcnow()
            query: Dict[str, Any] = {
                "device_id": device_id,
                "status": COMMAND_STATUS_QUEUED,
                "$or": [
                    {"expires_at": {"$exists": False}},
                    {"expires_at": None},
                    {"expires_at": {"$gt": now}},
                ],
                "$and": [
                    {
                        "$or": [
                            {"next_retry_at": {"$exists": False}},
                            {"next_retry_at": None},
                            {"next_retry_at": {"$lte": now}},
                        ]
                    }
                ],
            }
            update = {
                "$set": {
                    "status": COMMAND_STATUS_DISPATCHED,
                    "dispatched_at": now,
                    "last_dispatched_at": now,
                    "last_error": None,
                    "failure_reason": None,
                },
                "$inc": {"dispatch_count": 1},
            }
            doc = await self.device_commands.find_one_and_update(
                query,
                update,
                sort=[("created_at", 1)],
                return_document=ReturnDocument.AFTER,
            )
            if doc:
                command_name = doc.get("command", "unknown")
                created_at = doc.get("created_at")
                if isinstance(created_at, datetime):
                    latency = max((now - created_at).total_seconds(), 0.0)
                    DEVICE_COMMAND_QUEUE_LATENCY.labels(command=command_name).observe(latency)
                DEVICE_COMMAND_DISPATCHED_TOTAL.labels(command=command_name).inc()
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

            normalized_status = COMMAND_STATUS_ACKED if status == "done" else COMMAND_STATUS_FAILED
            now = datetime.utcnow()
            update_fields: Dict[str, Any] = {
                "status": normalized_status,
                "ack_message": message,
                "acked_at": now,
            }
            if normalized_status == COMMAND_STATUS_FAILED:
                update_fields["completed_at"] = now
                update_fields["failure_reason"] = message or "device reported failure"
                update_fields["last_error"] = message or "device reported failure"

            update = {
                "$set": update_fields
            }
            current = await self.device_commands.find_one({"_id": ObjectId(command_id), "device_id": device_id})
            command_name = current.get("command", "unknown") if current else "unknown"
            result = await self.device_commands.update_one(
                {
                    "_id": ObjectId(command_id),
                    "device_id": device_id,
                    "status": COMMAND_STATUS_DISPATCHED,
                },
                update,
            )
            if result.modified_count > 0 and normalized_status == COMMAND_STATUS_FAILED:
                DEVICE_COMMAND_FAILED_TOTAL.labels(
                    command=command_name,
                    reason="device_failed",
                ).inc()
            return result.modified_count > 0
        except Exception as exc:
            logger.error("Acknowledge device command error: %s", exc)
            return False

    async def cancel_device_command(self, device_id: str, command_id: str, reason: str) -> bool:
        """Cancel a queued or dispatched device command."""
        if self.device_commands is None:
            return False
        try:
            from bson import ObjectId

            result = await self.device_commands.update_one(
                {
                    "_id": ObjectId(command_id),
                    "device_id": device_id,
                    "status": {"$in": [COMMAND_STATUS_QUEUED, COMMAND_STATUS_DISPATCHED]},
                },
                {
                    "$set": {
                        "status": COMMAND_STATUS_CANCELLED,
                        "completed_at": datetime.utcnow(),
                        "ack_message": reason,
                        "failure_reason": reason,
                        "last_error": reason,
                    }
                },
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.error("Cancel device command error: %s", exc)
            return False

    async def recover_stale_device_commands(self) -> Dict[str, int]:
        """Recover stale command states and finalize terminal transitions."""
        if self.device_commands is None:
            return {"completed": 0, "requeued": 0, "failed": 0, "expired": 0}

        summary = {"completed": 0, "requeued": 0, "failed": 0, "expired": 0}
        now = datetime.utcnow()
        retry_after = now + timedelta(seconds=max(0, settings.command_retry_delay_seconds))
        retry_before = now - timedelta(seconds=settings.command_ack_timeout_seconds)

        try:
            acked_cursor = self.device_commands.find({"status": COMMAND_STATUS_ACKED})
            async for doc in acked_cursor:
                updated = await self.device_commands.update_one(
                    {"_id": doc["_id"], "status": COMMAND_STATUS_ACKED},
                    {
                        "$set": {
                            "status": COMMAND_STATUS_COMPLETED,
                            "completed_at": now,
                        }
                    },
                )
                if updated.modified_count > 0:
                    summary["completed"] += 1
                    DEVICE_COMMAND_COMPLETED_TOTAL.labels(
                        command=doc.get("command", "unknown"),
                    ).inc()

            expirable_cursor = self.device_commands.find(
                {
                    "status": {"$in": [COMMAND_STATUS_QUEUED, COMMAND_STATUS_DISPATCHED]},
                    "expires_at": {"$lte": now},
                }
            )
            async for doc in expirable_cursor:
                reason = "command ttl expired"
                updated = await self.device_commands.update_one(
                    {
                        "_id": doc["_id"],
                        "status": {"$in": [COMMAND_STATUS_QUEUED, COMMAND_STATUS_DISPATCHED]},
                    },
                    {
                        "$set": {
                            "status": COMMAND_STATUS_EXPIRED,
                            "completed_at": now,
                            "failure_reason": reason,
                            "last_error": reason,
                        }
                    },
                )
                if updated.modified_count > 0:
                    summary["expired"] += 1
                    DEVICE_COMMAND_FAILED_TOTAL.labels(
                        command=doc.get("command", "unknown"),
                        reason="expired",
                    ).inc()

            timed_out_cursor = self.device_commands.find(
                {
                    "status": COMMAND_STATUS_DISPATCHED,
                    "$or": [
                        {"expires_at": {"$exists": False}},
                        {"expires_at": None},
                        {"expires_at": {"$gt": now}},
                    ],
                    "dispatched_at": {"$lte": retry_before},
                }
            )
            async for doc in timed_out_cursor:
                command_name = doc.get("command", "unknown")
                DEVICE_COMMAND_TIMEOUT_TOTAL.labels(command=command_name).inc()
                if int(doc.get("dispatch_count", 0)) < settings.command_max_dispatch_count:
                    updated = await self.device_commands.update_one(
                        {"_id": doc["_id"], "status": COMMAND_STATUS_DISPATCHED},
                        {
                            "$set": {
                                "status": COMMAND_STATUS_QUEUED,
                                "next_retry_at": retry_after,
                                "last_error": "Command ACK timeout",
                                "failure_reason": None,
                            }
                        },
                    )
                    if updated.modified_count > 0:
                        summary["requeued"] += 1
                        DEVICE_COMMAND_RETRY_TOTAL.labels(command=command_name).inc()
                else:
                    reason = "ack timeout exceeded"
                    updated = await self.device_commands.update_one(
                        {"_id": doc["_id"], "status": COMMAND_STATUS_DISPATCHED},
                        {
                            "$set": {
                                "status": COMMAND_STATUS_FAILED,
                                "completed_at": now,
                                "failure_reason": reason,
                                "last_error": reason,
                            }
                        },
                    )
                    if updated.modified_count > 0:
                        summary["failed"] += 1
                        DEVICE_COMMAND_FAILED_TOTAL.labels(
                            command=command_name,
                            reason="ack_timeout_exceeded",
                        ).inc()
            return summary
        except Exception as exc:
            logger.error("Recover stale device commands error: %s", exc)
            return summary

    async def count_commands_by_status(self) -> Dict[str, int]:
        """Return current command counts grouped by status."""
        if self.device_commands is None:
            return {}
        try:
            pipeline = [
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            ]
            results = await self.device_commands.aggregate(pipeline).to_list(length=None)
            return {item["_id"] or "unknown": int(item["count"]) for item in results}
        except Exception as exc:
            logger.error("Count commands by status error: %s", exc)
            return {}

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

    async def get_user_auth(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get raw user document including auth fields."""
        if self.users is None:
            return None
        try:
            doc = await self.users.find_one({"user_id": user_id})
            if not doc:
                return None
            doc["_id"] = str(doc.get("_id"))
            return doc
        except Exception as exc:
            logger.error("User auth query error: %s", exc)
            return None

    async def get_user_auth_by_phone(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """Get raw user document by normalized phone number including auth fields."""
        if self.users is None:
            return None
        try:
            doc = await self.users.find_one({"phone_number": phone_number})
            if not doc:
                return None
            doc["_id"] = str(doc.get("_id"))
            return doc
        except Exception as exc:
            logger.error("User auth phone query error: %s", exc)
            return None

    async def phone_exists(self, phone_number: str) -> bool:
        """Return True when a normalized phone number is already registered."""
        if self.users is None:
            return False
        try:
            user = await self.users.find_one({"phone_number": phone_number}, {"_id": 1})
            return user is not None
        except Exception as exc:
            logger.error("Phone exists query error: %s", exc)
            return False

    async def generate_user_id(self) -> str:
        """Generate a collision-resistant internal user ID."""
        if self.users is None:
            return f"user-{secrets.token_hex(4)}"

        for _ in range(5):
            candidate = f"user-{secrets.token_hex(4)}"
            existing = await self.users.find_one({"user_id": candidate}, {"_id": 1})
            if existing is None:
                return candidate
        return f"user-{secrets.token_hex(8)}"

    async def create_user_with_phone(self, data: Dict[str, Any]) -> bool:
        """Create a new user account with phone-number authentication fields."""
        if self.users is None:
            return False
        try:
            payload = dict(data)
            payload.setdefault("created_at", datetime.utcnow())
            await self.users.insert_one(payload)
            return True
        except DuplicateKeyError:
            return False
        except Exception as exc:
            logger.error("Phone user creation error: %s", exc)
            return False

    async def update_user_thresholds(self, user_id: str, thresholds: Dict[str, Any]) -> bool:
        """Update user alert thresholds."""
        if self.users is None:
            return False
        try:
            result = await self.users.update_one(
                {"user_id": user_id},
                {"$set": {"alert_thresholds": thresholds}},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.error("User threshold update error: %s", exc)
            return False

    async def insert_audit_log(self, doc: Dict[str, Any]) -> bool:
        """Persist one audit log record."""
        if self.audit_logs is None:
            return False
        try:
            payload = dict(doc)
            payload.setdefault("timestamp", datetime.utcnow())
            await self.audit_logs.insert_one(payload)
            return True
        except Exception as exc:
            logger.error("Audit log insert error: %s", exc)
            return False

    # ===== Auth session methods =====

    async def create_auth_session(self, doc: Dict[str, Any]) -> bool:
        """Persist one login session for refresh-token rotation and revocation."""
        if self.auth_sessions is None:
            return False
        try:
            payload = dict(doc)
            now = datetime.utcnow()
            payload.setdefault("created_at", now)
            payload.setdefault("last_refreshed_at", now)
            payload.pop("role", None)
            await self.auth_sessions.insert_one(payload)
            return True
        except DuplicateKeyError:
            logger.warning("Auth session duplicate for session_id=%s", doc.get("session_id"))
            return False
        except Exception as exc:
            logger.error("Auth session creation error: %s", exc)
            return False

    async def get_auth_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one auth session by session ID."""
        if self.auth_sessions is None:
            return None
        try:
            return await self.auth_sessions.find_one({"session_id": session_id})
        except Exception as exc:
            logger.error("Auth session get error: %s", exc)
            return None

    async def get_auth_session_by_refresh_token_hash(
        self,
        refresh_token_hash: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch one active auth session by current refresh-token hash."""
        if self.auth_sessions is None:
            return None
        try:
            return await self.auth_sessions.find_one({"refresh_token_hash": refresh_token_hash})
        except Exception as exc:
            logger.error("Auth session refresh lookup error: %s", exc)
            return None

    async def rotate_auth_session(
        self,
        session_id: str,
        current_refresh_token_hash: str,
        new_refresh_token_hash: str,
        expires_at: datetime,
    ) -> bool:
        """Rotate the refresh token for one active session."""
        if self.auth_sessions is None:
            return False
        try:
            now = datetime.utcnow()
            result = await self.auth_sessions.update_one(
                {
                    "session_id": session_id,
                    "refresh_token_hash": current_refresh_token_hash,
                    "revoked_at": {"$exists": False},
                    "expires_at": {"$gt": now},
                },
                {
                    "$set": {
                        "refresh_token_hash": new_refresh_token_hash,
                        "expires_at": expires_at,
                        "last_refreshed_at": now,
                    }
                },
            )
            return result.modified_count > 0
        except DuplicateKeyError:
            logger.warning("Auth session rotate collision for session_id=%s", session_id)
            return False
        except Exception as exc:
            logger.error("Auth session rotate error: %s", exc)
            return False

    async def revoke_auth_session(
        self,
        session_id: str,
        reason: str,
        revoked_by: Optional[str] = None,
    ) -> bool:
        """Revoke one active session so access and refresh tokens stop working."""
        if self.auth_sessions is None:
            return False
        try:
            result = await self.auth_sessions.update_one(
                {
                    "session_id": session_id,
                    "revoked_at": {"$exists": False},
                },
                {
                    "$set": {
                        "revoked_at": datetime.utcnow(),
                        "revoked_reason": reason,
                        "revoked_by": revoked_by,
                    }
                },
            )
            return result.modified_count > 0
        except Exception as exc:
            logger.error("Auth session revoke error: %s", exc)
            return False

    async def count_pending_commands(self) -> int:
        """Return current queue backlog for metrics and monitoring."""
        if self.device_commands is None:
            return 0
        try:
            return await self.device_commands.count_documents(
                {"status": {"$in": list(ACTIVE_COMMAND_STATUSES)}}
            )
        except Exception as exc:
            logger.error("Count pending commands error: %s", exc)
            return 0

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
