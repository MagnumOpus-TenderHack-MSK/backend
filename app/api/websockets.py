import asyncio
import json
import logging
from typing import Dict, List, Any, Optional, Set
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, status, Depends, Query
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketState

from app.core.security import validate_token
from app.db.session import get_db
from app.db.models import User, Chat
from app.tasks.message_tasks import get_message_content_from_redis

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSockets"])

# Active WebSocket connections - structure:
# {
#   "chat_id:user_id": {
#     "connections": [WebSocket],
#     "last_activity": timestamp
#   }
# }
active_connections: Dict[str, Dict[str, Any]] = {}

# Keep track of connection IDs to prevent double-close errors
connection_ids: Set[int] = set()


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


def is_websocket_connected(websocket: WebSocket) -> bool:
    """Check if a WebSocket is still connected."""
    try:
        return websocket.client_state == WebSocketState.CONNECTED
    except Exception:
        return False


async def safe_send_json(websocket: WebSocket, data: dict) -> bool:
    """Safely send JSON data over a WebSocket with error handling."""
    if not is_websocket_connected(websocket):
        return False

    try:
        await websocket.send_json(data)
        return True
    except Exception as e:
        logger.error(f"Error sending JSON over WebSocket: {str(e)}")
        return False


async def safe_close_websocket(websocket: WebSocket, code: int = 1000, reason: str = "") -> bool:
    """Safely close a WebSocket with error handling."""
    # Get unique ID for this websocket
    ws_id = id(websocket)

    # Check if already closed
    if ws_id in connection_ids:
        logger.debug(f"WebSocket {ws_id} already closed")
        return False

    if not is_websocket_connected(websocket):
        connection_ids.add(ws_id)
        return False

    try:
        await websocket.close(code=code, reason=reason)
        connection_ids.add(ws_id)
        return True
    except Exception as e:
        logger.error(f"Error closing WebSocket: {str(e)}")
        connection_ids.add(ws_id)
        return False


