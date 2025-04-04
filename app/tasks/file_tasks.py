import base64
import json
import logging
import requests
from io import BytesIO
from typing import Dict, Any, Optional
from urllib.parse import urljoin
from uuid import UUID

from celery import shared_task
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import File, FileType
from app.services.file_service import update_file_content, save_file_preview

# Set up logging
logger = logging.getLogger(__name__)


def sanitize_content(content: str) -> str:
    """
    Sanitize extracted text content.
    """
    # Simple sanitization for now
    if not content:
        return ""

    return content.strip()


@shared_task
def process_file(file_id: str) -> Optional[str]:
    """
    Process a file using the preview service.
    """
    db = SessionLocal()
    try:
        # Get file from database
        file = db.query(File).filter(File.id == file_id).first()

        if not file:
            logger.error(f"File {file_id} not found")
            return None

        # Prepare request to preview service
        api_url = urljoin(settings.PREVIEW_SERVICE_URL, "/process_file/")

        try:
            # Open file
            with open(file.path, "rb") as f:
                files = {"file": (file.original_name, f)}

                # Set headers
                headers = {
                    "X-API-Key": settings.PREVIEW_SERVICE_API_KEY,
                    "Accept": "application/json",
                }

                # Send request with timeout
                response = requests.post(api_url, files=files, headers=headers, timeout=60)

                if response.status_code != 200:
                    logger.error(f"Failed to process file {file_id}: {response.text}")
                    return None

                # Process response
                result = response.json()

                # Update file type
                file_type = FileType(result["file_type"]) if "file_type" in result else None

                # Update file content
                file = update_file_content(
                    db=db,
                    file_id=file.id,
                    content=sanitize_content(result.get("content", "")),
                    file_type=file_type
                )

                # Save preview if available
                if result.get("preview"):
                    try:
                        image_data = base64.b64decode(result["preview"])
                        save_file_preview(db=db, file_id=file.id, preview_data=image_data)
                    except Exception as e:
                        logger.error(f"Error saving preview for file {file_id}: {str(e)}")

                logger.info(f"File {file_id} processed successfully")
                return file_id

        except requests.RequestException as e:
            logger.error(f"Request error processing file {file_id}: {str(e)}")
            return None
        except IOError as e:
            logger.error(f"IO error processing file {file_id}: {str(e)}")
            return None

    except Exception as e:
        logger.error(f"Error processing file {file_id}: {str(e)}", exc_info=True)
        return None

    finally:
        db.close()