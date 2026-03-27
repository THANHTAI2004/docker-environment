"""
Push notification token models.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


PushPlatform = Literal["android", "ios", "web"]


class PushToken(BaseModel):
    """One mobile/web push registration token bound to an installation."""

    user_id: str
    installation_id: str = Field(..., min_length=1, max_length=200)
    fcm_token: str = Field(..., min_length=16, max_length=4096)
    platform: PushPlatform
    is_active: bool = True
    last_seen_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None


class PushTokenDB(PushToken):
    """Push token document as stored in MongoDB."""

    id: Optional[str] = Field(None, alias="_id")

    model_config = ConfigDict(populate_by_name=True)


class PushTokenUpsertRequest(BaseModel):
    """Request payload used by the app to register or refresh one FCM token."""

    installation_id: str = Field(..., min_length=1, max_length=200)
    fcm_token: str = Field(..., min_length=16, max_length=4096)
    platform: PushPlatform
