from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.user import User as UserSchema # Import base User schema
from app.schemas.chat import Message as MessageSchema # Import base Message schema

# --- Schemas for Admin Responses ---

class AdminChatUser(BaseModel):
    """Simplified User schema for AdminChat list."""
    id: UUID
    username: Optional[str] = None
    email: Optional[str] = None

    class Config:
        from_attributes = True

class AdminChat(BaseModel):
    """Schema for representing a chat in the admin chat list."""
    id: UUID
    title: str
    user: Optional[AdminChatUser] = None # Use simplified user schema
    categories: List[str] = Field(default_factory=list)
    subcategories: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    likes: int = 0
    dislikes: int = 0

    class Config:
        from_attributes = True


# --- Schemas for Admin Chat Detail ---

class AdminFileReference(BaseModel):
    """Simplified File reference for Admin Chat Detail."""
    id: UUID
    name: Optional[str] = None
    file_type: Optional[str] = None
    preview_url: Optional[str] = None # URL generated by frontend/backend logic

    class Config:
        from_attributes = True
        # Custom from_orm to construct preview_url if needed elsewhere,
        # but for now endpoint generates it directly.


class AdminReaction(BaseModel):
    """Simplified Reaction for Admin Chat Detail."""
    id: UUID
    reaction_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class AdminMessage(MessageSchema): # Inherit from base message schema
    """Message schema tailored for Admin Chat Detail view."""
    # Override files and reactions with simplified versions if needed,
    # but inheriting MessageSchema which uses FileReference and Reaction should work
    # if FileReference/Reaction provide the needed fields.
    # Let's use the inherited ones first.
    pass


class AdminChatDetail(BaseModel):
    """Detailed schema for a single chat view in admin."""
    id: UUID
    title: str
    user: Optional[UserSchema] = None # Use full User schema here
    categories: List[str] = Field(default_factory=list)
    subcategories: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    messages: List[AdminMessage] = Field(default_factory=list) # Use potentially modified message schema

    class Config:
        from_attributes = True


# --- Admin User Schema ---
class AdminUser(UserSchema): # Inherit from base User schema
    """User schema for admin user list/detail."""
    pass # For now, it's the same as the standard user schema


# --- Generic Paginated Response ---
from typing import TypeVar, Generic

T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema."""
    items: List[T]
    total: int