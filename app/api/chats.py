import logging

from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request, Body
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_active_user, get_chat_by_id
from app.db.session import get_db
from app.db.models import User, Chat, Message, MessageStatus
from app.schemas.chat import (
    Chat as ChatSchema,
    ChatCreate,
    ChatList,
    Message as MessageSchema,
    MessageCreate,
    MessageList,
    ReactionCreate
)
from app.services import chat_service, ai_service
from app.tasks.message_tasks import update_message_status, save_completed_message

router = APIRouter(prefix="/chats", tags=["Chats"])
logger = logging.getLogger(__name__)


@router.get("", response_model=ChatList)
def get_chats(
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """
    Get all chats for the current user.
    """
    chats = chat_service.get_chats(
        db=db,
        user_id=current_user.id,
        skip=skip,
        limit=limit
    )
    return chats


@router.post("", response_model=ChatSchema, status_code=status.HTTP_201_CREATED)
def create_chat(
        chat_data: ChatCreate,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """
    Create a new chat.
    """
    chat = chat_service.create_chat(
        db=db,
        user_id=current_user.id,
        chat_data=chat_data
    )
    return chat


@router.get("/{chat_id}", response_model=ChatSchema)
def get_chat(
        chat: Chat = Depends(get_chat_by_id)
):
    """
    Get a specific chat by ID.
    """
    return chat


@router.get("/{chat_id}/messages", response_model=MessageList)
def get_messages(
        chat: Chat = Depends(get_chat_by_id),
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db)
):
    """
    Get all messages for a chat.
    """
    messages = chat_service.get_messages(
        db=db,
        chat_id=chat.id,
        skip=skip,
        limit=limit
    )
    return messages


@router.post("/{chat_id}/messages", response_model=MessageSchema)
async def create_message(
        request: Request,
        message_data: MessageCreate,
        chat: Chat = Depends(get_chat_by_id),
        db: Session = Depends(get_db)
):
    """
    Create a new message in a chat.
    """
    try:
        # Create user message
        user_message = chat_service.create_user_message(
            db=db,
            chat_id=chat.id,
            message_data=message_data
        )

        # Create AI message (pending)
        ai_message = chat_service.create_ai_message(
            db=db,
            chat_id=chat.id
        )

        # Get conversation history
        messages = chat.messages

        # Prepare conversation history for AI service
        conversation_history = ai_service.prepare_conversation_history(messages)

        # Create callback URL
        host = str(request.base_url).rstrip('/')
        callback_url = ai_service.create_callback_url(
            host=host,
            chat_id=chat.id,
            message_id=ai_message.id
        )

        # Send message to AI service
        success = ai_service.send_to_ai_service(
            message_content=message_data.content,
            conversation_history=conversation_history,
            callback_url=callback_url
        )

        # Update message status based on AI service response
        if success:
            update_message_status.delay(
                message_id=str(ai_message.id),
                status=MessageStatus.PROCESSING
            )
        else:
            update_message_status.delay(
                message_id=str(ai_message.id),
                status=MessageStatus.FAILED
            )

            # Update AI message with error content
            chat_service.update_ai_message(
                db=db,
                message_id=ai_message.id,
                content="Sorry, I'm having trouble processing your request right now. Please try again later.",
                status=MessageStatus.FAILED
            )

        return user_message
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating message: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process message"
        )


@router.post("/{chat_id}/messages/{message_id}/reaction")
def add_message_reaction(
        message_id: UUID,
        reaction_data: ReactionCreate,
        chat: Chat = Depends(get_chat_by_id),
        db: Session = Depends(get_db)
):
    """
    Add a reaction to a message.
    """
    # Check if message exists and belongs to this chat
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.chat_id == chat.id
    ).first()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    # Add reaction
    reaction = chat_service.add_reaction(
        db=db,
        message_id=message_id,
        reaction_data=reaction_data
    )

    return {"status": "success"}


@router.post("/{chat_id}/messages/{message_id}/callback")
async def message_callback(
        chat_id: UUID,
        message_id: UUID,
        data: Dict[str, Any] = Body(...),
        db: Session = Depends(get_db)
):
    """
    Callback endpoint for AI service to send message chunks.
    """
    # Check if message exists
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.chat_id == chat_id
    ).first()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    # Check data type
    if "type" not in data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing data type"
        )

    # Handle different callback types
    if data["type"] == "chunk":
        # Handle message chunk
        if "content" not in data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing chunk content"
            )

        # Save to Redis for WebSocket streaming
        from app.tasks.message_tasks import save_message_chunk_to_redis
        await save_message_chunk_to_redis(str(message_id), data["content"])

        return {"status": "success"}

    elif data["type"] == "complete":
        # Handle complete message
        if "content" not in data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing message content"
            )

        # Get sources if available
        sources = data.get("sources", [])

        # Save complete message
        save_completed_message.delay(
            message_id=str(message_id),
            content=data["content"],
            sources=sources
        )

        return {"status": "success"}

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown data type: {data['type']}"
        )