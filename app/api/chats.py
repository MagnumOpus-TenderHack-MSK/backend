import json
import logging
from typing import List, Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request, Body
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.websockets import broadcast_message_chunk, broadcast_message_complete
from app.core.dependencies import get_current_active_user, get_chat_by_id
from app.db.session import get_db
from app.db.models import User, Chat, Message, MessageStatus, MessageType, File
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
from app.tasks.message_tasks import update_message_status, save_completed_message, get_message_content_from_redis, \
    save_message_chunk_to_redis
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
    'Общие вопросы о работе с системой': ['Регистрация и вход в систему', 'Настройка личного кабинета',
                                          'Поиск информации'],
    'Процессы закупок': ['Прямые закупки', 'Котировочные сессии', 'Закупки по потребностям'],
    'Работа с контрактами': ['Формирование и подписание контрактов', 'Исполнение контрактов'],
    'Оферты и коммерческие предложения': ['Создание и редактирование оферт', 'Запросы на коммерческие предложения'],
    'Документы': ['Добавление и удаление документов', 'Редактирование и обновление документации'],
    'Работа с категориями продукции': ['Выбор конечной категории продукции', 'Использование справочников'],
    'Техническая поддержка': ['Решение проблем с системой', 'Вопросы о доступности функций'],
    'Чаты и обсуждения': ['Использование чатов', 'Обсуждение конкретных закупок и контрактов'],
    'Финансовые операции': ['Банковские гарантии и финансовые инструменты', 'Логистика и связанные услуги'],
    'Новости и обновления': ['Информация о новых возможностях портала', 'Новости о тендерах и закупках'],
    'Регуляторные и юридические вопросы': ['Вопросы, связанные с нормативными документами',
                                           'Правила участия в закупках'],
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


@router.get("/{chat_id}/suggestions")
async def get_chat_suggestions(
    chat_id: UUID,
    chat: Chat = Depends(get_chat_by_id)
) -> List[str]:
    """
    Get AI-generated suggestions for the chat.
    """
    try:
        # Return suggestions array from the chat or empty list if none
        return chat.suggestions or []
    except Exception as e:
        logger.error(f"Error getting chat suggestions: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get chat suggestions"
        )

@router.get("/{chat_id}", response_model=ChatSchema)
def get_chat(
    chat: Chat = Depends(get_chat_by_id)
):
    """
    Get a specific chat by ID.
    """
    logger.info(f"Fetching chat {chat.id}")
    # Make sure the chat schema includes suggestions field
    return chat


