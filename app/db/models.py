import uuid
from enum import Enum
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, ForeignKey, Integer, String,
    Text, DateTime, Enum as SQLEnum, LargeBinary,
    Float, Table
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship

from app.db.base import Base


class MessageType(str, Enum):
    """Message types enum."""
    USER = "user"
    AI = "ai"
    SYSTEM = "system"


class MessageStatus(str, Enum):
    """Message status enum."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReactionType(str, Enum):
    """Reaction types enum."""
    LIKE = "like"
    DISLIKE = "dislike"


class FileType(str, Enum):
    """File types enum."""
    TEXT = "text"
    IMAGE = "image"
    PDF = "pdf"
    WORD = "word"
    EXCEL = "excel"
    OTHER = "other"


class User(Base):
    """User model."""
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    chats = relationship("Chat", back_populates="user", cascade="all, delete-orphan")
    files = relationship("File", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username}>"


class Chat(Base):
    """Chat model."""
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    categories = Column(ARRAY(String), default=[])
    subcategories = Column(ARRAY(String), default=[])
    # NEW: suggestions to show quick reply buttons on the frontend
    suggestions = Column(ARRAY(String), default=[])

    # Relationships
    user = relationship("User", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan",
                            order_by="Message.created_at")

    def __repr__(self):
        return f"<Chat {self.title}>"


class Message(Base):
    """Message model."""
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chat.id"), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(SQLEnum(MessageType), nullable=False)
    status = Column(SQLEnum(MessageStatus), nullable=False, default=MessageStatus.COMPLETED)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    chat = relationship("Chat", back_populates="messages")
    files = relationship("MessageFile", back_populates="message", cascade="all, delete-orphan")
    reactions = relationship("Reaction", back_populates="message", cascade="all, delete-orphan")
    sources = relationship("Source", back_populates="message", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Message {self.id} {self.message_type}>"


class Reaction(Base):
    """Reaction model for message feedback."""
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("message.id"), nullable=False)
    reaction_type = Column(SQLEnum(ReactionType), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    message = relationship("Message", back_populates="reactions")

    def __repr__(self):
        return f"<Reaction {self.reaction_type} for {self.message_id}>"


class File(Base):
    """File model for uploaded files."""
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    name = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    path = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=False)
    file_type = Column(SQLEnum(FileType), nullable=False, default=FileType.OTHER)
    content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="files")
    message_files = relationship("MessageFile", back_populates="file", cascade="all, delete-orphan")
    preview = relationship("FilePreview", back_populates="file", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<File {self.name}>"


class FilePreview(Base):
    """File preview model."""
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("file.id"), nullable=False, unique=True)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    file = relationship("File", back_populates="preview")

    def __repr__(self):
        return f"<FilePreview for {self.file_id}>"


class MessageFile(Base):
    """Association table for Message and File."""
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("message.id"), nullable=False)
    file_id = Column(UUID(as_uuid=True), ForeignKey("file.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    message = relationship("Message", back_populates="files")
    file = relationship("File", back_populates="message_files", lazy="joined")

    @property
    def name(self):
        return self.file.name if self.file else "Unknown File"

    @property
    def file_type(self):
        return self.file.file_type.value if self.file else "OTHER"

    @property
    def preview_url(self):
        if self.file and hasattr(self.file, 'preview') and self.file.preview:
            return f"/api/files/{self.file_id}/preview"
        return None

    def __repr__(self):
        return f"<MessageFile {self.message_id} - {self.file_id}>"


class Source(Base):
    """Source model for message sources."""
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("message.id"), nullable=False)
    title = Column(String, nullable=False)
    url = Column(String, nullable=True)
    content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    message = relationship("Message", back_populates="sources")

    def __repr__(self):
        return f"<Source {self.title} for {self.message_id}>"
