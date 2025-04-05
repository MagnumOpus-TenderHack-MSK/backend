import logging

from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy.orm import Session, selectinload, joinedload
from fastapi import HTTPException, status

from app.db.models import Chat, Message, MessageType, MessageStatus, MessageFile, Source, Reaction, ReactionType, File
from app.schemas.chat import ChatCreate, MessageCreate, ReactionCreate

logger = logging.getLogger(__name__)


def get_chats(db: Session, user_id: UUID, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
    """
    Get all chats for a user with pagination.
    """
    try:
        # Log the start of the operation
        logger.info(f"Fetching chats for user {user_id}, skip={skip}, limit={limit}")

        # Get total chats count
        total = db.query(Chat).filter(Chat.user_id == user_id).count()
        logger.info(f"Total chats found: {total}")

        # Get chats with eager loading of messages and related data
        chats = db.query(Chat).filter(Chat.user_id == user_id).options(
            selectinload(Chat.messages).selectinload(Message.files).joinedload(MessageFile.file)
        ).order_by(Chat.updated_at.desc()).offset(skip).limit(limit).all()

        logger.info(f"Successfully fetched {len(chats)} chats")
        return {
            "items": chats,
            "total": total
        }
    except Exception as e:
        logger.error(f"Error fetching chats for user {user_id}: {str(e)}", exc_info=True)
        raise


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
    try:
        logger.info(f"Fetching messages for chat {chat_id}, skip={skip}, limit={limit}")

        # Get messages with count
        total = db.query(Message).filter(Message.chat_id == chat_id).count()
        logger.info(f"Total messages found: {total}")

        # Get messages with eager loading of files and file data
        messages = db.query(Message).filter(Message.chat_id == chat_id).options(
            selectinload(Message.files).joinedload(MessageFile.file),
            selectinload(Message.reactions),
            selectinload(Message.sources)
        ).order_by(Message.created_at).offset(skip).limit(limit).all()

        logger.info(f"Successfully fetched {len(messages)} messages for chat {chat_id}")
        return {
            "items": messages,
            "total": total
        }
    except Exception as e:
        logger.error(f"Error fetching messages for chat {chat_id}: {str(e)}", exc_info=True)
        raise


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

        return message
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating message: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create message"
        )


def create_system_message(db: Session, chat_id: UUID, content: str) -> Message:
    """
    Create a new system message.
    """
    try:
        # Create message
        message = Message(
            chat_id=chat_id,
            content=content,
            message_type=MessageType.SYSTEM,
            status=MessageStatus.COMPLETED
        )

        db.add(message)
        db.commit()
        db.refresh(message)

        return message
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating system message: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create system message"
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