@router.websocket("/ws/chat/{chat_id}")
async def websocket_endpoint(
        websocket: WebSocket,
        chat_id: UUID,
        token: str = Query(...),
        db: Session = Depends(get_db)
):
    """WebSocket endpoint for chat messages."""
    ws_id = id(websocket)
    user_connection_id = None
    connection_key = None
    socket_already_closed = False
    is_new_chat = websocket.query_params.get("new_chat") == "true"

    # Clear any existing closed connection record
    if ws_id in connection_ids:
        connection_ids.remove(ws_id)

    try:
        # Validate token
        token_data = validate_token(token)
        if not token_data:
            logger.warning(f"Invalid token for WebSocket connection to chat {chat_id}")
            await safe_close_websocket(websocket, code=1008)
            socket_already_closed = True
            return

        # Get user ID from token
        user_id = token_data.get("sub")
        if not user_id:
            logger.warning(f"No user ID in token for WebSocket connection to chat {chat_id}")
            await safe_close_websocket(websocket, code=1008)
            socket_already_closed = True
            return

        # Create a unique connection identifier for this user+chat
        connection_key = f"{chat_id}:{user_id}"

        # Check if chat exists and user has access
        chat = await run_in_threadpool(
            lambda: db.query(Chat).filter(Chat.id == chat_id).first()
        )
        if not chat:
            logger.warning(f"Chat {chat_id} not found for WebSocket connection")
            await safe_close_websocket(websocket, code=1008)
            socket_already_closed = True
            return

        # Check if user has access to this chat
        user = db.query(User).filter(User.id == user_id).first()
        if not user or (chat.user_id != UUID(user_id) and not user.is_admin):
            logger.warning(f"User {user_id} does not have access to chat {chat_id}")
            await safe_close_websocket(websocket, code=1008)
            socket_already_closed = True
            return

        # Accept connection - MUST BE DONE BEFORE ANY receive_text() CALLS
        try:
            await websocket.accept()
            logger.info(f"WebSocket connection accepted for chat {chat_id}, user {user_id}")
        except Exception as e:
            logger.error(f"Error accepting WebSocket connection: {str(e)}")
            socket_already_closed = True
            return

        # Register connection AFTER accepting the websocket
        if connection_key not in active_connections:
            active_connections[connection_key] = {
                "connections": [],
                "last_activity": asyncio.get_event_loop().time()
            }

        # Check if this websocket is already in the connections list
        if websocket not in active_connections[connection_key]["connections"]:
            active_connections[connection_key]["connections"].append(websocket)
            active_connections[connection_key]["last_activity"] = asyncio.get_event_loop().time()

        # Send welcome message for connection confirmation
        try:
            initMessage = {
                "type": "connection_established",
                "chat_id": str(chat_id),
                "timestamp": str(asyncio.get_event_loop().time())
            }

            # If this is a new chat, include initial suggestions
            if is_new_chat and chat.suggestions:
                initMessage["suggestions"] = chat.suggestions
                logger.info(f"Sending initial suggestions for new chat: {chat.suggestions}")

            await safe_send_json(websocket, initMessage)
        except Exception as e:
            logger.error(f"Error sending welcome message: {str(e)}")
            # Continue even if welcome message fails

        # Main connection loop
        try:
            # Periodically ping the client to keep the connection alive
            ping_task = asyncio.create_task(
                ping_client(websocket, connection_key)
            )

            # Use a larger timeout to avoid frequent reconnections
            receive_timeout = 120  # 2 minutes

            while is_websocket_connected(websocket):
                # Process incoming messages with timeout
                try:
                    # IMPORTANT: Only call receive_text() after websocket.accept()
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=receive_timeout)

                    # Update activity timestamp
                    if connection_key in active_connections:
                        active_connections[connection_key]["last_activity"] = asyncio.get_event_loop().time()

                    # Parse message
                    try:
                        message_data = json.loads(data)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON format received from user {user_id}")
                        await safe_send_json(websocket, {
                            "error": "Invalid JSON format"
                        })
                        continue

                    # Handle message types
                    message_type = message_data.get("type")

                    if message_type == "ping":
                        # Respond to ping
                        await safe_send_json(websocket, {
                            "type": "pong",
                            "timestamp": message_data.get("timestamp")
                        })

                    elif message_type == "stream_request":
                        # Handle stream request
                        message_id = message_data.get("message_id")

                        if not message_id:
                            logger.warning(f"Missing message_id in stream_request from user {user_id}")
                            await safe_send_json(websocket, {
                                "error": "Missing message_id"
                            })
                            continue

                        logger.info(f"Stream request for message {message_id} from user {user_id}")

                        # Get message content from Redis
                        content = await get_message_content_from_redis(message_id)

                        # Send content
                        await safe_send_json(websocket, {
                            "type": "stream_content",
                            "message_id": message_id,
                            "content": content
                        })

                    elif message_type == "get_suggestions":
                        # Client is requesting suggestions for this chat
                        if chat.suggestions:
                            await safe_send_json(websocket, {
                                "type": "suggestions",
                                "suggestions": chat.suggestions
                            })
                        else:
                            await safe_send_json(websocket, {
                                "type": "suggestions",
                                "suggestions": []
                            })

                    else:
                        # Unknown message type
                        logger.warning(f"Unknown message type '{message_type}' from user {user_id}")
                        await safe_send_json(websocket, {
                            "error": f"Unknown message type: {message_type}"
                        })

                except asyncio.TimeoutError:
                    # Handle timeout gracefully - just continue waiting
                    # This timeout is just to allow periodic checks, not an error
                    logger.debug(f"No message received from client after {receive_timeout}s - continuing")
                    continue
                except WebSocketDisconnect:
                    # Handle normal disconnect
                    logger.info(f"WebSocket disconnected: {connection_key}")
                    socket_already_closed = True
                    break
                except Exception as e:
                    # Handle other errors
                    logger.error(f"WebSocket error: {str(e)}", exc_info=True)
                    break

            # Cancel ping task
            if 'ping_task' in locals():
                ping_task.cancel()
                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass

        finally:
            # Clean up connection
            if connection_key and connection_key in active_connections:
                try:
                    if websocket in active_connections[connection_key]["connections"]:
                        active_connections[connection_key]["connections"].remove(websocket)

                    # Remove the connection entry if no more active connections
                    if not active_connections[connection_key]["connections"]:
                        del active_connections[connection_key]
                except Exception as e:
                    logger.error(f"Error cleaning up connection: {str(e)}")

            # Close WebSocket if still connected
            if not socket_already_closed and is_websocket_connected(websocket):
                await safe_close_websocket(websocket)

    except Exception as e:
        logger.error(f"WebSocket initialization error: {str(e)}", exc_info=True)
        if not socket_already_closed and ws_id not in connection_ids:
            await safe_close_websocket(websocket, code=1011)


