from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel

from app.db.models import FileType


class FileBase(BaseModel):
    """Base file schema."""
    name: str
    original_name: str
    mime_type: str
    size: int
    file_type: FileType


class File(FileBase):
    """File schema."""
    id: UUID
    user_id: UUID
    path: str
    content: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    preview_url: Optional[str] = None

    class Config:
        from_attributes = True
        from_attributes = True


class FileUploadResponse(BaseModel):
    """File upload response schema."""
    id: UUID
    name: str
    original_name: str
    file_type: FileType
    mime_type: str
    size: int
    preview_url: Optional[str] = None


class FileList(BaseModel):
    """File list schema."""
    items: List[File]
    total: int