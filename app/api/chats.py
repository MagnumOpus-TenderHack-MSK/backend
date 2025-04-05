import json
import logging
from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request, Body
from sqlalchemy.orm import Session

from app.api.websockets import broadcast_message_chunk, broadcast_message_complete
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
from app.tasks.message_tasks import update_message_status, save_completed_message, get_message_content_from_redis, save_message_chunk_to_redis
from app.core.config import settings

router = APIRouter(prefix="/chats", tags=["Chats"])
logger = logging.getLogger(__name__)

# Define cluster mappings (same as used in admin)
general_clusters = [
    'Общие вопросы о работе с системой', 'Процессы закупок', 'Работа с контрактами',
    'Оферты и коммерческие предложения', 'Документы', 'Работа с категориями продукции',
    'Техническая поддержка', 'Чаты и обсуждения', 'Финансовые операции',
    'Новости и обновления', 'Регуляторные и юридические вопросы', 'Ошибки и предупреждения',
    'Бессмысленный запрос'
]

sub_clusters = {
    'Общие вопросы о работе с системой': ['Регистрация и вход в систему', 'Настройка личного кабинета', 'Поиск информации'],
    'Процессы закупок': ['Прямые закупки', 'Котировочные сессии', 'Закупки по потребностям'],
    'Работа с контрактами': ['Формирование и подписание контрактов', 'Исполнение контрактов'],
    'Оферты и коммерческие предложения': ['Создание и редактирование оферт', 'Запросы на коммерческие предложения'],
    'Документы': ['Добавление и удаление документов', 'Редактирование и обновление документации'],
    'Работа с категориями продукции': ['Выбор конечной категории продукции', 'Использование справочников'],
    'Техническая поддержка': ['Решение проблем с системой', 'Вопросы о доступности функций'],
    'Чаты и обсуждения': ['Использование чатов', 'Обсуждение конкретных закупок и контрактов'],
    'Финансовые операции': ['Банковские гарантии и финансовые инструменты', 'Логистика и связанные услуги'],
    'Новости и обновления': ['Информация о новых возможностях портала', 'Новости о тендерах и закупках'],
    'Регуляторные и юридические вопросы': ['Вопросы, связанные с нормативными документами', 'Правила участия в закупках'],
    'Ошибки и предупреждения': ['Вопросы о неправильных действиях', 'Работа с блокировками или жалобами'],
    'Бессмысленный запрос': []
}


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
    try:
        logger.info(f"Getting chats for user {current_user.id}")
        chats_data = chat_service.get_chats(
            db=db,
            user_id=current_user.id,
            skip=skip,
            limit=limit
        )

        chat_items = [ChatSchema.from_orm(chat) for chat in chats_data["items"]]
        logger.info(f"Successfully fetched {len(chat_items)} chats")
        return ChatList(
            items=chat_items,
            total=chats_data["total"]
        )
    except Exception as e:
        logger.error(f"Error in get_chats endpoint: {str(e)}", exc_info=True)
        raise


