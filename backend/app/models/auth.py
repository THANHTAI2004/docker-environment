"""
Authentication and authorization models.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Credential payload used to exchange for a JWT."""
    user_id: str
    password: str = Field(..., min_length=8)


class TokenResponse(BaseModel):
    """JWT response returned after a successful login."""
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user_id: str
    role: str
    scopes: List[str] = Field(default_factory=list)


class AuthenticatedUser(BaseModel):
    """Minimal identity shape used by route authorization."""
    user_id: str
    role: str
    auth_type: str = "jwt"
    caregivers: List[str] = Field(default_factory=list)
    is_active: bool = True
    email: Optional[str] = None
