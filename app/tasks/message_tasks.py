import json
import logging
from typing import Dict, Any, List, Optional
from uuid import UUID

from celery import shared_task
from redis.asyncio import Redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import Message, MessageStatus, Source
from app.services.chat_service import update_ai_message

# Set up logging
logger = logging.getLogger(__name__)


@shared_task
def save_completed_message(message_id: str, content: str, sources: Optional[List[Dict[str, Any]]] = None) -> Optional[
    str]:
    """
    Save a completed AI message to the database.

    This task:
    1. Updates the message content and status
    2. Adds sources if available
    """
    db = SessionLocal()
    try:
        # Update message in database
        message = update_ai_message(
            db=db,
            message_id=message_id,
            content=content,
            status=MessageStatus.COMPLETED,
            sources=sources
        )

        logger.info(f"Message {message_id} saved successfully")
        return message_id

    except Exception as e:
        logger.error(f"Error saving message {message_id}: {str(e)}")
        return None

    finally:
        db.close()


@shared_task
def update_message_status(message_id: str, status: str) -> Optional[str]:
    """
    Update message status.
    """
    db = SessionLocal()
    try:
        # Get message from database
        message = db.query(Message).filter(Message.id == message_id).first()

        if not message:
            logger.error(f"Message {message_id} not found")
            return None

        # Update status
        message.status = MessageStatus(status)
        db.commit()

        logger.info(f"Message {message_id} status updated to {status}")
        return message_id

    except Exception as e:
        logger.error(f"Error updating message {message_id} status: {str(e)}")
        return None

    finally:
        db.close()


async def save_message_chunk_to_redis(message_id: str, chunk: str) -> bool:
    """
    Save a message chunk to Redis.
    """
    try:
        redis = Redis.from_url(settings.REDIS_URL)

        # Create Redis key for this message
        redis_key = f"message:{message_id}"

        # Append chunk to message content
        await redis.append(redis_key, chunk)

        # Set expiration (1 hour)
        await redis.expire(redis_key, 3600)

        await redis.close()

        return True

    except Exception as e:
        logger.error(f"Error saving message chunk to Redis: {str(e)}")
        return False


async def get_message_content_from_redis(message_id: str) -> str:
    """
    Get the complete message content from Redis.
    """
    try:
        redis = Redis.from_url(settings.REDIS_URL)

        # Create Redis key for this message
        redis_key = f"message:{message_id}"

        # Get message content
        content = await redis.get(redis_key)

        await redis.close()

        return content.decode('utf-8') if content else ""

    except Exception as e:
        logger.error(f"Error getting message content from Redis: {str(e)}")
        return ""