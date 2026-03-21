"""
Logging, request correlation, and metrics helpers.
"""
import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest


request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

REQUEST_COUNT = Counter(
    "wearable_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "wearable_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)
RATE_LIMIT_HITS = Counter(
    "wearable_rate_limit_hits_total",
    "Total rate-limited requests",
    ["category"],
)
DB_PING_FAILURES = Counter(
    "wearable_db_ping_failures_total",
    "Database ping failures observed by readiness checks",
)
PENDING_COMMANDS = Gauge(
    "wearable_device_commands_pending",
    "Pending or in-flight device commands",
)
DEVICE_COMMANDS_BY_STATUS = Gauge(
    "wearable_device_commands_current",
    "Current device commands by status",
    ["status"],
)
DEVICE_COMMAND_DISPATCHED_TOTAL = Counter(
    "wearable_device_command_dispatched_total",
    "Total device commands dispatched to ESP",
    ["command"],
)
DEVICE_COMMAND_COMPLETED_TOTAL = Counter(
    "wearable_device_command_completed_total",
    "Total device commands completed successfully",
    ["command"],
)
DEVICE_COMMAND_FAILED_TOTAL = Counter(
    "wearable_device_command_failed_total",
    "Total device commands that failed terminally",
    ["command", "reason"],
)
DEVICE_COMMAND_TIMEOUT_TOTAL = Counter(
    "wearable_device_command_timeout_total",
    "Total device commands that exceeded ACK timeout",
    ["command"],
)
DEVICE_COMMAND_RETRY_TOTAL = Counter(
    "wearable_device_command_retry_total",
    "Total device command retries scheduled",
    ["command"],
)
DEVICE_COMMAND_QUEUE_LATENCY = Histogram(
    "wearable_device_command_queue_latency_seconds",
    "Time spent waiting in queue before dispatch",
    ["command"],
)
AUTH_LOGIN_TOTAL = Counter(
    "wearable_auth_login_total",
    "Login attempts",
    ["outcome"],
)
AUTH_REFRESH_TOTAL = Counter(
    "wearable_auth_refresh_total",
    "Refresh-token attempts",
    ["outcome"],
)
AUTH_REVOKED_SESSIONS_TOTAL = Counter(
    "wearable_auth_revoked_sessions_total",
    "Revoked auth sessions",
    ["reason"],
)
AUTH_CHANGE_PASSWORD_TOTAL = Counter(
    "wearable_auth_change_password_total",
    "Change-password attempts",
    ["outcome"],
)
ESP_READINGS_RECEIVED_TOTAL = Counter(
    "wearable_esp_readings_received_total",
    "ESP readings received by ingest API",
    ["device_type"],
)
ESP_VALIDATION_FAILURE_TOTAL = Counter(
    "wearable_esp_validation_failure_total",
    "ESP ingest payload validation failures",
)
ESP_DUPLICATE_READINGS_TOTAL = Counter(
    "wearable_esp_duplicate_readings_total",
    "Duplicate ESP readings ignored by QoS deduplication",
)
ALERTS_CREATED_TOTAL = Counter(
    "wearable_alerts_created_total",
    "Alerts created by the alert service",
    ["severity", "alert_type"],
)
ALERTS_ACKNOWLEDGED_TOTAL = Counter(
    "wearable_alerts_acknowledged_total",
    "Alerts acknowledged by users",
    ["severity"],
)


class JsonFormatter(logging.Formatter):
    """Emit logs as compact JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(use_json: bool) -> None:
    """Configure root logging once at startup."""
    formatter: logging.Formatter
    if use_json:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in root.handlers:
        handler.setFormatter(formatter)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)


def set_request_id(request_id: str):
    """Bind a request ID to the current context."""
    return request_id_ctx.set(request_id)


def reset_request_id(token) -> None:
    """Reset the current request ID context."""
    request_id_ctx.reset(token)


def metrics_payload() -> bytes:
    """Serialize Prometheus metrics."""
    return generate_latest()


def metrics_content_type() -> str:
    """Expose Prometheus content type."""
    return CONTENT_TYPE_LATEST
