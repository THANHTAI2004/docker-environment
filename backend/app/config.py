"""
Application configuration using Pydantic Settings.
All settings can be overridden via environment variables.
"""
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API authentication
    api_key: str = "dev-api-key"
    admin_api_key: str = "change-this-admin-api-key"
    device_token_secret: str = "change-this-device-token-secret"
    jwt_secret: str = "change-this-jwt-secret"
    refresh_token_secret: str = "change-this-refresh-token-secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_exp_minutes: int = 60
    jwt_refresh_token_exp_days: int = 30
    cors_allow_origins: str = (
        "https://app.eldercare.io.vn,"
        "https://admin.eldercare.io.vn,"
        "http://localhost,http://127.0.0.1,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )
    cors_allow_origin_regex: str = ""
    rate_limit_enabled: bool = True
    rate_limit_storage: str = "redis"
    rate_limit_general_per_minute: int = 300
    rate_limit_esp_per_minute: int = 1200
    redis_url: str = "redis://redis:6379/0"
    expose_error_details: bool = False
    expose_api_docs: bool = False
    expose_metrics: bool = False
    metrics_token: str = ""
    metrics_allow_ips: str = "127.0.0.1,::1,localhost"
    allow_admin_api_key_bootstrap: bool = False
    log_json: bool = True
    device_clock_skew_tolerance_seconds: int = 300
    
    # MongoDB Configuration
    mongo_uri: str = "mongodb://admin:change-this-mongo-password@mongodb:27017"
    mongo_db: str = "wearable"
    mongo_collection: str = "readings"
    
    # Health Collections
    mongo_health_collection: str = "health_readings"
    mongo_alerts_collection: str = "alerts"
    mongo_devices_collection: str = "devices"
    mongo_users_collection: str = "users"
    mongo_commands_collection: str = "device_commands"
    mongo_audit_collection: str = "audit_logs"
    mongo_device_links_collection: str = "device_links"
    mongo_auth_sessions_collection: str = "auth_sessions"
    command_ttl_seconds: int = 300
    command_ack_timeout_seconds: int = 45
    command_retry_delay_seconds: int = 5
    command_recovery_interval_seconds: int = 15
    command_max_dispatch_count: int = 3
    command_max_pending_per_device: int = 3
    command_dedupe_window_seconds: int = 20
    alert_dedupe_window_seconds: int = 120
    
    # Health Monitoring Alert Thresholds (defaults)
    # SpO2
    spo2_low_warning: float = 90.0
    spo2_low_critical: float = 85.0
    
    # Temperature
    temp_high_warning: float = 38.0
    temp_high_critical: float = 39.5
    temp_low_warning: float = 35.5
    
    # Heart Rate
    hr_low_warning: int = 50
    hr_low_critical: int = 40
    hr_high_warning: int = 120
    hr_high_critical: int = 150
    
    # Respiratory Rate
    rr_low_warning: int = 10
    rr_high_warning: int = 25
    
    # ECG Quality Alerts
    ecg_quality_alert: bool = True
    ecg_lead_off_alert: bool = True
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def validate_runtime_secrets(self) -> None:
        """Fail fast when runtime secrets are missing or left at placeholders."""
        invalid: list[str] = []

        if self.api_key in {"", "dev-api-key", "change-this-api-key"}:
            invalid.append("API_KEY")
        if self.admin_api_key in {"", "change-this-admin-api-key"}:
            invalid.append("ADMIN_API_KEY")
        if self.device_token_secret in {"", "change-this-device-token-secret"}:
            invalid.append("DEVICE_TOKEN_SECRET")
        if self.jwt_secret in {"", "change-this-jwt-secret"}:
            invalid.append("JWT_SECRET")
        if self.refresh_token_secret in {"", "change-this-refresh-token-secret"}:
            invalid.append("REFRESH_TOKEN_SECRET")
        if self.admin_api_key == self.api_key:
            invalid.append("ADMIN_API_KEY must differ from API_KEY")
        if self.jwt_secret in {self.api_key, self.admin_api_key, self.device_token_secret}:
            invalid.append("JWT_SECRET must differ from API_KEY, ADMIN_API_KEY, DEVICE_TOKEN_SECRET")
        if self.refresh_token_secret in {
            self.api_key,
            self.admin_api_key,
            self.device_token_secret,
            self.jwt_secret,
        }:
            invalid.append(
                "REFRESH_TOKEN_SECRET must differ from API_KEY, ADMIN_API_KEY, DEVICE_TOKEN_SECRET, JWT_SECRET"
            )

        mongo_password = urlsplit(self.mongo_uri).password or ""
        if mongo_password in {"", "change-this-mongo-password", "SecurePassword2026!"}:
            invalid.append("MONGO_URI / MONGO_ROOT_PASSWORD")

        if invalid:
            joined = ", ".join(invalid)
            raise ValueError(
                f"Insecure runtime configuration detected. Update these values before startup: {joined}"
            )


# Global settings instance
settings = Settings()
settings.validate_runtime_secrets()
