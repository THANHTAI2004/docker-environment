"""
Push notification delivery service backed by Firebase Cloud Messaging.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import settings
from ..db import db

logger = logging.getLogger(__name__)


class PushNotificationService:
    """Dispatch push notifications for newly created alerts."""

    severity_rank = {
        "info": 0,
        "warning": 1,
        "critical": 2,
    }

    def __init__(self):
        self._firebase_app = None

    async def send_alert_notification(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """Send one alert as a push notification to the linked users of the device."""
        alert_id = str(alert.get("id") or alert.get("_id") or "").strip()
        if not alert_id:
            logger.warning("Skipping push dispatch because alert ID is missing")
            return {"status": "missing_alert_id"}

        attempted_at = datetime.utcnow()
        if not settings.push_notifications_enabled:
            await db.update_alert_push_status(
                alert_id,
                {
                    "push_status": "disabled",
                    "push_attempted_at": attempted_at,
                },
            )
            return {"status": "disabled"}

        device_id = alert.get("device_id")
        alert_type = alert.get("alert_type")
        timestamp = float(alert.get("timestamp") or 0)
        if not device_id or not alert_type or not timestamp:
            await db.update_alert_push_status(
                alert_id,
                {
                    "push_status": "missing_context",
                    "push_attempted_at": attempted_at,
                },
            )
            return {"status": "missing_context"}

        previous_alert = await db.get_recent_dispatched_alert(
            device_id=device_id,
            alert_type=alert_type,
            timestamp=timestamp,
            cooldown_seconds=settings.push_notification_cooldown_seconds,
        )
        if previous_alert and not self._is_severity_escalation(
            previous_alert.get("severity"),
            alert.get("severity"),
        ):
            await db.update_alert_push_status(
                alert_id,
                {
                    "push_status": "suppressed_cooldown",
                    "push_attempted_at": attempted_at,
                    "push_suppressed_by_alert_id": previous_alert.get("_id"),
                },
            )
            return {"status": "suppressed_cooldown"}

        recipient_user_ids = [
            user_id
            for user_id in alert.get("recipient_user_ids", [])
            if isinstance(user_id, str) and user_id.strip()
        ]
        if not recipient_user_ids:
            await db.update_alert_push_status(
                alert_id,
                {
                    "push_status": "no_recipients",
                    "push_attempted_at": attempted_at,
                },
            )
            return {"status": "no_recipients"}

        token_docs = await db.list_active_push_tokens(recipient_user_ids)
        token_docs = self._dedupe_tokens(token_docs)
        if not token_docs:
            await db.update_alert_push_status(
                alert_id,
                {
                    "push_status": "no_tokens",
                    "push_attempted_at": attempted_at,
                },
            )
            return {"status": "no_tokens"}

        device = await db.get_device(device_id)
        title = self._build_title(alert, device)
        body = alert.get("message") or "Health alert detected"
        data = self._build_data(alert, device)

        try:
            delivery = await self._dispatch_multicast(
                tokens=[item["fcm_token"] for item in token_docs],
                title=title,
                body=body,
                data=data,
            )
        except Exception as exc:
            logger.error("Push notification dispatch error for alert=%s: %s", alert_id, exc, exc_info=True)
            await db.update_alert_push_status(
                alert_id,
                {
                    "push_status": "error",
                    "push_attempted_at": attempted_at,
                    "push_error": str(exc),
                },
            )
            return {"status": "error", "error": str(exc)}

        invalid_tokens = delivery.get("invalid_tokens", [])
        if invalid_tokens:
            await db.deactivate_push_tokens_by_fcm_tokens(invalid_tokens)

        dispatched_at: Optional[datetime] = attempted_at if delivery.get("success_count", 0) > 0 else None
        status = "sent" if dispatched_at else "error"
        await db.update_alert_push_status(
            alert_id,
            {
                "push_status": status,
                "push_attempted_at": attempted_at,
                "push_dispatched_at": dispatched_at,
                "push_success_count": delivery.get("success_count", 0),
                "push_failure_count": delivery.get("failure_count", 0),
                "push_invalid_token_count": len(invalid_tokens),
                "push_error_codes": delivery.get("error_codes") or None,
            },
        )
        return {"status": status, **delivery}

    def _is_severity_escalation(self, previous: Any, current: Any) -> bool:
        """Allow a push inside cooldown only when severity escalates."""
        previous_rank = self.severity_rank.get(str(previous), -1)
        current_rank = self.severity_rank.get(str(current), -1)
        return current_rank > previous_rank

    def _dedupe_tokens(self, token_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep the newest registration per FCM token."""
        seen: set[str] = set()
        deduped: List[Dict[str, Any]] = []
        for token_doc in token_docs:
            token = token_doc.get("fcm_token")
            if not token or token in seen:
                continue
            seen.add(token)
            deduped.append(token_doc)
        return deduped

    def _build_title(self, alert: Dict[str, Any], device: Optional[Dict[str, Any]]) -> str:
        """Build a compact notification title for one alert."""
        severity = str(alert.get("severity") or "warning").upper()
        device_name = None
        if isinstance(device, dict):
            device_name = device.get("device_name") or device.get("device_id")
        if not device_name:
            device_name = alert.get("device_id") or "device"
        return f"{severity}: {device_name}"

    def _build_data(self, alert: Dict[str, Any], device: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """Build FCM data payload for in-app routing."""
        payload = {
            "alert_id": str(alert.get("id") or alert.get("_id") or ""),
            "device_id": str(alert.get("device_id") or ""),
            "device_name": str((device or {}).get("device_name") or ""),
            "alert_type": str(alert.get("alert_type") or ""),
            "severity": str(alert.get("severity") or ""),
            "metric": str(alert.get("metric") or ""),
            "message": str(alert.get("message") or ""),
            "timestamp": str(alert.get("timestamp") or ""),
            "click_action": "OPEN_ALERT",
        }
        return {key: value for key, value in payload.items() if value}

    async def _dispatch_multicast(
        self,
        tokens: List[str],
        title: str,
        body: str,
        data: Dict[str, str],
    ) -> Dict[str, Any]:
        """Send one multicast FCM message without blocking the event loop."""
        return await asyncio.to_thread(
            self._dispatch_multicast_sync,
            tokens=tokens,
            title=title,
            body=body,
            data=data,
        )

    def _dispatch_multicast_sync(
        self,
        *,
        tokens: List[str],
        title: str,
        body: str,
        data: Dict[str, str],
    ) -> Dict[str, Any]:
        """Perform the blocking Firebase Admin SDK call."""
        firebase_app, messaging = self._get_firebase_components()
        message = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(title=title, body=body),
            data=data,
        )
        batch = messaging.send_each_for_multicast(message, app=firebase_app)

        error_codes: List[str] = []
        invalid_tokens: List[str] = []
        for index, response in enumerate(batch.responses):
            if response.success:
                continue
            exception = response.exception
            error_code = self._error_code(exception)
            error_codes.append(error_code)
            if self._is_invalid_token_error(exception):
                invalid_tokens.append(tokens[index])

        return {
            "success_count": batch.success_count,
            "failure_count": batch.failure_count,
            "invalid_tokens": invalid_tokens,
            "error_codes": sorted(set(error_codes)),
        }

    def _get_firebase_components(self):
        """Resolve the Firebase Admin SDK app and messaging module lazily."""
        try:
            import firebase_admin
            from firebase_admin import credentials, messaging
        except ImportError as exc:
            raise RuntimeError(
                "firebase-admin is not installed; add it to backend dependencies before enabling push notifications"
            ) from exc

        if self._firebase_app is not None:
            return self._firebase_app, messaging

        options = {"projectId": settings.fcm_project_id} if settings.fcm_project_id else None
        app_name = "wearable-push"

        try:
            self._firebase_app = firebase_admin.get_app(app_name)
            return self._firebase_app, messaging
        except ValueError:
            pass

        credential = None
        if settings.fcm_service_account_json:
            try:
                credential = credentials.Certificate(json.loads(settings.fcm_service_account_json))
            except json.JSONDecodeError as exc:
                raise RuntimeError("FCM_SERVICE_ACCOUNT_JSON must be valid JSON") from exc
        elif settings.fcm_service_account_path:
            credential = credentials.Certificate(settings.fcm_service_account_path)

        if credential is not None:
            self._firebase_app = firebase_admin.initialize_app(credential=credential, options=options, name=app_name)
        else:
            self._firebase_app = firebase_admin.initialize_app(options=options, name=app_name)
        return self._firebase_app, messaging

    def _is_invalid_token_error(self, exception: Exception | None) -> bool:
        """Identify provider errors that mean a stored token should be deactivated."""
        if exception is None:
            return False
        code = self._error_code(exception)
        return code in {
            "registration-token-not-registered",
            "unregistered",
            "invalid-registration-token",
        } or type(exception).__name__ in {"UnregisteredError"}

    def _error_code(self, exception: Exception | None) -> str:
        """Extract a normalized error code from one Firebase Admin SDK exception."""
        if exception is None:
            return ""
        code = getattr(exception, "code", None)
        if isinstance(code, str) and code:
            return code.replace("messaging/", "")
        cause = getattr(exception, "cause", None)
        cause_code = getattr(cause, "code", None)
        if isinstance(cause_code, str) and cause_code:
            return cause_code.replace("messaging/", "")
        return type(exception).__name__


push_notification_service = PushNotificationService()
