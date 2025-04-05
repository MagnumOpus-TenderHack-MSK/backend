import json
import logging
from typing import Dict, List, Any, Optional
from uuid import UUID

import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, status, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import validate_token
from app.db.session import get_db
from app.db.models import User, Chat
from app.tasks.message_tasks import get_message_content_from_redis

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSockets"])

# Active WebSocket connections
active_connections: Dict[str, List[WebSocket]] = {}


async def get_token_data(
        token: str = Query(...),
) -> Dict[str, Any]:
    """
    Validate token and get user data.
    """
    token_data = validate_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    return token_data


@router.websocket("/ws/chat/{chat_id}")
async def websocket_endpoint(
        websocket: WebSocket,
        chat_id: UUID,
        token: str = Query(...),
        db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for chat messages.
    """
    try:
        # Validate token
        token_data = validate_token(token)
        if not token_data:
            logger.warning(f"Invalid token for WebSocket connection to chat {chat_id}")
            await websocket.close(code=1008)  # Policy violation
            return

        # Get user ID from token
        user_id = token_data.get("sub")
        if not user_id:
            logger.warning(f"No user ID in token for WebSocket connection to chat {chat_id}")
            await websocket.close(code=1008)
            return

        # Check if chat exists and user has access
        chat = db.query(Chat).filter(Chat.id == chat_id).first()
        if not chat:
            logger.warning(f"Chat {chat_id} not found for WebSocket connection")
            await websocket.close(code=1008)
            return

        # Check if user has access to this chat
        user = db.query(User).filter(User.id == user_id).first()
        if not user or (chat.user_id != UUID(user_id) and not user.is_admin):
            logger.warning(f"User {user_id} does not have access to chat {chat_id}")
            await websocket.close(code=1008)
            return

        # Accept connection
        await websocket.accept()
        logger.info(f"WebSocket connection accepted for chat {chat_id}, user {user_id}")

        # Register connection
        connection_id = f"{chat_id}:{user_id}"
        if connection_id not in active_connections:
            active_connections[connection_id] = []
        active_connections[connection_id].append(websocket)

        try:
            while True:
                # Wait for message with timeout
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=300)  # 5min timeout

                    # Log received message (for debugging)
                    logger.debug(f"Received WebSocket message from user {user_id} for chat {chat_id}: {data[:100]}...")

                    # Parse message
                    try:
                        message_data = json.loads(data)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON format received from user {user_id}")
                        await websocket.send_json({
                            "error": "Invalid JSON format"
                        })
                        continue

                    # Handle message types
                    message_type = message_data.get("type")

                    if message_type == "ping":
                        # Respond to ping
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": message_data.get("timestamp")
                        })
                        logger.debug(f"Sent pong response to user {user_id}")

                    elif message_type == "stream_request":
                        # Handle stream request with error handling
                        try:
                            message_id = message_data.get("message_id")

                            if not message_id:
                                logger.warning(f"Missing message_id in stream_request from user {user_id}")
                                await websocket.send_json({
                                    "error": "Missing message_id"
                                })
                                continue

                            logger.info(f"Stream request for message {message_id} from user {user_id}")

                            # Get message content from Redis
                            content = await get_message_content_from_redis(message_id)

                            # Send content
                            await websocket.send_json({
                                "type": "stream_content",
                                "message_id": message_id,
                                "content": content
                            })
                            logger.debug(f"Sent stream content for message {message_id} to user {user_id}")
                        except Exception as e:
                            logger.error(f"Error handling stream request: {str(e)}", exc_info=True)
                            await websocket.send_json({
                                "error": "Failed to retrieve message content"
                            })

                    else:
                        # Unknown message type
                        logger.warning(f"Unknown message type '{message_type}' from user {user_id}")
                        await websocket.send_json({
                            "error": f"Unknown message type: {message_type}"
                        })

                except asyncio.TimeoutError:
                    # Handle timeout - send a message and continue waiting
                    logger.info(f"WebSocket timeout for user {user_id}, chat {chat_id}")
                    await websocket.send_json({
                        "type": "timeout",
                        "message": "Connection timed out due to inactivity"
                    })
                    continue

        except WebSocketDisconnect:
            # Handle normal disconnect
            logger.info(f"WebSocket disconnected: {connection_id}")
        except asyncio.CancelledError:
            # Handle cancellation
            logger.info(f"WebSocket connection canceled for user {user_id}, chat {chat_id}")
        except Exception as e:
            # Handle other errors
            logger.error(f"WebSocket error: {str(e)}", exc_info=True)
            if websocket.client_state.CONNECTED:
                await websocket.send_json({
                    "error": "An unexpected error occurred"
                })

        finally:
            # Clean up connection
            if connection_id in active_connections:
                if websocket in active_connections[connection_id]:
                    active_connections[connection_id].remove(websocket)
                if not active_connections[connection_id]:
                    del active_connections[connection_id]

            # Close WebSocket if still connected
            if websocket.client_state.CONNECTED:
                try:
                    await websocket.close()
                except Exception as e:
                    logger.error(f"Error closing WebSocket: {str(e)}", exc_info=True)

    except Exception as e:
        logger.error(f"WebSocket initialization error: {str(e)}", exc_info=True)
        if websocket.client_state.CONNECTED:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


async def broadcast_message(chat_id: UUID, user_id: UUID, message: Dict[str, Any]):
    """
    Broadcast a message to all connections for a chat.
    """
    connection_id = f"{chat_id}:{user_id}"
    logger.info(f"Broadcasting message to connection {connection_id}")

    if connection_id in active_connections:
        for connection in active_connections[connection_id]:
            try:
                await connection.send_json(message)
                logger.debug(f"Message sent to connection for {connection_id}")
            except Exception as e:
                logger.error(f"Error broadcasting message: {str(e)}", exc_info=True)
    else:
        logger.warning(f"No active connections for {connection_id}")


async def broadcast_message_chunk(chat_id: UUID, user_id: UUID, message_id: UUID, chunk: str):
    """
    Broadcast a message chunk to all connections for a chat.
    """
    message = {
        "type": "chunk",
        "message_id": str(message_id),
        "content": chunk
    }

    logger.debug(f"Broadcasting chunk for message {message_id} to chat {chat_id}, user {user_id}")
    await broadcast_message(chat_id, user_id, message)


async def broadcast_message_complete(chat_id: UUID, user_id: UUID, message_id: UUID,
                                     sources: List[Dict[str, Any]] = None):
    """
    Broadcast message completion to all connections for a chat.
    """
    message = {
        "type": "complete",
        "message_id": str(message_id)
    }

    if sources:
        message["sources"] = sources

    logger.info(f"Broadcasting completion for message {message_id} to chat {chat_id}, user {user_id}")
    await broadcast_message(chat_id, user_id, message)