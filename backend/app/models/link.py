"""
User-device link models.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_link_role(value: str) -> str:
    """Map legacy caregiver links to the new viewer role."""
    if value == "caregiver":
        return "viewer"
    return value


class DeviceLink(BaseModel):
    """One relationship between a user account and a device."""
    device_id: str
    user_id: str
    link_role: Literal["owner", "viewer"] = Field(default="viewer")
    linked_at: Optional[datetime] = None
    linked_by: Optional[str] = None
    updated_at: Optional[datetime] = None

    @field_validator("link_role", mode="before")
    @classmethod
    def normalize_link_role(cls, value: str) -> str:
        return _normalize_link_role(value)


class DeviceLinkDB(DeviceLink):
    """Device link as stored in database."""
    id: Optional[str] = Field(None, alias="_id")

    model_config = ConfigDict(populate_by_name=True)


class DeviceLinkRequest(BaseModel):
    """Request payload to link a user to a device."""
    user_id: Optional[str] = None
    link_role: Literal["owner", "viewer", "caregiver"] = Field(default="viewer")

    @field_validator("link_role", mode="before")
    @classmethod
    def normalize_link_role(cls, value: str) -> str:
        return _normalize_link_role(value)


class DeviceViewerRequest(BaseModel):
    """Request payload to add one viewer to a device."""
    user_id: str


class DeviceCaregiverRequest(DeviceViewerRequest):
    """Backward-compatible alias for older caregiver payloads."""
