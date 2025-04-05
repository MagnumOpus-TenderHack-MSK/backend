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
        # Log all incoming parameters for debugging
        logger.info(f"save_completed_message called for message_id: {message_id}")
        logger.info(f"Content length: {len(content)}")
        logger.debug(f"Content preview: {content[:100]}..." if len(content) > 100 else f"Content: {content}")

        if sources:
            logger.info(f"Sources provided: {len(sources)}")
            logger.debug(f"First source: {json.dumps(sources[0], default=str)}" if sources else "No sources")

        # Get the message from database to verify it exists
        message = db.query(Message).filter(Message.id == message_id).first()
        if not message:
            logger.error(f"Message {message_id} not found in database")
            return None

        # Update message in database
        try:
            message = update_ai_message(
                db=db,
                message_id=message_id,
                content=content,
                status=MessageStatus.COMPLETED,
                sources=sources
            )
            logger.info(f"Message {message_id} saved successfully")

            # Log chat information for context
            logger.info(f"Message belongs to chat {message.chat_id}")

            return message_id
        except Exception as e:
            logger.error(f"Error updating message in database: {str(e)}", exc_info=True)
            raise

    except Exception as e:
        logger.error(f"Error saving message {message_id}: {str(e)}", exc_info=True)
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
        logger.error(f"Error updating message {message_id} status: {str(e)}", exc_info=True)
        return None

    finally:
        db.close()


async def save_message_chunk_to_redis(message_id: str, chunk: str) -> bool:
    """
    Save a message chunk to Redis.
    This appends the new chunk to any existing content for this message.
    """
    try:
        redis = Redis.from_url(settings.REDIS_URL)

        # Create Redis key for this message
        redis_key = f"message:{message_id}"

        # Append chunk to message content
        await redis.append(redis_key, chunk)

        # Set expiration (1 hour)
        await redis.expire(redis_key, 3600)

        # Also store a timestamp of the last update for this message
        timestamp_key = f"message:{message_id}:last_updated"
        timestamp = await redis.time()
        await redis.set(timestamp_key, int(timestamp[0]))
        await redis.expire(timestamp_key, 3600)

        await redis.close()

        return True

    except Exception as e:
        logger.error(f"Error saving message chunk to Redis: {str(e)}", exc_info=True)
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

        if content:
            return content.decode('utf-8')
        else:
            logger.warning(f"No content found in Redis for message {message_id}")
            return ""

    except Exception as e:
        logger.error(f"Error getting message content from Redis: {str(e)}", exc_info=True)
        return ""


async def check_in_progress_messages() -> List[Dict[str, Any]]:
    """
    Check for all in-progress messages in Redis.
    Returns a list of message IDs and their content.
    """
    try:
        redis = Redis.from_url(settings.REDIS_URL)

        # Get all message keys
        keys = await redis.keys("message:*")

        # Filter out timestamp keys
        message_keys = [key for key in keys if b":last_updated" not in key]

        result = []
        for key in message_keys:
            message_id = key.decode('utf-8').replace("message:", "")
            content = await redis.get(key)

            # Get the last updated timestamp if available
            timestamp_key = f"message:{message_id}:last_updated"
            timestamp = await redis.get(timestamp_key)
            last_updated = int(timestamp.decode('utf-8')) if timestamp else None

            if content:
                result.append({
                    "message_id": message_id,
                    "content": content.decode('utf-8'),
                    "last_updated": last_updated
                })

        await redis.close()
        return result

    except Exception as e:
        logger.error(f"Error checking in-progress messages: {str(e)}", exc_info=True)
        return []


async def clean_old_messages(older_than_seconds: int = 3600) -> int:
    """
    Clean up old message content from Redis.
    Returns the number of keys removed.
    """
    try:
        redis = Redis.from_url(settings.REDIS_URL)

        # Get current server time
        current_time = int(redis.time()[0])

        # Get all timestamp keys
        keys = await redis.keys("message:*:last_updated")

        removed = 0
        for key in keys:
            timestamp = await redis.get(key)

            if timestamp:
                last_updated = int(timestamp.decode('utf-8'))

                # If older than the specified time
                if current_time - last_updated > older_than_seconds:
                    # Extract message ID
                    message_id = key.decode('utf-8').split(':')[1]

                    # Delete message content and timestamp
                    content_key = f"message:{message_id}"
                    await redis.delete(content_key)
                    await redis.delete(key)

                    removed += 1

        await redis.close()
        return removed

    except Exception as e:
        logger.error(f"Error cleaning old messages: {str(e)}", exc_info=True)
        return 0