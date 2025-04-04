from typing import Optional
from pydantic import BaseModel, EmailStr

from app.schemas.user import User


class Token(BaseModel):
    """Token schema."""
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Token payload schema."""
    sub: Optional[str] = None
    exp: Optional[int] = None


class LoginRequest(BaseModel):
    """Login request schema."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response schema."""
    access_token: str
    token_type: str = "bearer"
    user: User


class RegisterRequest(BaseModel):
    """Registration request schema."""
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class RegisterResponse(BaseModel):
    """Registration response schema."""
    access_token: str
    token_type: str = "bearer"
    user: User