from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_active_user
from app.db.session import get_db
from app.db.models import User
from app.schemas.file import FileUploadResponse, FileList, File as FileSchema
from app.services import file_service
from app.tasks.file_tasks import process_file

router = APIRouter(prefix="/files", tags=["Files"])


@router.get("", response_model=FileList)
def get_files(
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """
    Get all files for the current user.
    """
    files = file_service.get_user_files(
        db=db,
        user_id=current_user.id,
        skip=skip,
        limit=limit
    )
    return files


@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """
    Upload a file.
    """
    # Check file size
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset to beginning

    if file_size > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE} bytes"
        )

    # Save file
    file_data = file_service.save_upload_file(file, settings.UPLOAD_PATH)

    # Create file record in DB
    file_record = file_service.create_file(db, current_user, file_data)

    # Process file asynchronously
    process_file.delay(str(file_record.id))

    # Add preview URL
    preview_url = file_service.get_file_preview_url(file_record.id)

    # Create response
    response = {
        "id": file_record.id,
        "name": file_record.name,
        "original_name": file_record.original_name,
        "file_type": file_record.file_type,
        "mime_type": file_record.mime_type,
        "size": file_record.size,
        "preview_url": preview_url
    }

    return response


@router.post("/upload-multiple", response_model=List[FileUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_multiple_files(
        files: List[UploadFile] = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """
    Upload multiple files.
    """
    responses = []

    for file in files:
        # Check file size
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Reset to beginning

        if file_size > settings.MAX_UPLOAD_SIZE:
            # Skip files that are too large
            continue

        # Save file
        file_data = file_service.save_upload_file(file, settings.UPLOAD_PATH)

        # Create file record in DB
        file_record = file_service.create_file(db, current_user, file_data)

        # Process file asynchronously
        process_file.delay(str(file_record.id))

        # Add preview URL
        preview_url = file_service.get_file_preview_url(file_record.id)

        # Create response
        response = {
            "id": file_record.id,
            "name": file_record.name,
            "original_name": file_record.original_name,
            "file_type": file_record.file_type,
            "mime_type": file_record.mime_type,
            "size": file_record.size,
            "preview_url": preview_url
        }

        responses.append(response)

    return responses


@router.get("/{file_id}", response_model=FileSchema)
def get_file(
        file_id: UUID,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """
    Get a specific file by ID.
    """
    file = file_service.get_file(db, file_id)

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # Check if user has access to this file
    if file.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden"
        )

    # Add preview URL
    preview_url = file_service.get_file_preview_url(file.id)

    # Convert to schema
    file_schema = FileSchema.from_orm(file)

    # Manually add preview URL (not in DB model)
    file_dict = file_schema.dict()
    file_dict["preview_url"] = preview_url

    return FileSchema(**file_dict)


@router.get("/{file_id}/download")
def download_file(
        file_id: UUID,
        db: Session = Depends(get_db)
):
    """
    Download a file. Public route - no authentication required.
    """
    file = file_service.get_file(db, file_id)

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    return FileResponse(
        path=file.path,
        filename=file.original_name,
        media_type=file.mime_type
    )


@router.get("/{file_id}/preview")
def get_file_preview(
        file_id: UUID,
        db: Session = Depends(get_db)
):
    """
    Get file preview image. Public route - no authentication required.
    """
    file = file_service.get_file(db, file_id)

    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )

    # Check if preview exists
    if not file.preview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preview not available"
        )

    return Response(
        content=file.preview.data,
        media_type="image/jpeg"
    )