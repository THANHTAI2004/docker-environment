"""
Data models for wearable health monitoring system.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class VitalsData(BaseModel):
    """Nested vitals object for new format."""
    heart_rate: Optional[int] = Field(None, ge=0, le=300, description="Heart rate bpm")
    respiratory_rate: Optional[int] = Field(None, ge=0, le=60, description="Breaths per minute")
    spo2: Optional[float] = Field(None, ge=0, le=100, description="Blood oxygen saturation %")
    temperature: Optional[float] = Field(None, ge=30, le=45, description="Body temperature °C")


class MetadataInfo(BaseModel):
    """Device metadata."""
    battery_level: Optional[int] = Field(None, ge=0, le=100, description="Battery percentage")
    signal_strength: Optional[int] = Field(None, description="WiFi RSSI (dBm)")
    signal_quality: Optional[int] = Field(None, ge=0, le=100, description="BLE/application quality score")
    firmware_version: Optional[str] = Field(None, description="Firmware version")


class ECGData(BaseModel):
    """ECG waveform data."""
    waveform: List[float] = Field(..., description="Raw ECG samples")
    sampling_rate: int = Field(..., description="Sampling rate in Hz")
    duration: Optional[float] = Field(None, description="Duration in seconds")
    lead_off: bool = Field(default=False, description="Lead-off detection")
    quality: str = Field(default="good", description="Signal quality: good, fair, poor")
    ecg_hr: Optional[int] = Field(None, description="Heart rate from ECG")


class LocationData(BaseModel):
    """GPS location data."""
    latitude: float
    longitude: float


class HealthReading(BaseModel):
    """Health reading from wearable device."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # Accept both device_id and device_uid from device payload.
    device_id: str = Field(
        ...,
        validation_alias=AliasChoices("device_id", "device_uid"),
        description="Unique device identifier",
    )
    device_type: Optional[str] = Field(default=None, description="wrist or chest")
    timestamp: Optional[float] = None
    seq: Optional[int] = None

    # NEW: Nested vitals object (preferred format)
    vitals: Optional[VitalsData] = None
    
    # DEPRECATED: Flat vitals fields (backward compatibility)
    spo2: Optional[float] = Field(None, ge=0, le=100, description="Blood oxygen saturation % (deprecated, use vitals.spo2)")
    temperature: Optional[float] = Field(None, ge=30, le=45, description="Body temperature °C (deprecated, use vitals.temperature)")
    respiratory_rate: Optional[int] = Field(None, ge=0, le=60, description="Breaths per minute (deprecated, use vitals.respiratory_rate)")
    heart_rate: Optional[int] = Field(None, ge=0, le=300, description="Heart rate bpm (deprecated, use vitals.heart_rate)")
    
    # ECG data (chest device only)
    ecg: Optional[ECGData] = None
    
    # NEW: Nested metadata object (preferred format)
    metadata: Optional[MetadataInfo] = None
    
    # DEPRECATED: Flat metadata fields (backward compatibility)
    battery_level: Optional[int] = Field(None, ge=0, le=100, description="Battery % (deprecated, use metadata.battery_level)")
    signal_strength: Optional[int] = Field(None, description="WiFi RSSI (deprecated, use metadata.signal_strength)")
    location: Optional[LocationData] = None
    
    # System fields (added by server)
    received_at: Optional[datetime] = None

    @property
    def device_uid(self) -> str:
        """Backward-compatible alias for existing code paths."""
        return self.device_id


class HealthReadingDB(HealthReading):
    """Health reading as stored in database."""
    id: Optional[str] = Field(None, alias="_id")
