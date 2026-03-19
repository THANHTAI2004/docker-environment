"""
Authentication models for end-user sessions and internal admin access.
"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """Registration payload for end-user self-signup."""
    name: str = Field(..., min_length=2, max_length=100)
    phone_number: str = Field(..., min_length=9, max_length=15)
    date_of_birth: date
    password: str = Field(..., min_length=8)


class PhoneLoginRequest(BaseModel):
    """Preferred credential payload used to login with a phone number."""
    phone_number: str = Field(..., min_length=9, max_length=15)
    password: str = Field(..., min_length=8)


class TokenResponse(BaseModel):
    """JWT response returned after a successful login."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime
    refresh_expires_at: datetime
    session_id: str
    user_id: str


class RefreshRequest(BaseModel):
    """Refresh-token payload used to rotate a session."""
    refresh_token: str = Field(..., min_length=32)


class LogoutResponse(BaseModel):
    """Response returned after a successful logout."""
    status: str = "success"
    session_id: str


class AuthenticatedUser(BaseModel):
    """Minimal identity shape used by route authorization."""
    user_id: str
    auth_type: str = "jwt"
    session_id: str
    caregivers: List[str] = Field(default_factory=list)
    is_active: bool = True
    is_system_admin: bool = False
    role: Optional[str] = Field(default=None, description="Internal system role for admin accounts only.")
    email: Optional[str] = None
    phone_number: Optional[str] = None
    date_of_birth: Optional[str] = None
