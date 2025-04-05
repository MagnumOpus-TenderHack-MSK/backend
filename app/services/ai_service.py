import json
import requests
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
from uuid import UUID

from app.core.config import settings
from app.db.models import Message, MessageType

logger = logging.getLogger(__name__)


def prepare_conversation_history(messages: List[Message]) -> List[Dict[str, Any]]:
    """
    Prepare conversation history for AI service.

    Convert database message objects to the format expected by the AI service.
    """
    history = []

    for message in messages:
        # Skip messages that are not user or AI
        if message.message_type not in [MessageType.USER, MessageType.AI]:
            continue

        # Convert message to dict
        message_dict = {
            "role": "user" if message.message_type == MessageType.USER else "assistant",
            "content": message.content
        }

        history.append(message_dict)

    return history


def send_to_ai_service(
        message_content: str,
        conversation_history: List[Dict[str, Any]],
        callback_url: str
) -> bool:
    """
    Send a message to the AI service for processing.

    Returns True if the request was successful, False otherwise.
    """
    # Check if the last message is already included in the history
    # If not, add the current message to the history
    should_add_message = True
    if conversation_history:
        for msg in conversation_history[-3:]:  # Check the last few messages
            if msg.get("role") == "user" and msg.get("content") == message_content:
                should_add_message = False
                break

    # Make a copy of the conversation history to avoid modifying the original
    messages = conversation_history.copy()

    # Add the current message if needed
    if should_add_message:
        messages.append({
            "role": "user",
            "content": message_content
        })

    # Prepare request data according to the API schema
    request_data = {
        "chat_history": {
            "messages": messages
        },
        "callback_url": callback_url,
        "max_tokens": getattr(settings, 'AI_SERVICE_MAX_TOKENS', 2000),
        "temperature": getattr(settings, 'AI_SERVICE_TEMPERATURE', 0.7),
        "stream_chunks": getattr(settings, 'AI_SERVICE_STREAM_CHUNKS', True)
    }

    # Prepare headers
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": settings.AI_SERVICE_API_KEY
    }

    try:
        # Construct the full API endpoint URL
        endpoint = f"{settings.AI_SERVICE_URL.rstrip('/')}/api/answer"

        logger.info(f"Sending request to AI service endpoint: {endpoint}")
        logger.info(f"With callback URL: {callback_url}")

        # Log detailed request data for debugging
        debug_data = request_data.copy()
        messages_count = len(debug_data["chat_history"]["messages"])
        logger.debug(f"Sending {messages_count} messages to AI service")
        logger.debug(f"Last message: {message_content[:100]}..." if len(
            message_content) > 100 else f"Last message: {message_content}")

        # Send request to AI service
        response = requests.post(
            endpoint,
            json=request_data,
            headers=headers,
            timeout=10  # Increase timeout for LLM service
        )

        # Log response status
        logger.info(f"AI service response status: {response.status_code}")

        # Check if request was successful
        if response.status_code == 200:
            try:
                response_data = response.json()
                request_id = response_data.get("request_id")
                status = response_data.get("status")

                logger.info(f"AI service request successful. Request ID: {request_id}, Status: {status}")
                return True
            except json.JSONDecodeError:
                logger.error("Failed to parse JSON response from AI service")
                logger.debug(f"Response content: {response.text[:200]}...")
                return False
        else:
            # Log error with detailed information
            logger.error(f"Error from AI service: Status {response.status_code}")
            try:
                error_content = response.text[:500]  # Limit size for log
                logger.error(f"Error response content: {error_content}")
            except Exception as e:
                logger.error(f"Could not get error content: {str(e)}")
            return False

    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error to AI service: {str(e)}", exc_info=True)
        return False
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout error contacting AI service: {str(e)}", exc_info=True)
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error to AI service: {str(e)}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending message to AI service: {str(e)}", exc_info=True)
        return False


def create_callback_url(
        host: str,
        chat_id: UUID,
        message_id: UUID
) -> str:
    """
    Create a callback URL for the AI service to send responses back.

    If CALLBACK_HOST is set in settings, use that instead of the provided host.
    """
    # Use the configured callback host if available, otherwise use the provided host
    base_url = settings.CALLBACK_HOST.rstrip('/') if settings.CALLBACK_HOST else host.rstrip('/')

    logger.info(f"Creating callback URL with base: {base_url}")

    # Create the callback path
    callback_path = f"/api/chats/{chat_id}/messages/{message_id}/callback"

    # Join the base URL and callback path
    callback_url = f"{base_url}{callback_path}"

    logger.info(f"Generated callback URL: {callback_url}")
    return callback_url


def check_answer_status(request_id: str) -> Dict[str, Any]:
    """
    Check the status of an answer request with the AI service.

    Args:
        request_id: The ID of the answer request

    Returns:
        Dict with status information
    """
    # Construct the full API endpoint URL
    endpoint = f"{settings.AI_SERVICE_URL.rstrip('/')}/api/answer/{request_id}"

    # Prepare headers
    headers = {
        "X-API-Key": settings.AI_SERVICE_API_KEY
    }

    try:
        logger.info(f"Checking answer status for request ID: {request_id}")

        # Send request to AI service
        response = requests.get(
            endpoint,
            headers=headers,
            timeout=5
        )

        # Check if request was successful
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Error checking answer status: {response.status_code} - {response.text}")
            return {"status": "error", "message": f"Failed to check status: {response.status_code}"}

    except Exception as e:
        logger.error(f"Exception checking answer status: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}