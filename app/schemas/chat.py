from typing import List, Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from app.db.models import MessageType, MessageStatus, ReactionType


class SourceBase(BaseModel):
    """Base source schema."""
    title: str
    url: Optional[str] = None
    content: Optional[str] = None


class Source(SourceBase):
    """Source schema."""
    id: UUID
    message_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class ReactionBase(BaseModel):
    """Base reaction schema."""
    reaction_type: ReactionType


class Reaction(ReactionBase):
    """Reaction schema."""
    id: UUID
    message_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class FileReference(BaseModel):
    """File reference schema for messages."""
    id: UUID
    name: str
    file_type: str
    preview_url: Optional[str] = None

    class Config:
        from_attributes = True


class MessageBase(BaseModel):
    """Base message schema."""
    content: str
    message_type: MessageType


class MessageCreate(BaseModel):
    """Message creation schema."""
    content: str
    file_ids: Optional[List[UUID]] = None


class Message(MessageBase):
    """Message schema."""
    id: UUID
    chat_id: UUID
    status: MessageStatus
    created_at: datetime
    updated_at: datetime
    sources: Optional[List[Source]] = []
    files: Optional[List[FileReference]] = []
    reactions: Optional[List[Reaction]] = []

    class Config:
        from_attributes = True


class ChatBase(BaseModel):
    """Base chat schema."""
    title: str


class ChatCreate(BaseModel):
    """Chat creation schema."""
    title: str = Field(..., min_length=1, max_length=100)


class Chat(ChatBase):
    """Chat schema."""
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
    messages: Optional[List[Message]] = []

    class Config:
        from_attributes = True


class ChatList(BaseModel):
    """Chat list schema."""
    items: List[Chat]
    total: int


class MessageList(BaseModel):
    """Message list schema."""
    items: List[Message]
    total: int


class ReactionCreate(BaseModel):
    """Reaction creation schema."""
    reaction_type: ReactionType