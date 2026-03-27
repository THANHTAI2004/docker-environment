"""
Data validation utilities for health readings.
"""
from typing import Dict, Any, List, Optional


def validate_vital_signs(data: Dict[str, Any]) -> tuple[bool, Optional[List[str]]]:
    """
    Validate vital signs data for reasonable ranges.
    
    Returns:
        (is_valid, errors) - True if valid, list of error messages if not
    """
    errors = []
    
    # SpO2 validation (70-100%)
    if "spo2" in data and data["spo2"] is not None:
        spo2 = data["spo2"]
        if not (70 <= spo2 <= 100):
            errors.append(f"SpO2 out of range: {spo2}% (expected 70-100%)")
    
    # Temperature validation (30-45°C)
    if "temperature" in data and data["temperature"] is not None:
        temp = data["temperature"]
        if not (30 <= temp <= 45):
            errors.append(f"Temperature out of range: {temp}°C (expected 30-45°C)")
    
    # Heart rate validation (20-300 bpm)
    if "heart_rate" in data and data["heart_rate"] is not None:
        hr = data["heart_rate"]
        if not (20 <= hr <= 300):
            errors.append(f"Heart rate out of range: {hr} bpm (expected 20-300 bpm)")
    
    # Battery level validation (0-100%)
    if "battery_level" in data and data["battery_level"] is not None:
        battery = data["battery_level"]
        if not (0 <= battery <= 100):
            errors.append(f"Battery level out of range: {battery}% (expected 0-100%)")
    
    return len(errors) == 0, errors if errors else None


def validate_ecg_data(ecg: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Validate ECG waveform data.
    
    Returns:
        (is_valid, error_message)
    """
    # Check required fields
    if "waveform" not in ecg:
        return False, "ECG waveform data is required"
    
    if "sampling_rate" not in ecg:
        return False, "ECG sampling rate is required"
    
    waveform = ecg["waveform"]
    sampling_rate = ecg["sampling_rate"]
    
    # Validate waveform is a list
    if not isinstance(waveform, list):
        return False, "ECG waveform must be a list"
    
    # Validate waveform length (at least 0.5 seconds of data)
    min_samples = sampling_rate * 0.5
    if len(waveform) < min_samples:
        return False, f"ECG waveform too short: {len(waveform)} samples (expected at least {min_samples})"
    
    # Validate waveform length (max 10 seconds to avoid huge data)
    max_samples = sampling_rate * 10
    if len(waveform) > max_samples:
        return False, f"ECG waveform too long: {len(waveform)} samples (max {max_samples})"
    
    # Validate sampling rate (50-1000 Hz)
    if not (50 <= sampling_rate <= 1000):
        return False, f"Invalid sampling rate: {sampling_rate} Hz (expected 50-1000 Hz)"
    
    # Validate waveform values are numeric
    try:
        for i, value in enumerate(waveform):
            if not isinstance(value, (int, float)):
                return False, f"ECG waveform contains non-numeric value at index {i}: {value}"
            # Reasonable range check (-10 to +10 mV)
            if not (-10 <= value <= 10):
                return False, f"ECG value out of range at index {i}: {value} (expected -10 to +10)"
    except Exception as e:
        return False, f"Error validating ECG waveform: {str(e)}"
    
    # Validate quality field if present
    if "quality" in ecg:
        valid_qualities = ["good", "fair", "poor"]
        if ecg["quality"] not in valid_qualities:
            return False, f"Invalid ECG quality: {ecg['quality']} (expected one of {valid_qualities})"
    
    return True, None


def validate_device_type(device_type: str) -> bool:
    """Validate device type is either 'wrist' or 'chest'."""
    return device_type in ["wrist", "chest"]


def validate_user_role(role: str) -> bool:
    """Validate accepted internal user-role values."""
    return role in ["admin"]


def validate_alert_severity(severity: str) -> bool:
    """Validate alert severity level."""
    return severity in ["info", "warning", "critical"]
