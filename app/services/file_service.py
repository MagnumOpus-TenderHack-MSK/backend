import os
import uuid
import mimetypes
from typing import List, Optional, Dict, Any
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import File, FileType, FilePreview, User


def get_file_type(mime_type: str) -> FileType:
    """
    Determine file type from MIME type.
    """
    if mime_type.startswith('text/'):
        return FileType.TEXT
    elif mime_type.startswith('image/'):
        return FileType.IMAGE
    elif mime_type == 'application/pdf':
        return FileType.PDF
    elif mime_type in [
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/msword'
    ]:
        return FileType.WORD
    elif mime_type in [
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-excel'
    ]:
        return FileType.EXCEL
    else:
        return FileType.OTHER


def save_upload_file(upload_file: UploadFile, upload_dir: Path) -> Dict[str, Any]:
    """
    Save an uploaded file to disk.
    """
    # Generate a unique filename
    filename = f"{uuid.uuid4()}{os.path.splitext(upload_file.filename)[1]}"
    file_path = upload_dir / filename

    # Ensure directory exists
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Determine MIME type
    content_type = upload_file.content_type
    if not content_type:
        content_type = mimetypes.guess_type(upload_file.filename)[0] or 'application/octet-stream'

    # Save file to disk
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(upload_file.file.read())
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not save file: {str(e)}"
        )

    # Get file size
    file_size = os.path.getsize(file_path)

    return {
        "filename": filename,
        "original_name": upload_file.filename,
        "path": str(file_path),
        "size": file_size,
        "mime_type": content_type,
        "file_type": get_file_type(content_type)
    }


def create_file(db: Session, user: User, file_data: Dict[str, Any]) -> File:
    """
    Create a file record in the database.
    """
    # Create file record
    file_record = File(
        user_id=user.id,
        name=file_data["filename"],
        original_name=file_data["original_name"],
        path=file_data["path"],
        size=file_data["size"],
        mime_type=file_data["mime_type"],
        file_type=file_data["file_type"]
    )

    db.add(file_record)
    db.commit()
    db.refresh(file_record)

    return file_record


def get_file(db: Session, file_id: UUID) -> Optional[File]:
    """
    Get a file by ID.
    """
    return db.query(File).filter(File.id == file_id).first()


def get_user_files(db: Session, user_id: UUID, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
    """
    Get all files for a user with pagination.
    """
    # Get files with count
    total = db.query(File).filter(File.user_id == user_id).count()
    files = db.query(File).filter(File.user_id == user_id).order_by(File.created_at.desc()).offset(skip).limit(
        limit).all()

    return {
        "items": files,
        "total": total
    }


def save_file_preview(db: Session, file_id: UUID, preview_data: bytes) -> FilePreview:
    """
    Save file preview image.
    """
    # Check if file exists
    file = get_file(db, file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # Check if preview already exists
    existing_preview = db.query(FilePreview).filter(FilePreview.file_id == file_id).first()
    if existing_preview:
        existing_preview.data = preview_data
        db.commit()
        return existing_preview

    # Create new preview
    preview = FilePreview(
        file_id=file_id,
        data=preview_data
    )

    db.add(preview)
    db.commit()
    db.refresh(preview)

    return preview


def update_file_content(db: Session, file_id: UUID, content: str, file_type: FileType = None) -> File:
    """
    Update file content and optionally file type.
    """
    # Check if file exists
    file = get_file(db, file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # Update file content and type
    file.content = content
    if file_type:
        file.file_type = file_type

    db.commit()
    db.refresh(file)

    return file


def get_file_preview_url(file_id: UUID) -> str:
    """
    Get preview URL for a file.
    """
    return f"/api/files/{file_id}/preview"


def get_file_download_url(file_id: UUID) -> str:
    """
    Get download URL for a file.
    """
    return f"/api/files/{file_id}/download"