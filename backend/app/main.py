"""
FastAPI backend for wearable health monitoring system.
REST API + MongoDB for health data management.
"""
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

# Import modular components
from .config import settings
from .utils.auth import require_admin_api_key, require_api_key
from .db import db

# Import API routers
from .api import health_router, alerts_router, devices_router, users_router, esp_router


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RequestRateLimiter:
    """Simple in-memory per-IP rate limiter with separate ESP/general buckets."""

    def __init__(self):
        self._counts: dict[tuple[str, int, str], int] = defaultdict(int)

    def _client_ip(self, request: Request) -> str:
        # Cloudflare and proxies usually provide original client IP in these headers.
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip:
            return cf_ip.strip()

        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()

        x_real_ip = request.headers.get("x-real-ip")
        if x_real_ip:
            return x_real_ip.strip()

        return request.client.host if request.client else "unknown"

    def check(self, request: Request) -> tuple[bool, int]:
        if not settings.rate_limit_enabled:
            return True, 0

        path = request.url.path
        if path in {"/health", "/live", "/ready"}:
            return True, 0

        category = "esp" if path.startswith("/api/v1/esp/") else "general"
        limit = (
            settings.rate_limit_esp_per_minute
            if category == "esp"
            else settings.rate_limit_general_per_minute
        )

        now_min = int(time.time() // 60)
        ip = self._client_ip(request)
        key = (ip, now_min, category)
        self._counts[key] += 1
        remaining = max(limit - self._counts[key], 0)

        # Opportunistic cleanup to keep memory bounded.
        old_min = now_min - 2
        stale_keys = [k for k in self._counts if k[1] < old_min]
        for stale in stale_keys:
            self._counts.pop(stale, None)

        return self._counts[key] <= limit, remaining


rate_limiter = RequestRateLimiter()


# ===== Startup/Shutdown Lifespan =====

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize and teardown application resources."""
    logger.info("Starting Wearable Health Monitoring Backend...")
    db.connect()
    await db.create_indexes()
    logger.info("MongoDB connected and indexes created")
    logger.info("REST ingestion is enabled for ESP devices")
    yield
    # Shutdown: close MongoDB connection
    if db.client:
        db.client.close()
        logger.info("MongoDB connection closed")


# FastAPI app with enhanced metadata
app = FastAPI(
    lifespan=lifespan,
    title="Wearable Health Monitoring API",
    description="""
    Backend service for elderly health monitoring with wearable devices.
    
    ## Features
    
    * **Health Data Management** - Store and retrieve vital signs, ECG waveforms
    * **Alert System** - Automatic threshold-based alerts with customizable levels
    * **Device Management** - Register and track wearable devices
    * **User Management** - Patient and caregiver profiles with custom thresholds
    
    ## Alert Thresholds
    
    - SpO₂: Warning <90%, Critical <85%
    - Temperature: Warning >38°C, Critical >39.5°C
    - Heart Rate: Warning 50-120 bpm, Critical <40 or >150 bpm
    - Respiratory Rate: Warning 10-25 breaths/min
    """,
    version="2.0.0",
    contact={
        "name": "Health Monitoring Team",
    },
    license_info={
        "name": "MIT License",
    },
    docs_url="/docs" if settings.expose_api_docs else None,
    redoc_url="/redoc" if settings.expose_api_docs else None,
    openapi_url="/openapi.json" if settings.expose_api_docs else None,
)

# CORS middleware - allow Flutter web/mobile apps
cors_origins = [
    origin.strip()
    for origin in settings.cors_allow_origins.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=settings.cors_allow_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    allowed, remaining = rate_limiter.check(request)
    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"message": "Too many requests"},
            headers={"Retry-After": "60"},
        )

    response = await call_next(request)
    if settings.rate_limit_enabled:
        response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response

# Custom exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with detailed messages."""
    logger.warning(f"Validation error on {request.url}: {exc.errors()}")
    content = {"detail": exc.errors(), "message": "Invalid request data"}
    if settings.expose_error_details:
        content["body"] = exc.body
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=content,
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors."""
    logger.error(f"Unexpected error on {request.url}: {str(exc)}", exc_info=True)
    detail = str(exc) if settings.expose_error_details else "Contact administrator"
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "message": "Internal server error",
            "detail": detail,
        },
    )

# Include API routers
app.include_router(health_router, dependencies=[Depends(require_api_key)])
app.include_router(alerts_router, dependencies=[Depends(require_api_key)])
app.include_router(devices_router, dependencies=[Depends(require_api_key)])
app.include_router(users_router, dependencies=[Depends(require_api_key)])
app.include_router(esp_router)


# ===== Legacy Models =====

class Reading(BaseModel):
    """Legacy reading model for backwards compatibility."""
    device_id: str
    ts: Optional[float] = None
    heart_rate: Optional[float] = None
    temperature: Optional[float] = None
    raw: Optional[dict] = None


# ===== Health Check Endpoint =====

def _readiness_payload(db_ok: bool) -> dict[str, str]:
    """Return a stable readiness payload for API and container probes."""
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "ingest_mode": "rest_api",
    }


@app.get("/live")
async def live_check():
    """Liveness endpoint that only reports whether the process is running."""
    return {"status": "alive", "ingest_mode": "rest_api"}


@app.get("/ready")
async def readiness_check():
    """Readiness endpoint that fails when the database is unavailable."""
    db_ok = await db.ping()
    payload = _readiness_payload(db_ok)
    return JSONResponse(
        status_code=status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload,
    )


@app.get("/health")
async def health_check():
    """Compatibility alias for readiness checks used by monitoring."""
    return await readiness_check()


# ===== Legacy API Endpoints (Backwards Compatibility) =====

@app.post("/readings")
async def post_reading(r: Reading, _: None = Depends(require_admin_api_key)):
    """
    Post a sensor reading (legacy endpoint for backwards compatibility).
    """
    doc = r.dict()
    doc["received_at"] = datetime.utcnow()
    
    success = await db.insert_reading(doc)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to insert reading")

    return {"status": "success", "device_id": r.device_id}


@app.get("/history/{device_id}")
async def get_history(device_id: str, limit: int = 100, _: None = Depends(require_api_key)):
    """
    Get historical readings for a device (legacy endpoint).
    """
    items = await db.get_legacy_readings_by_device(device_id, limit)
    
    return {
        "device_id": device_id,
        "count": len(items),
        "items": items
    }
