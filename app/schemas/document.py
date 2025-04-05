from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel

class DocumentReferenceBase(BaseModel):
    """Base document reference schema."""
    name: str
    num: Optional[int] = None
    path: str
    description: Optional[str] = None


class DocumentReferenceCreate(DocumentReferenceBase):
    """Document reference creation schema."""
    pass


class DocumentReferenceResponse(DocumentReferenceBase):
    """Document reference response schema."""
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True