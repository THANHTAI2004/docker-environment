"""
User account models.
"""
from datetime import date, datetime
from typing import Optional, List, Dict, Literal
from pydantic import BaseModel, ConfigDict, Field, EmailStr

SystemUserRole = Literal["admin"]


class EmergencyContact(BaseModel):
    """Emergency contact information."""
    name: str
    phone: str
    relation: str


class HealthProfile(BaseModel):
    """Optional health context stored on a user account."""
    conditions: List[str] = Field(default_factory=list, description="Medical conditions")
    medications: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    emergency_contact: Optional[EmergencyContact] = None


class AlertThresholds(BaseModel):
    """Alert-threshold overrides reusable for one device."""
    # SpO2
    spo2_low: Optional[float] = 90.0
    spo2_critical: Optional[float] = 85.0
    
    # Temperature
    temp_high: Optional[float] = 38.0
    temp_critical: Optional[float] = 39.5
    temp_low: Optional[float] = 35.5
    
    # Heart rate
    hr_low: Optional[int] = 50
    hr_low_critical: Optional[int] = 40
    hr_high: Optional[int] = 120
    hr_critical: Optional[int] = 150
    
    # Respiratory rate
    rr_low: Optional[int] = 10
    rr_high: Optional[int] = 25


class User(BaseModel):
    """User account with identity and authentication fields."""
    user_id: str
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    role: Optional[SystemUserRole] = Field(
        default=None,
        description="Internal system role for admin accounts only.",
    )
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    phone_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    is_active: bool = True
    
    # Health profile (optional)
    health_profile: Optional[HealthProfile] = None
    
    # Legacy user-scoped thresholds kept only for backward compatibility.
    alert_thresholds: Optional[AlertThresholds] = None
    
    # Associated devices
    devices: List[str] = Field(default_factory=list)
    
    # Legacy sharing field retained for backward compatibility with older records.
    caregivers: List[str] = Field(default_factory=list, description="Deprecated legacy sharing field")
    
    created_at: Optional[datetime] = None


class UserDB(User):
    """User as stored in database."""
    id: Optional[str] = Field(None, alias="_id")

    model_config = ConfigDict(populate_by_name=True)


class UserCreate(BaseModel):
    """User creation request."""
    user_id: str
    name: str
    role: Optional[SystemUserRole] = Field(
        default=None,
        description="Optional internal system role. Omit for normal product users.",
    )
    password: str = Field(..., min_length=8)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    phone_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    caregivers: List[str] = Field(default_factory=list)


class ThresholdsUpdate(BaseModel):
    """Update device-scoped alert threshold overrides."""
    spo2_low: Optional[float] = None
    spo2_critical: Optional[float] = None
    temp_high: Optional[float] = None
    temp_critical: Optional[float] = None
    temp_low: Optional[float] = None
    hr_low: Optional[int] = None
    hr_low_critical: Optional[int] = None
    hr_high: Optional[int] = None
    hr_critical: Optional[int] = None
    rr_low: Optional[int] = None
    rr_high: Optional[int] = None
