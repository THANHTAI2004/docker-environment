"""
Phone number normalization utilities.
"""
import re


_PHONE_CLEANUP_PATTERN = re.compile(r"[\s().-]+")


def normalize_phone_number(phone: str) -> str:
    """
    Normalize Vietnamese phone numbers into E.164-like ``+84...`` format.

    Accepted examples:
    - 0987654321 -> +84987654321
    - 84987654321 -> +84987654321
    - +84987654321 -> +84987654321
    """
    if not isinstance(phone, str) or not phone.strip():
        raise ValueError("Phone number is required")

    cleaned = _PHONE_CLEANUP_PATTERN.sub("", phone.strip())
    if cleaned.startswith("+"):
        prefix = "+"
        digits = cleaned[1:]
    else:
        prefix = ""
        digits = cleaned

    if not digits.isdigit():
        raise ValueError("Phone number must contain digits only")

    normalized = f"{prefix}{digits}"
    if normalized.startswith("+84"):
        national_number = normalized[3:]
    elif normalized.startswith("84"):
        national_number = normalized[2:]
    elif normalized.startswith("0"):
        national_number = normalized[1:]
    else:
        raise ValueError("Phone number must start with 0, 84, or +84")

    if not national_number or not national_number.isdigit():
        raise ValueError("Invalid phone number")
    if len(national_number) not in (9, 10):
        raise ValueError("Phone number must contain 9 or 10 digits after the country code")
    if national_number.startswith("0"):
        raise ValueError("Phone number contains an extra leading zero")

    return f"+84{national_number}"
