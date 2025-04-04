import json
import requests
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
from uuid import UUID

from app.core.config import settings
from app.db.models import Message, MessageType


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
    # Prepare request data
    request_data = {
        "message": message_content,
        "conversation_history": conversation_history,
        "callback_url": callback_url
    }

    # Prepare headers
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": settings.AI_SERVICE_API_KEY
    }

    try:
        # Send request to AI service
        response = requests.post(
            settings.AI_SERVICE_URL,
            json=request_data,
            headers=headers,
            timeout=5  # 5 seconds timeout
        )

        # Check if request was successful
        if response.status_code == 200:
            return True
        else:
            # Log error
            print(f"Error sending message to AI service: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        # Log error
        print(f"Exception sending message to AI service: {str(e)}")
        return False


def create_callback_url(host: str, chat_id: UUID, message_id: UUID) -> str:
    """
    Create a callback URL for the AI service to send responses back.
    """
    return f"{host}/api/chats/{chat_id}/messages/{message_id}/callback"