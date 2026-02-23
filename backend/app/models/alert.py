"""
Alert data models.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Alert(BaseModel):
    """Health alert."""
    device_id: str
    user_id: str
    timestamp: float
    alert_type: str = Field(..., description="spo2_low, temp_high, hr_abnormal, etc.")
    severity: str = Field(..., description="info, warning, critical")
    metric: str = Field(..., description="spo2, temperature, heart_rate, etc.")
    value: float
    threshold: float
    message: str
    acknowledged: bool = Field(default=False)
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None


class AlertDB(Alert):
    """Alert as stored in database."""
    id: Optional[str] = Field(None, alias="_id")
    
    class Config:
        populate_by_name = True


class AlertAcknowledge(BaseModel):
    """Alert acknowledgment request."""
    acknowledged_by: str
    notes: Optional[str] = None