@router.get("/{chat_id}/messages", response_model=MessageList)
async def get_messages(
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

        message_items = []

        # Check for in-progress AI messages to add the latest content from Redis
        for msg in messages_data["items"]:
            # Create a message schema from the ORM model
            message_schema = MessageSchema.from_orm(msg)

            # If it's an AI message in progress, try to get content from Redis
            if msg.message_type == MessageType.AI and msg.status in [MessageStatus.PENDING, MessageStatus.PROCESSING]:
                try:
                    # Get the latest content from Redis if available
                    redis_content = await get_message_content_from_redis(str(msg.id))
                    if redis_content:
                        # Update the content with what's in Redis
                        message_schema.content = redis_content
                except Exception as e:
                    logger.warning(f"Error fetching Redis content for in-progress message {msg.id}: {e}")

            message_items.append(message_schema)

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
        # Check if this is support request - don't process with AI
        is_support_request = False
        support_keywords = ["оператор", "поддержк", "консультант", "помощник", "специалист"]

        if message_data.content:
            message_lower = message_data.content.lower()
            # Check if message contains support keywords
            if any(keyword in message_lower for keyword in support_keywords):
                is_support_request = True
                logger.info(f"Detected support request: {message_data.content}")

        logger.info(f"Creating message in chat {chat.id}: {message_data.content[:30]}...")
        user_message = chat_service.create_user_message(
            db=db,
            chat_id=chat.id,
            message_data=message_data
        )
        logger.info(f"Created user message {user_message.id}")

        # If this is a support request, create a system message instead of AI message
        if is_support_request:
            logger.info("Creating system message for support request")
            system_content = "Запрос на соединение с оператором отправлен. Пожалуйста, ожидайте, оператор присоединится к чату в ближайшее время."

            system_message = chat_service.create_system_message(
                db=db,
                chat_id=chat.id,
                content=system_content
            )
            logger.info(f"Created system message {system_message.id} for support request")

            return user_message

        # Check if the latest message was a system message about support operator
        latest_messages = chat.messages[-3:] if chat.messages and len(chat.messages) >= 3 else chat.messages
        has_system_support_message = False

        if latest_messages:
            for msg in reversed(latest_messages):  # Check most recent first
                if msg.message_type == MessageType.SYSTEM and any(
                        keyword in msg.content.lower() for keyword in support_keywords):
                    has_system_support_message = True
                    break

        # If there was a recent system message about support, don't create an AI message
        if has_system_support_message:
            logger.info(f"Skipping AI response since there's a support system message")
            return user_message

        # Create the AI message
        ai_message = chat_service.create_ai_message(
            db=db,
            chat_id=chat.id
        )
        logger.info(f"Created pending AI message {ai_message.id}")

        # Get conversation history
        messages = chat.messages
        conversation_history = ai_service.prepare_conversation_history(messages)

        # Create callback URL
        host = str(request.base_url).rstrip('/')
        callback_url = ai_service.create_callback_url(
            host=host,
            chat_id=chat.id,
            message_id=ai_message.id
        )
        logger.info(f"Callback URL created: {callback_url}")

        # Get file contents if any file IDs were provided
        file_contents = None
        if message_data.file_ids and len(message_data.file_ids) > 0:
            file_contents = []
            for file_id in message_data.file_ids:
                file = db.query(File).filter(File.id == file_id).first()
                if file and file.content:
                    file_contents.append({
                        "id": str(file.id),
                        "name": file.original_name or file.name,
                        "content": file.content,
                        "type": file.file_type.value if file.file_type else "OTHER"
                    })

            if file_contents:
                logger.info(f"Including {len(file_contents)} file contents with AI request")

        # Send message to AI service and get full response with additional meta data
        ai_response = ai_service.send_to_ai_service(
            message_content=message_data.content,
            conversation_history=conversation_history,
            callback_url=callback_url,
            file_contents=file_contents
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
                logger.info(f"Updated chat title to: {chat.title}")

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
                logger.info(f"Updated chat categories to: {new_general}, subcategories: {new_subcategories}")

            # Store suggestions to be shown in the UI
            if ai_response.get("suggestions"):
                chat.suggestions = ai_response["suggestions"]
                db.commit()
                logger.info(f"Stored {len(ai_response['suggestions'])} suggestions for chat")

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


@router.post("/{chat_id}/system-messages", response_model=MessageSchema)
async def create_system_message(
        chat_id: UUID,
        message_data: dict = Body(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user)
):
    """
    Create a new system message in a chat.

    This endpoint allows for creating system messages like support notifications.
    """
    try:
        # Verify chat exists and user has access
        chat = await run_in_threadpool(
            lambda: db.query(Chat).filter(Chat.id == chat_id).first()
        )
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat not found"
            )

        # Check if user has access to this chat
        if chat.user_id != current_user.id and not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden"
            )

        # Get content and message type
        content = message_data.get("content")
        message_type = message_data.get("message_type", "SYSTEM")

        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content is required"
            )

        # Create system message
        system_message = chat_service.create_system_message(
            db=db,
            chat_id=chat_id,
            content=content
        )

        logger.info(f"Created system message {system_message.id} in chat {chat_id}")
        return system_message

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating system message: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create system message"
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

        # Get the chat's suggestions for broadcasting
        suggestions = chat_obj.suggestions if chat_obj else []
        logger.info(f"Retrieved {len(suggestions) if suggestions else 0} suggestions from chat")

        # Send complete notification to client with suggestions
        await broadcast_message_complete(chat_id, user_id, message_id, context_used, suggestions)

    return {"status": "success"}