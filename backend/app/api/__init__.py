"""
API routers for wearable health monitoring.
"""
from .auth import router as auth_router
from .health import router as health_router
from .alerts import router as alerts_router
from .devices import router as devices_router
from .users import router as users_router
from .esp import router as esp_router
from .push import router as push_router

__all__ = ["auth_router", "health_router", "alerts_router", "devices_router", "users_router", "esp_router", "push_router"]
