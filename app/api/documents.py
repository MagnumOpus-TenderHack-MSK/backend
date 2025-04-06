import logging
import os
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from pathlib import Path

from app.db.session import get_db
from app.db.models import Source

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)

# Define the references directory
REFERENCES_DIR = Path("static/references")

# Mapping for document names to directories
DOCUMENT_MAPPING = {
    # Document name variations (lowercase) -> directory name
    "инструкция_по_работе_с_порталом_для_поставщика": "инструкция_по_работе_с_порталом_для_поставщика",
    "инструкция по работе с порталом для поставщика": "инструкция_по_работе_с_порталом_для_поставщика",
    "инструкция_по_работе_с_порталом_для_поставщика.pdf": "инструкция_по_работе_с_порталом_для_поставщика",
    "инструкция_по_работе_с_порталом_для_заказчика": "инструкция_по_работе_с_порталом_для_заказчика",
    "инструкция по работе с порталом для заказчика": "инструкция_по_работе_с_порталом_для_заказчика",
    "инструкция_по_работе_с_порталом_для_заказчика.pdf": "инструкция_по_работе_с_порталом_для_заказчика",
    "инструкция_по_электронному_актированию": "инструкция_по_электронному_актированию",
    "инструкция по электронному актированию": "инструкция_по_электронному_актированию",
    "инструкция_по_электронному_актированию.pdf": "инструкция_по_электронному_актированию",
    "регламент_информационного_взаимодействия": "регламент_информационного_взаимодействия",
    "регламент информационного взаимодействия": "регламент_информационного_взаимодействия",
    "регламент_информационного_взаимодействия.pdf": "регламент_информационного_взаимодействия",
    "xlsx": "xlsx",
}

# Display names for documents
DOCUMENT_DISPLAY_NAMES = {
    "инструкция_по_работе_с_порталом_для_поставщика": "Инструкция по работе с порталом для поставщика",
    "инструкция_по_работе_с_порталом_для_заказчика": "Инструкция по работе с порталом для заказчика",
    "инструкция_по_электронному_актированию": "Инструкция по электронному актированию",
    "регламент_информационного_взаимодействия": "Регламент информационного взаимодействия",
    "xlsx": "Файл Excel"
}


def normalize_document_name(source_name: str) -> str:
    """
    Normalize a document name from the AI response to match our directory structure.
    """
    if not source_name:
        return ""

    # Convert to lowercase for case-insensitive matching
    name_lower = source_name.lower().strip()

    # Remove any "таблица из файла" prefix
    if "таблица из файла" in name_lower:
        name_lower = name_lower.replace("таблица из файла", "").strip()

    # Try direct mapping
    if name_lower in DOCUMENT_MAPPING:
        return DOCUMENT_MAPPING[name_lower]

    # Try partial matching if no exact match
    for key, value in DOCUMENT_MAPPING.items():
        if key in name_lower:
            return value

    # Return as is if no match found
    return name_lower


@router.get("/reference/{message_id}/{ref_num}")
async def get_reference_image(
        message_id: UUID,
        ref_num: str,
        db: Session = Depends(get_db)
):
    """
    Get a reference image for a document reference in a message.
    """
    try:
        # Find the source reference
        source = db.query(Source).filter(
            Source.message_id == message_id,
            Source.url == ref_num
        ).first()

        if not source:
            logger.warning(f"Reference {ref_num} not found for message {message_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reference not found"
            )

        # Parse the document information from the source
        source_title = source.title if source.title else ""
        page_number = None

        # Extract page number from content (expect format like "Page 9" or just the number)
        if source.content:
            if source.content.startswith("Page "):
                page_number = source.content.replace("Page ", "")
            else:
                page_number = source.content

        # Normalize the document name to match our directory structure
        document_dir = normalize_document_name(source_title)

        # Get display name for the document
        display_name = DOCUMENT_DISPLAY_NAMES.get(document_dir, source_title)

        # Determine file path based on whether it's a page in a directory
        logger.info(f"Looking for document: {document_dir}, page: {page_number}")

        if page_number and page_number.isdigit():
            # It's a page in a directory
            image_path = REFERENCES_DIR / document_dir / f"{page_number}.png"
            logger.info(f"Trying to access image at: {image_path}")
        else:
            # Assume it's a direct file reference
            image_path = REFERENCES_DIR / f"{document_dir}.png"

            # If the direct file doesn't exist, check for other formats
            if not image_path.exists():
                for ext in ['.pdf', '.xlsx', '.docx', '.jpg', '.jpeg']:
                    alt_path = REFERENCES_DIR / f"{document_dir}{ext}"
                    if alt_path.exists():
                        image_path = alt_path
                        break

        # Check if the file exists
        if image_path.exists():
            # For image files, return directly
            with open(image_path, "rb") as f:
                image_data = f.read()
                return Response(
                    content=image_data,
                    media_type="image/png" if str(image_path).endswith('.png') else "application/octet-stream"
                )
        else:
            # If file doesn't exist, create a placeholder image with error message
            logger.warning(f"Reference file not found: {image_path}")

            # Create a placeholder image
            width, height = 800, 300
            image = Image.new('RGB', (width, height), color=(255, 255, 255))
            draw = ImageDraw.Draw(image)

            # Draw header
            draw.rectangle([(0, 0), (width, 60)], fill=(47, 90, 168))

            # Try to get a font, use default if not available
            try:
                title_font = ImageFont.truetype("Arial", 24)
                body_font = ImageFont.truetype("Arial", 16)
            except:
                title_font = ImageFont.load_default()
                body_font = ImageFont.load_default()

            draw.text((20, 15), f"Ссылка [{source.url}]", font=title_font, fill=(255, 255, 255))

            # Draw error message
            draw.text((20, 80), f"Файл не найден: {image_path}", font=body_font, fill=(255, 0, 0))

            # Draw document information
            draw.text((20, 120), f"Документ: {display_name}", font=body_font, fill=(0, 0, 0))
            if page_number:
                draw.text((20, 150), f"Страница: {page_number}", font=body_font, fill=(0, 0, 0))

            # Add processing message
            draw.text((20, 200), "Документ еще обрабатывается. Пожалуйста, повторите попытку позже.",
                      font=body_font, fill=(0, 0, 0))

            # Add debug information
            draw.text((20, 230), f"Нормализованный путь: {document_dir}", font=body_font, fill=(100, 100, 100))
            draw.text((20, 260), f"Исходное название: {source_title}", font=body_font, fill=(100, 100, 100))

            # Convert image to bytes
            img_byte_arr = BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)

            return Response(content=img_byte_arr.getvalue(), media_type="image/png")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving reference image: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve reference image"
        )