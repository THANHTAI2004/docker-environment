"""
ECG signal processing utilities.
Basic signal quality assessment and feature extraction.
"""
from typing import List, Dict, Any, Optional


def calculate_ecg_quality(waveform: List[float], sampling_rate: int) -> str:
    """
    Assess ECG signal quality based on simple heuristics.
    
    Returns:
        "good", "fair", or "poor"
    """
    if not waveform:
        return "poor"
    
    # Calculate basic statistics
    mean = sum(waveform) / len(waveform)
    
    # Calculate variance
    variance = sum((x - mean) ** 2 for x in waveform) / len(waveform)
    std_dev = variance ** 0.5
    
    # Check for flat signal (poor quality)
    if std_dev < 0.01:
        return "poor"
    
    # Check for excessive noise (high variance)
    if std_dev > 5.0:
        return "poor"
    
    # Count zero crossings (baseline crossings)
    zero_crossings = 0
    for i in range(1, len(waveform)):
        if (waveform[i-1] - mean) * (waveform[i] - mean) < 0:
            zero_crossings += 1
    
    # Expected zero crossings for normal ECG (rough estimate)
    duration = len(waveform) / sampling_rate
    expected_hr = 70  # bpm
    expected_crossings = (expected_hr / 60) * duration * 4  # ~4 crossings per heartbeat
    
    # Too many or too few crossings indicates noise or poor signal
    crossing_ratio = zero_crossings / expected_crossings if expected_crossings > 0 else 0
    
    if 0.5 <= crossing_ratio <= 2.0:
        # Check standard deviation for good vs fair
        if 0.1 <= std_dev <= 2.0:
            return "good"
        else:
            return "fair"
    else:
        return "fair" if 0.2 <= crossing_ratio <= 3.0 else "poor"


def detect_lead_off(waveform: List[float], threshold: float = 0.05) -> bool:
    """
    Detect if ECG leads are disconnected.
    
    Lead-off is indicated by very low signal amplitude.
    
    Returns:
        True if lead is off, False otherwise
    """
    if not waveform:
        return True
    
    # Calculate peak-to-peak amplitude
    min_val = min(waveform)
    max_val = max(waveform)
    amplitude = max_val - min_val
    
    # If amplitude is below threshold, leads are likely off
    return amplitude < threshold


def estimate_heart_rate_from_ecg(waveform: List[float], sampling_rate: int) -> Optional[int]:
    """
    Estimate heart rate from ECG waveform using simple peak detection.
    
    This is a basic implementation. For production, use more robust algorithms.
    
    Returns:
        Estimated heart rate in bpm, or None if cannot be determined
    """
    if not waveform or len(waveform) < sampling_rate:
        return None
    
    # Simple peak detection
    mean = sum(waveform) / len(waveform)
    std_dev = (sum((x - mean) ** 2 for x in waveform) / len(waveform)) ** 0.5
    
    # Threshold for peak detection (mean + 1.5 * std_dev)
    threshold = mean + 1.5 * std_dev
    
    # Find peaks
    peaks = []
    for i in range(1, len(waveform) - 1):
        # Local maximum above threshold
        if (waveform[i] > waveform[i-1] and 
            waveform[i] > waveform[i+1] and 
            waveform[i] > threshold):
            peaks.append(i)
    
    if len(peaks) < 2:
        return None
    
    # Calculate average interval between peaks
    intervals = []
    for i in range(1, len(peaks)):
        interval = (peaks[i] - peaks[i-1]) / sampling_rate  # in seconds
        # Filter out unrealistic intervals (too fast or too slow)
        if 0.3 <= interval <= 2.0:  # 30-200 bpm range
            intervals.append(interval)
    
    if not intervals:
        return None
    
    # Calculate heart rate
    avg_interval = sum(intervals) / len(intervals)
    heart_rate = 60 / avg_interval  # Convert to bpm
    
    # Sanity check
    if 30 <= heart_rate <= 200:
        return int(round(heart_rate))
    
    return None


def calculate_ecg_features(waveform: List[float], sampling_rate: int) -> Dict[str, Any]:
    """
    Extract basic ECG features for analysis.
    
    Returns:
        Dictionary with ECG features
    """
    if not waveform:
        return {}
    
    features = {
        "quality": calculate_ecg_quality(waveform, sampling_rate),
        "lead_off": detect_lead_off(waveform),
        "duration": len(waveform) / sampling_rate,
        "sampling_rate": sampling_rate,
        "sample_count": len(waveform),
    }
    
    # Add heart rate estimate
    hr = estimate_heart_rate_from_ecg(waveform, sampling_rate)
    if hr:
        features["estimated_hr"] = hr
    
    # Add amplitude statistics
    features["amplitude"] = {
        "min": min(waveform),
        "max": max(waveform),
        "mean": sum(waveform) / len(waveform),
        "peak_to_peak": max(waveform) - min(waveform)
    }
    
    return features
