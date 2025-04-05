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
    """
    history = []

    for message in messages:
        if message.message_type not in [MessageType.USER, MessageType.AI]:
            continue

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
) -> Dict[str, Any]:
    """
    Send a message to the AI service for processing.
    Returns a dictionary with the following keys:
      - success: bool
      - request_id: (if available)
      - status: AI service status
      - suggestions: list of suggestion strings
      - name: new chat name (if provided)
      - cluster: list of subclusters from the AI response
    """
    should_add_message = True
    if conversation_history:
        for msg in conversation_history[-3:]:
            if msg.get("role") == "user" and msg.get("content") == message_content:
                should_add_message = False
                break

    messages = conversation_history.copy()
    if should_add_message:
        messages.append({
            "role": "user",
            "content": message_content
        })

    request_data = {
        "chat_history": {
            "messages": messages
        },
        "callback_url": callback_url,
        "max_tokens": getattr(settings, 'AI_SERVICE_MAX_TOKENS', 2000),
        "temperature": getattr(settings, 'AI_SERVICE_TEMPERATURE', 0.7),
        "stream_chunks": getattr(settings, 'AI_SERVICE_STREAM_CHUNKS', True)
    }

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": settings.AI_SERVICE_API_KEY
    }

    try:
        endpoint = f"{settings.AI_SERVICE_URL.rstrip('/')}/api/answer"
        logger.info(f"Sending request to AI service endpoint: {endpoint}")
        logger.info(f"With callback URL: {callback_url}")

        response = requests.post(
            endpoint,
            json=request_data,
            headers=headers,
            timeout=10
        )

        logger.info(f"AI service response status: {response.status_code}")

        if response.status_code == 200:
            try:
                response_data = response.json()
                return {
                    "success": True,
                    "request_id": response_data.get("request_id"),
                    "status": response_data.get("status"),
                    "suggestions": response_data.get("suggestions", []),
                    "name": response_data.get("name"),
                    "cluster": response_data.get("cluster", [])
                }
            except json.JSONDecodeError:
                logger.error("Failed to parse JSON response from AI service")
                logger.debug(f"Response content: {response.text[:200]}...")
                return {"success": False}
        else:
            logger.error(f"Error from AI service: Status {response.status_code}")
            try:
                error_content = response.text[:500]
                logger.error(f"Error response content: {error_content}")
            except Exception as e:
                logger.error(f"Could not get error content: {str(e)}")
            return {"success": False}

    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error to AI service: {str(e)}", exc_info=True)
        return {"success": False}
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout error contacting AI service: {str(e)}", exc_info=True)
        return {"success": False}
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error to AI service: {str(e)}", exc_info=True)
        return {"success": False}
    except Exception as e:
        logger.error(f"Unexpected error sending message to AI service: {str(e)}", exc_info=True)
        return {"success": False}




def create_callback_url(
        host: str,
        chat_id: UUID,
        message_id: UUID
) -> str:
    """
    Create a callback URL for the AI service to send responses back.
    """
    base_url = settings.CALLBACK_HOST.rstrip('/') if settings.CALLBACK_HOST else host.rstrip('/')
    logger.info(f"Creating callback URL with base: {base_url}")
    callback_path = f"/api/chats/{chat_id}/messages/{message_id}/callback"
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