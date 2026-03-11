"""
FastAPI backend for wearable health monitoring system.
REST API + MongoDB for health data management.
"""
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

# Import modular components
from .config import settings
from .db import db
from .observability import (
    DB_PING_FAILURES,
    PENDING_COMMANDS,
    RATE_LIMIT_HITS,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    configure_logging,
    metrics_content_type,
    metrics_payload,
    reset_request_id,
    set_request_id,
)
from .utils.access import ensure_device_access
from .utils.auth import require_admin_principal, require_current_user
from .utils.rate_limit import RateLimiter

# Import API routers
from .api import auth_router, health_router, alerts_router, devices_router, users_router, esp_router


# Configure logging
configure_logging(settings.log_json)
logger = logging.getLogger(__name__)
rate_limiter = RateLimiter()


# ===== Startup/Shutdown Lifespan =====

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize and teardown application resources."""
    logger.info("Starting Wearable Health Monitoring Backend...")
    db.connect()
    await rate_limiter.connect()
    await db.create_indexes()
    logger.info("MongoDB connected and indexes created")
    logger.info("REST ingestion is enabled for ESP devices")
    yield
    # Shutdown: close MongoDB connection
    await rate_limiter.close()
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
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    token = set_request_id(request_id)
    try:
        response = await call_next(request)
    finally:
        reset_request_id(token)
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    allowed, remaining, category = await rate_limiter.check(request)
    if not allowed:
        RATE_LIMIT_HITS.labels(category=category).inc()
        REQUEST_COUNT.labels(
            method=request.method,
            path=request.url.path,
            status_code=str(status.HTTP_429_TOO_MANY_REQUESTS),
        ).inc()
        logger.warning("Rate limit exceeded for path=%s category=%s", request.url.path, category)
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"message": "Too many requests"},
            headers={"Retry-After": "60"},
        )

    with REQUEST_LATENCY.labels(method=request.method, path=request.url.path).time():
        response = await call_next(request)
    REQUEST_COUNT.labels(
        method=request.method,
        path=request.url.path,
        status_code=str(response.status_code),
    ).inc()
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
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(alerts_router)
app.include_router(devices_router)
app.include_router(users_router)
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
    if not db_ok:
        DB_PING_FAILURES.inc()
    payload = _readiness_payload(db_ok)
    return JSONResponse(
        status_code=status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload,
    )


@app.get("/health")
async def health_check():
    """Compatibility alias for readiness checks used by monitoring."""
    return await readiness_check()


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    PENDING_COMMANDS.set(await db.count_pending_commands())
    return Response(content=metrics_payload(), media_type=metrics_content_type())


# ===== Legacy API Endpoints (Backwards Compatibility) =====

@app.post("/readings")
async def post_reading(r: Reading, _: dict = Depends(require_admin_principal)):
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
async def get_history(
    device_id: str,
    limit: int = 100,
    current_user: dict = Depends(require_current_user),
):
    """
    Get historical readings for a device (legacy endpoint).
    """
    await ensure_device_access(current_user, device_id)
    items = await db.get_legacy_readings_by_device(device_id, limit)
    
    return {
        "device_id": device_id,
        "count": len(items),
        "items": items
    }