@router.post("", response_model=ChatSchema, status_code=status.HTTP_201_CREATED)
def create_chat(
        chat_data: ChatCreate,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """
    Create a new chat.
    """
    try:
        logger.info(f"Creating new chat for user {current_user.id} with title: {chat_data.title}")
        chat = chat_service.create_chat(
            db=db,
            user_id=current_user.id,
            chat_data=chat_data
        )
        logger.info(f"Successfully created chat {chat.id}")
        return chat
    except Exception as e:
        logger.error(f"Error creating chat: {str(e)}", exc_info=True)
        raise


@router.get("/{chat_id}", response_model=ChatSchema)
def get_chat(
        chat: Chat = Depends(get_chat_by_id)
):
    """
    Get a specific chat by ID.
    """
    logger.info(f"Fetching chat {chat.id}")
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
    try:
        logger.info(f"Getting messages for chat {chat.id}")
        messages_data = chat_service.get_messages(
            db=db,
            chat_id=chat.id,
            skip=skip,
            limit=limit
        )

        message_items = [MessageSchema.from_orm(msg) for msg in messages_data["items"]]
        logger.info(f"Successfully fetched {len(message_items)} messages")
        return MessageList(
            items=message_items,
            total=messages_data["total"]
        )
    except Exception as e:
        logger.error(f"Error getting messages: {str(e)}", exc_info=True)
        raise


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
        logger.info(f"Creating message in chat {chat.id}: {message_data.content[:30]}...")
        user_message = chat_service.create_user_message(
            db=db,
            chat_id=chat.id,
            message_data=message_data
        )
        logger.info(f"Created user message {user_message.id}")

        ai_message = chat_service.create_ai_message(
            db=db,
            chat_id=chat.id
        )
        logger.info(f"Created pending AI message {ai_message.id}")

        messages = chat.messages
        conversation_history = ai_service.prepare_conversation_history(messages)
        host = str(request.base_url).rstrip('/')
        callback_url = ai_service.create_callback_url(
            host=host,
            chat_id=chat.id,
            message_id=ai_message.id
        )
        logger.info(f"Callback URL created: {callback_url}")

        # Send message to AI service and get full response with additional meta data
        ai_response = ai_service.send_to_ai_service(
            message_content=message_data.content,
            conversation_history=conversation_history,
            callback_url=callback_url
        )

        if ai_response.get("success"):
            logger.info(f"Message sent to AI service, updating status to PROCESSING")
            update_message_status.delay(
                message_id=str(ai_message.id),
                status=MessageStatus.PROCESSING
            )
            # Update chat title if current title is default
            if ai_response.get("name") and (chat.title in ["Новый чат", "", None]):
                chat.title = ai_response["name"]
                db.commit()
            # Update clusters: map returned subclusters to general clusters
            if ai_response.get("cluster"):
                new_subcategories = ai_response["cluster"]
                new_general = []
                for sub in new_subcategories:
                    for general, subs in sub_clusters.items():
                        if sub in subs:
                            new_general.append(general)
                new_general = list(set(new_general))
                chat.subcategories = new_subcategories
                chat.categories = new_general
                db.commit()
            # Store suggestions to be shown in the UI
            if ai_response.get("suggestions"):
                chat.suggestions = ai_response["suggestions"]
                db.commit()

        else:
            logger.error("Failed to send message to AI service")
            update_message_status.delay(
                message_id=str(ai_message.id),
                status=MessageStatus.FAILED
            )
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
    try:
        logger.info(f"Adding reaction {reaction_data.reaction_type} to message {message_id}")

        # Check if message exists and belongs to this chat
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.chat_id == chat.id
        ).first()

        if not message:
            logger.warning(f"Message {message_id} not found in chat {chat.id}")
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
        logger.info(f"Added reaction successfully")

        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding reaction: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add reaction"
        )


@router.post("/{chat_id}/messages/{message_id}/callback")
async def message_callback(
        chat_id: UUID,
        message_id: UUID,
        data: Dict[str, Any] = Body(...),
        db: Session = Depends(get_db)
):
    """
    Callback endpoint for AI service to send message chunks.
    This endpoint accepts JSON responses in the following format:
    {
        "chunk_id": "<chunk_id>",
        "content": "<content>",
        "is_final": <True/False>,
        "context_used": [ ... ]
    }
    """
    logger.info(f"Received callback for chat {chat_id}, message {message_id}")
    logger.debug(f"Callback data: {json.dumps(data, default=str)[:500]}")

    # Check if message exists
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.chat_id == chat_id
    ).first()

    if not message:
        logger.error(f"Message {message_id} not found for chat {chat_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    # Validate that data contains the expected keys
    required_keys = ["chunk_id", "content", "is_final"]
    if not all(key in data for key in required_keys):
        logger.error("Callback data missing required keys")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid callback format"
        )

    # Determine user_id for broadcasting
    chat_obj = db.query(Chat).filter(Chat.id == chat_id).first()
    user_id = chat_obj.user_id if chat_obj else None
    if not user_id:
        logger.error(f"Could not determine user_id for chat {chat_id}")
        user_id = UUID("00000000-0000-0000-0000-000000000000")  # Fallback

    content = data.get("content", "")
    is_final = data.get("is_final", False)
    context_used = data.get("context_used", [])

    # Append this chunk to Redis
    await save_message_chunk_to_redis(str(message_id), content)

    # Send only the new chunk to the client for smooth typing
    await broadcast_message_chunk(chat_id, user_id, message_id, content)

    if is_final:
        # Retrieve the full accumulated message content
        full_content = await get_message_content_from_redis(str(message_id))

        # Update the message in the database
        message.content = full_content
        message.status = MessageStatus.COMPLETED
        db.commit()
        db.refresh(message)

        # Use celery task to process sources and finalize message
        save_completed_message.delay(
            message_id=str(message_id),
            content=full_content,
            sources=context_used
        )

        # Send complete notification to client
        await broadcast_message_complete(chat_id, user_id, message_id, context_used)

    return {"status": "success"}

