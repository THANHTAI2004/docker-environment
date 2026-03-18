"""
Device data models.
"""
from datetime import datetime
from typing import Optional, Dict, Literal
from pydantic import BaseModel, ConfigDict, Field

from .user import AlertThresholds


class DeviceMetadata(BaseModel):
    """Device metadata."""
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None


class DeviceSettings(BaseModel):
    """Owner-managed device settings."""
    model_config = ConfigDict(extra="allow")

    alert_thresholds: Optional[AlertThresholds] = None


class Device(BaseModel):
    """Wearable device."""
    device_id: str
    device_type: str = Field(..., description="wrist or chest")
    device_name: str
    firmware_version: Optional[str] = None
    registered_at: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    status: str = Field(default="active", description="active, inactive, maintenance")
    owner_user_id: Optional[str] = None
    metadata: Optional[DeviceMetadata] = None
    settings: Optional[DeviceSettings] = None
    alert_thresholds: Optional[AlertThresholds] = None


class DeviceDB(Device):
    """Device as stored in database."""
    id: Optional[str] = Field(None, alias="_id")

    model_config = ConfigDict(populate_by_name=True)


class DeviceRegistration(BaseModel):
    """Device registration request."""
    device_id: str
    device_type: str
    device_name: Optional[str] = None
    firmware_version: Optional[str] = None
    metadata: Optional[DeviceMetadata] = None
    settings: Optional[DeviceSettings] = None
    alert_thresholds: Optional[AlertThresholds] = None


class ECGRequestCommand(BaseModel):
    """ECG capture command issued by app."""
    duration_seconds: int = Field(default=10, ge=3, le=60)
    sampling_rate: int = Field(default=250, ge=100, le=1000)


class ESPCommandAck(BaseModel):
    """ESP command acknowledgement payload."""
    status: Literal["done", "failed"] = "done"
    message: Optional[str] = None