async def ping_client(websocket: WebSocket, connection_key: str):
    """Periodically ping the client to keep the connection alive."""
    try:
        # Use a longer ping interval to reduce overhead
        ping_interval = 45  # 45 seconds

        while is_websocket_connected(websocket):
            await asyncio.sleep(ping_interval)

            if not is_websocket_connected(websocket):
                break

            try:
                await safe_send_json(websocket, {
                    "type": "ping",
                    "timestamp": asyncio.get_event_loop().time()
                })

                # Update activity timestamp
                if connection_key in active_connections:
                    active_connections[connection_key]["last_activity"] = asyncio.get_event_loop().time()
            except Exception as e:
                logger.error(f"Error sending ping: {str(e)}")
                break
    except asyncio.CancelledError:
        # Task was cancelled - normal shutdown
        pass
    except Exception as e:
        logger.error(f"Error in ping task: {str(e)}")


async def broadcast_message(chat_id: UUID, user_id: UUID, message: Dict[str, Any]):
    """Broadcast a message to all connections for a chat."""
    connection_key = f"{chat_id}:{user_id}"
    logger.info(f"Broadcasting message to connection {connection_key}")

    if connection_key in active_connections:
        # Make a copy to avoid modification during iteration
        connections = active_connections[connection_key]["connections"].copy()

        # Track successful sends
        success_count = 0

        for connection in connections:
            if is_websocket_connected(connection):
                try:
                    await connection.send_json(message)
                    success_count += 1
                except Exception as e:
                    logger.error(f"Error broadcasting message: {str(e)}")

        if success_count == 0 and connections:
            logger.warning(f"Failed to send message to any of {len(connections)} connections for {connection_key}")
        else:
            logger.debug(f"Message sent to {success_count}/{len(connections)} connections for {connection_key}")
    else:
        logger.warning(f"No active connections for {connection_key}")


async def broadcast_message_chunk(chat_id: UUID, user_id: UUID, message_id: UUID, chunk: str):
    """Broadcast a message chunk to all connections for a chat."""
    message = {
        "type": "chunk",
        "message_id": str(message_id),
        "content": chunk
    }

    logger.debug(f"Broadcasting chunk for message {message_id} to chat {chat_id}, user {user_id}")
    await broadcast_message(chat_id, user_id, message)


async def broadcast_message_complete(
        chat_id: UUID,
        user_id: UUID,
        message_id: UUID,
        sources: List[Dict[str, Any]] = None,
        suggestions: List[str] = None
):
    """Broadcast message completion to all connections for a chat.

    Args:
        chat_id: The chat ID
        user_id: The user ID
        message_id: The message ID
        sources: Optional list of source references
        suggestions: Optional list of suggested followup messages
    """
    message = {
        "type": "complete",
        "message_id": str(message_id)
    }

    if sources:
        # Process sources to ensure they're in the right format
        processed_sources = []
        for source in sources:
            # Standardize source fields - ensure we have the expected properties
            processed_source = {
                "id": source.get("id", ""),
                "title": source.get("source", "") or source.get("title", ""),
                "content": source.get("page", None),  # Use page directly, without "Page " prefix
                "url": source.get("id", "")  # Use id as url for reference matching
            }
            processed_sources.append(processed_source)

        message["sources"] = processed_sources

    if suggestions:
        message["suggestions"] = suggestions
        logger.info(f"Including {len(suggestions)} suggestions in completion message")

    logger.info(f"Broadcasting completion for message {message_id} to chat {chat_id}, user {user_id}")
    await broadcast_message(chat_id, user_id, message)