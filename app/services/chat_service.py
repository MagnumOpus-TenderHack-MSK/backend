import logging

from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.db.models import Chat, Message, MessageType, MessageStatus, MessageFile, Source, Reaction, ReactionType, File
from app.schemas.chat import ChatCreate, MessageCreate, ReactionCreate

logger = logging.getLogger(__name__)


def get_chats(db: Session, user_id: UUID, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
    """
    Get all chats for a user with pagination.
    """
    # Get chats with count
    total = db.query(Chat).filter(Chat.user_id == user_id).count()
    chats = db.query(Chat).filter(Chat.user_id == user_id).order_by(Chat.updated_at.desc()).offset(skip).limit(
        limit).all()

    return {
        "items": chats,
        "total": total
    }


def get_chat(db: Session, chat_id: UUID) -> Chat:
    """
    Get a single chat by ID.
    """
    chat = db.query(Chat).filter(Chat.id == chat_id).first()

    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found"
        )

    return chat


def create_chat(db: Session, user_id: UUID, chat_data: ChatCreate) -> Chat:
    """
    Create a new chat.
    """
    # Create chat
    chat = Chat(
        title=chat_data.title,
        user_id=user_id
    )

    db.add(chat)
    db.commit()
    db.refresh(chat)

    return chat


def get_messages(db: Session, chat_id: UUID, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
    """
    Get all messages for a chat with pagination.
    """
    # Get messages with count
    total = db.query(Message).filter(Message.chat_id == chat_id).count()
    messages = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.created_at).offset(skip).limit(
        limit).all()

    return {
        "items": messages,
        "total": total
    }


def create_user_message(db: Session, chat_id: UUID, message_data: MessageCreate) -> Message:
    """
    Create a new user message.
    """
    try:
        # Create message
        message = Message(
            chat_id=chat_id,
            content=message_data.content,
            message_type=MessageType.USER,
            status=MessageStatus.COMPLETED
        )

        db.add(message)
        db.commit()
        db.refresh(message)

        # Add files if any
        if message_data.file_ids:
            for file_id in message_data.file_ids:
                try:
                    # Check if file exists
                    file = db.query(File).filter(File.id == file_id).first()
                    if not file:
                        logger.warning(f"File {file_id} not found")
                        continue

                    message_file = MessageFile(
                        message_id=message.id,
                        file_id=file_id
                    )
                    db.add(message_file)
                except Exception as e:
                    logger.error(f"Error attaching file {file_id}: {str(e)}")
                    # Continue with other files if one fails

            db.commit()
            db.refresh(message)  # Refresh to get the attached files

        # Process message files for response schema
        # This is the fix for the validation error
        if hasattr(message, 'files') and message.files:
            # Convert MessageFile to FileReference format with necessary fields
            for msg_file in message.files:
                if hasattr(msg_file, 'file') and msg_file.file:
                    # Add required fields that were missing
                    msg_file.name = msg_file.file.name
                    msg_file.file_type = msg_file.file.file_type.value

        return message
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating message: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create message"
        )


def create_ai_message(db: Session, chat_id: UUID, content: str = "") -> Message:
    """
    Create a new AI message with pending status.
    """
    # Create message
    message = Message(
        chat_id=chat_id,
        content=content,
        message_type=MessageType.AI,
        status=MessageStatus.PENDING
    )

    db.add(message)
    db.commit()
    db.refresh(message)

    return message


def update_ai_message(db: Session, message_id: UUID, content: str, status: MessageStatus,
                      sources: List[Dict[str, Any]] = None) -> Message:
    """
    Update an AI message with new content and status.
    """
    message = db.query(Message).filter(Message.id == message_id).first()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    message.content = content
    message.status = status

    db.commit()
    db.refresh(message)

    # Add sources if any
    if sources:
        for source_data in sources:
            source = Source(
                message_id=message.id,
                title=source_data.get("title", ""),
                url=source_data.get("url"),
                content=source_data.get("content")
            )
            db.add(source)

        db.commit()

    return message


def add_reaction(db: Session, message_id: UUID, reaction_data: ReactionCreate) -> Reaction:
    """
    Add a reaction to a message.
    """
    # Check if message exists
    message = db.query(Message).filter(Message.id == message_id).first()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    # Remove existing reactions
    db.query(Reaction).filter(Reaction.message_id == message_id).delete()

    # Create new reaction
    reaction = Reaction(
        message_id=message_id,
        reaction_type=reaction_data.reaction_type
    )

    db.add(reaction)
    db.commit()
    db.refresh(reaction)

    return reaction