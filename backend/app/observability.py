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
