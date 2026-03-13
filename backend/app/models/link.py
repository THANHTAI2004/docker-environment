"""
User-device link models.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DeviceLink(BaseModel):
    """One relationship between a user account and a device."""
    device_id: str
    user_id: str
    link_role: Literal["owner", "viewer"] = Field(default="viewer")
    linked_at: Optional[datetime] = None
    linked_by: Optional[str] = None
    updated_at: Optional[datetime] = None


class DeviceLinkDB(DeviceLink):
    """Device link as stored in database."""
    id: Optional[str] = Field(None, alias="_id")

    model_config = ConfigDict(populate_by_name=True)


class DeviceLinkRequest(BaseModel):
    """Request payload to link a user to a device."""
    user_id: Optional[str] = None
    link_role: Literal["owner", "viewer"] = Field(default="viewer")
