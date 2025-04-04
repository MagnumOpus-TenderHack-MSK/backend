from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema."""
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool = True


class UserCreate(UserBase):
    """User creation schema."""
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    """User update schema."""
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)
    is_active: Optional[bool] = None


class UserInDBBase(UserBase):
    """Base schema for User in DB."""
    id: UUID
    created_at: datetime
    updated_at: datetime
    is_admin: bool = False

    class Config:
        from_attributes = True
        from_attributes = True


class User(UserInDBBase):
    """User schema to return to client."""
    pass


class UserInDB(UserInDBBase):
    """User schema with password hash."""
    hashed_password: str