from typing import List, Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, root_validator, validator

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
        arbitrary_types_allowed = True


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
        arbitrary_types_allowed = True

    @classmethod
    def from_orm(cls, obj):
        """Custom from_orm to handle files."""
        # Create a dict for normal fields
        obj_dict = {}
        for field in cls.__fields__:
            if field != 'files' and hasattr(obj, field):
                obj_dict[field] = getattr(obj, field)

        # Process files separately
        if hasattr(obj, 'files') and obj.files:
            files_data = []
            for file_ref in obj.files:
                if hasattr(file_ref, 'file') and file_ref.file:
                    file_data = {
                        'id': file_ref.file_id,
                        'name': file_ref.file.name,
                        'file_type': file_ref.file.file_type.value,
                    }
                    # Add preview URL if available
                    if hasattr(file_ref.file, 'preview') and file_ref.file.preview:
                        file_data['preview_url'] = f"/api/files/{file_ref.file_id}/preview"
                    files_data.append(file_data)
            obj_dict['files'] = files_data

        return cls(**obj_dict)


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