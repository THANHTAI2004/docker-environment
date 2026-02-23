"""
User data models.
"""
from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, Field, EmailStr


class EmergencyContact(BaseModel):
    """Emergency contact information."""
    name: str
    phone: str
    relation: str


class HealthProfile(BaseModel):
    """Patient health profile."""
    conditions: List[str] = Field(default_factory=list, description="Medical conditions")
    medications: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    emergency_contact: Optional[EmergencyContact] = None


class AlertThresholds(BaseModel):
    """Custom alert thresholds for a user."""
    # SpO2
    spo2_low: Optional[float] = 90.0
    spo2_critical: Optional[float] = 85.0
    
    # Temperature
    temp_high: Optional[float] = 38.0
    temp_critical: Optional[float] = 39.5
    temp_low: Optional[float] = 35.5
    
    # Heart rate
    hr_low: Optional[int] = 50
    hr_high: Optional[int] = 120
    hr_critical: Optional[int] = 150
    
    # Respiratory rate
    rr_low: Optional[int] = 10
    rr_high: Optional[int] = 25


class User(BaseModel):
    """System user (patient or caregiver)."""
    user_id: str
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    role: str = Field(..., description="patient or caregiver")
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    
    # Health profile (for patients)
    health_profile: Optional[HealthProfile] = None
    
    # Custom thresholds
    alert_thresholds: Optional[AlertThresholds] = None
    
    # Associated devices
    devices: List[str] = Field(default_factory=list)
    
    # Caregivers (for patients)
    caregivers: List[str] = Field(default_factory=list, description="Caregiver user IDs")
    
    created_at: Optional[datetime] = None


class UserDB(User):
    """User as stored in database."""
    id: Optional[str] = Field(None, alias="_id")
    
    class Config:
        populate_by_name = True


class UserCreate(BaseModel):
    """User creation request."""
    user_id: str
    name: str
    role: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None


class ThresholdsUpdate(BaseModel):
    """Update user alert thresholds."""
    spo2_low: Optional[float] = None
    spo2_critical: Optional[float] = None
    temp_high: Optional[float] = None
    temp_critical: Optional[float] = None
    temp_low: Optional[float] = None
    hr_low: Optional[int] = None
    hr_high: Optional[int] = None
    hr_critical: Optional[int] = None
    rr_low: Optional[int] = None
    rr_high: Optional[int] = None
