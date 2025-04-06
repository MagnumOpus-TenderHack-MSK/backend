import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload, selectinload
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from app.core.dependencies import get_current_admin_user
from app.db.models import Chat, Message, Reaction, User, MessageFile, Source # Import missing models
from app.db.session import get_db
from sqlalchemy import func, case, text, and_
from app.schemas.chat import ChatList, MessageList # Keep using existing schemas for now
from app.schemas.admin import AdminChat, AdminChatDetail, AdminUser, PaginatedResponse # Import new admin schemas
from app.schemas.user import User as UserSchema # Import base User schema


router = APIRouter(prefix="/admin", tags=["Admin"])
logger = logging.getLogger(__name__)

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

def get_default_color(category):
    """Get default color for a category"""
    default_colors = {
        'Общие вопросы о работе с системой': "#8884d8", 'Процессы закупок': "#82ca9d",
        'Работа с контрактами': "#ffc658", 'Оферты и коммерческие предложения': "#ff8042",
        'Документы': "#0088FE", 'Работа с категориями продукции': "#00C49F",
        'Техническая поддержка': "#FFBB28", 'Чаты и обсуждения': "#FF8042",
        'Финансовые операции': "#a4de6c", 'Новости и обновления': "#d0ed57",
        'Регуляторные и юридические вопросы': "#8884d8", 'Ошибки и предупреждения': "#82ca9d",
        'Бессмысленный запрос': "#ff8042"
    }
    return default_colors.get(category, "#cccccc") # Default grey if not found


@router.get("/clusters")
def get_clusters_stats(
        db: Session = Depends(get_db),
        current_admin: User = Depends(get_current_admin_user),
        parentCluster: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """
    Get statistics about clusters and sub-clusters used in chats.
    If a parent cluster is provided, returns only its child sub-clusters.
    """
    try:
        query = db.query(Chat)
        if parentCluster:
            # Filter by parent cluster before fetching
            query = query.filter(Chat.categories.any(parentCluster))

        chats = query.all()
        logger.info(f"Analyzed {len(chats)} chats for parentCluster='{parentCluster}'")

        if parentCluster:
            # Return sub-clusters for the given parent
            if parentCluster not in sub_clusters:
                logger.warning(f"Unknown parent cluster requested: {parentCluster}")
                return {"sub_clusters": []}

            valid_subcategories = sub_clusters[parentCluster]
            subcategory_counts = {sub: 0 for sub in valid_subcategories}

            for chat in chats: # Iterate only through filtered chats
                if chat.subcategories:
                    for sub in chat.subcategories:
                        if sub in subcategory_counts:
                            subcategory_counts[sub] += 1

            sub_stats = [{
                "name": sub,
                "requests": count,
                "color": get_default_color(sub) # Assign color here
            } for sub, count in subcategory_counts.items()]

            sub_stats.sort(key=lambda x: x["requests"], reverse=True)
            logger.info(f"Returning {len(sub_stats)} subcategories for parent {parentCluster}")
            return {"sub_clusters": sub_stats}
        else:
            # Return general clusters stats
            category_counts = {cat: 0 for cat in general_clusters}
            for chat in chats:
                if chat.categories:
                    for cat in chat.categories:
                        if cat in category_counts:
                            category_counts[cat] += 1

            general_stats = [{
                "name": cat,
                "requests": count,
                "color": get_default_color(cat)
            } for cat, count in category_counts.items() if count > 0] # Only include categories with requests

            general_stats.sort(key=lambda x: x["requests"], reverse=True)
            logger.info(f"Returning {len(general_stats)} general categories")
            return {"general_clusters": general_stats}

    except Exception as e:
        logger.error(f"Error getting cluster stats: {str(e)}", exc_info=True)
        return {
            "general_clusters": [] if not parentCluster else None,
            "sub_clusters": [] if parentCluster else None
        }


@router.get("/cluster-timeseries")
def get_cluster_timeseries(
        start_date: str = Query(..., description="Start date in YYYY-MM-DD"),
        end_date: str = Query(..., description="End date in YYYY-MM-DD"),
        granularity: str = Query("day", description="Data granularity: hour, day, or week"),
        db: Session = Depends(get_db),
        current_admin: User = Depends(get_current_admin_user)
) -> List[Dict[str, Any]]:
    """
    Returns time series data with specified granularity for each general cluster.
    """
    try:
        start_datetime = datetime.strptime(f"{start_date} 00:00:00", "%Y-%m-%d %H:%M:%S")
        end_datetime = datetime.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S")

        # Determine time formatting and interval based on granularity
        if granularity == "hour":
            time_trunc = "hour"
            interval = timedelta(hours=1)
            formatter = lambda dt: dt.strftime("%Y-%m-%d %H:00")
        elif granularity == "week":
            time_trunc = "week"
            interval = timedelta(weeks=1)
            formatter = lambda dt: (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d") # Start of week
        else:  # Default to day
            time_trunc = "day"
            interval = timedelta(days=1)
            formatter = lambda dt: dt.strftime("%Y-%m-%d")

        # Generate all expected time slots within the range
        all_slots = set()
        current_slot_start = start_datetime
        while current_slot_start <= end_datetime:
            if granularity == 'week':
                 slot_dt = current_slot_start - timedelta(days=current_slot_start.weekday())
            else:
                 slot_dt = current_slot_start
            if granularity == 'hour': truncated_dt = slot_dt.replace(minute=0, second=0, microsecond=0)
            elif granularity == 'week': truncated_dt = slot_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            else: truncated_dt = slot_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            all_slots.add(formatter(truncated_dt))
            current_slot_start += interval

        # Query to aggregate counts per time slot and category
        query = text(f"""
            SELECT
                date_trunc(:granularity, created_at) AS time_slot,
                unnest(categories) AS category,
                count(*) AS count
            FROM chat
            WHERE created_at BETWEEN :start_date AND :end_date
            AND categories IS NOT NULL AND cardinality(categories) > 0 -- Ensure categories exist and are not empty
            GROUP BY time_slot, category
            ORDER BY time_slot;
        """)

        results = db.execute(query, {
            "granularity": time_trunc,
            "start_date": start_datetime,
            "end_date": end_datetime
        }).mappings().all() # Use mappings().all() to get list of dict-like RowMappings

        # Process results into the timeseries format
        timeseries_dict: Dict[str, Dict[str, Any]] = {slot: {"date": slot} for slot in all_slots}
        for slot in timeseries_dict:
            for gc in general_clusters:
                timeseries_dict[slot][gc] = 0 # Initialize all clusters to 0

        for row in results:
            # Now access using dictionary keys as mappings() returns dict-like objects
            slot_str = formatter(row['time_slot'])
            category = row['category']
            count = row['count']

            if slot_str in timeseries_dict and category in general_clusters:
                timeseries_dict[slot_str][category] = count

        # Convert to list and sort
        final_timeseries = sorted(list(timeseries_dict.values()), key=lambda x: x["date"])

        logger.info(f"Generated timeseries data with {len(final_timeseries)} points, granularity: {granularity}")
        return final_timeseries

    except Exception as e:
        logger.error(f"Error in cluster timeseries: {str(e)}", exc_info=True)
        return [] # Return empty list on error


@router.get("/feedback")
def get_feedback_stats(
        from_date: str = Query(None, description="Start date in YYYY-MM-DD"),
        to_date: str = Query(None, description="End date in YYYY-MM-DD"),
        granularity: str = Query("hour", description="Data granularity: hour, day, or week"),
        db: Session = Depends(get_db),
        current_admin: User = Depends(get_current_admin_user)
) -> List[Dict[str, Any]]:
    """
    Returns feedback stats (likes/dislikes) with specified granularity.
    """
    try:
        today = datetime.utcnow().date()
        start_datetime = datetime.strptime(f"{from_date} 00:00:00", "%Y-%m-%d %H:%M:%S") if from_date else datetime.combine(today - timedelta(days=7), datetime.min.time())
        end_datetime = datetime.strptime(f"{to_date} 23:59:59", "%Y-%m-%d %H:%M:%S") if to_date else datetime.combine(today, datetime.max.time())

        if granularity == "hour":
            time_trunc = "hour"
            interval = timedelta(hours=1)
            formatter = lambda dt: dt.strftime("%Y-%m-%d %H:00")
        elif granularity == "week":
            time_trunc = "week"
            interval = timedelta(weeks=1)
            formatter = lambda dt: (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
        else: # Default to day
            time_trunc = "day"
            interval = timedelta(days=1)
            formatter = lambda dt: dt.strftime("%Y-%m-%d")

        all_slots = set()
        current_slot_start = start_datetime
        while current_slot_start <= end_datetime:
            if granularity == 'week': slot_dt = current_slot_start - timedelta(days=current_slot_start.weekday())
            else: slot_dt = current_slot_start
            if granularity == 'hour': truncated_dt = slot_dt.replace(minute=0, second=0, microsecond=0)
            elif granularity == 'week': truncated_dt = slot_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            else: truncated_dt = slot_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            all_slots.add(formatter(truncated_dt))
            current_slot_start += interval
        if granularity == 'week': last_slot_dt = end_datetime - timedelta(days=end_datetime.weekday())
        else: last_slot_dt = end_datetime
        if granularity == 'hour': last_truncated_dt = last_slot_dt.replace(minute=0, second=0, microsecond=0)
        elif granularity == 'week': last_truncated_dt = last_slot_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        else: last_truncated_dt = last_slot_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        all_slots.add(formatter(last_truncated_dt))


        query = text(f"""
            SELECT
                date_trunc(:granularity, r.created_at) as time_slot,
                r.reaction_type,
                count(*) as count
            FROM reaction r
            JOIN message m ON r.message_id = m.id
            WHERE r.created_at BETWEEN :start_date AND :end_date
            GROUP BY time_slot, r.reaction_type
            ORDER BY time_slot;
        """)

        results = db.execute(query, {
            "granularity": time_trunc,
            "start_date": start_datetime,
            "end_date": end_datetime
        }).mappings().all()

        # Optional: Add logging to see raw results before processing
        logger.debug(f"Raw feedback query results: {results}")

        # --- Process Results ---
        feedback_dict: Dict[str, Dict[str, Any]] = {slot: {"date": slot, "likes": 0, "dislikes": 0} for slot in all_slots}

        for row in results:
            time_slot_dt = row.get('time_slot')
            if not isinstance(time_slot_dt, datetime):
                logger.warning(f"Skipping row with invalid time_slot type: {time_slot_dt}")
                continue

            slot_str = formatter(time_slot_dt)

            # Get reaction type, convert to string, and make lowercase for robust comparison
            reaction_type_str = str(row['reaction_type']).lower()
            count = row['count']

            if slot_str in feedback_dict:
                # Compare with lowercase strings 'like' and 'dislike'
                if reaction_type_str == 'like':
                    feedback_dict[slot_str]['likes'] += count
                elif reaction_type_str == 'dislike':
                    feedback_dict[slot_str]['dislikes'] += count
                else:
                    logger.warning(f"Unknown reaction type '{row['reaction_type']}' found for slot {slot_str}")
            else:
                 logger.warning(f"Calculated slot '{slot_str}' not found in initial dictionary. Row: {row}")


        final_feedback = sorted(list(feedback_dict.values()), key=lambda x: x["date"])

        logger.info(f"Generated feedback data with {len(final_feedback)} points, granularity: {granularity}")
        # logger.debug(f"Final processed feedback data: {final_feedback}") # Optional: log final data

        return final_feedback

    except Exception as e:
        logger.error(f"Error getting feedback stats: {str(e)}", exc_info=True)
        return []

@router.get("/stats")
def get_admin_stats(
        db: Session = Depends(get_db),
        current_admin: User = Depends(get_current_admin_user),
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    """
    Get admin dashboard statistics, optionally filtered by date range for chats/reactions.
    """
    try:
        total_users = db.query(func.count(User.id)).scalar()

        # Date filtering for chats and reactions
        chat_query = db.query(func.count(Chat.id))
        reaction_query_likes = db.query(func.count(Reaction.id)).filter(Reaction.reaction_type == "like")
        reaction_query_dislikes = db.query(func.count(Reaction.id)).filter(Reaction.reaction_type == "dislike")

        if from_date and to_date:
            try:
                start_date = datetime.strptime(from_date, "%Y-%m-%d")
                end_date = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)
                chat_query = chat_query.filter(Chat.updated_at.between(start_date, end_date))
                reaction_query_likes = reaction_query_likes.filter(Reaction.created_at.between(start_date, end_date))
                reaction_query_dislikes = reaction_query_dislikes.filter(Reaction.created_at.between(start_date, end_date))
            except ValueError:
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD.")

        active_chats = chat_query.scalar()
        positive_reactions = reaction_query_likes.scalar()
        negative_reactions = reaction_query_dislikes.scalar()

        return {
            "totalUsers": total_users or 0,
            "activeChats": active_chats or 0,
            "positiveReactions": positive_reactions or 0,
            "negativeReactions": negative_reactions or 0,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting admin stats: {str(e)}", exc_info=True)
        return {
            "totalUsers": 0,
            "activeChats": 0,
            "positiveReactions": 0,
            "negativeReactions": 0,
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/chats", response_model=PaginatedResponse[AdminChat]) # Use AdminChat schema
def get_admin_chats(
        skip: int = 0,
        limit: int = 100,
        cluster: Optional[str] = Query(None),
        subCluster: Optional[str] = Query(None),
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to"),
        db: Session = Depends(get_db),
        current_admin: User = Depends(get_current_admin_user),
):
    """
    Get chats with filtering for admin view. Returns PaginatedResponse[AdminChat].
    """
    try:
        query = db.query(Chat).options(
            joinedload(Chat.user), # Eager load user
             # Subquery to count messages and reactions separately
        )

        # --- Subquery for Message Count ---
        message_count_subquery = (
            db.query(Message.chat_id, func.count(Message.id).label("message_count"))
            .group_by(Message.chat_id)
            .subquery()
        )
        query = query.outerjoin(
            message_count_subquery, Chat.id == message_count_subquery.c.chat_id
        )
        query = query.add_columns(
            func.coalesce(message_count_subquery.c.message_count, 0).label("message_count")
        )

        # --- Subquery for Likes ---
        likes_subquery = (
            db.query(Message.chat_id, func.count(Reaction.id).label("likes_count"))
            .join(Reaction, Message.id == Reaction.message_id)
            .filter(Reaction.reaction_type == "like")
            .group_by(Message.chat_id)
            .subquery()
        )
        query = query.outerjoin(
            likes_subquery, Chat.id == likes_subquery.c.chat_id
        )
        query = query.add_columns(
            func.coalesce(likes_subquery.c.likes_count, 0).label("likes_count")
        )

        # --- Subquery for Dislikes ---
        dislikes_subquery = (
            db.query(Message.chat_id, func.count(Reaction.id).label("dislikes_count"))
            .join(Reaction, Message.id == Reaction.message_id)
            .filter(Reaction.reaction_type == "dislike")
            .group_by(Message.chat_id)
            .subquery()
        )
        query = query.outerjoin(
            dislikes_subquery, Chat.id == dislikes_subquery.c.chat_id
        )
        query = query.add_columns(
            func.coalesce(dislikes_subquery.c.dislikes_count, 0).label("dislikes_count")
        )


        # Date range filtering
        if from_date and to_date:
            try:
                start_date = datetime.strptime(from_date, "%Y-%m-%d")
                end_date = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)
                query = query.filter(Chat.created_at.between(start_date, end_date))
            except ValueError:
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD.")

        # Cluster/Subcluster filtering
        if subCluster:
            query = query.filter(Chat.subcategories.any(subCluster))
            logger.info(f"Filtering chats by subCluster: {subCluster}")
        elif cluster:
            query = query.filter(Chat.categories.any(cluster))
            logger.info(f"Filtering chats by cluster: {cluster}")

        # --- Total Count ---
        # Create a separate query for counting to avoid issues with columns/joins
        count_query = db.query(func.count(Chat.id))
        if from_date and to_date: count_query = count_query.filter(Chat.created_at.between(start_date, end_date))
        if subCluster: count_query = count_query.filter(Chat.subcategories.any(subCluster))
        elif cluster: count_query = count_query.filter(Chat.categories.any(cluster))
        total = count_query.scalar() or 0

        logger.info(f"Found {total} chats matching admin filters")

        # Apply ordering, offset, and limit to the main query
        results = query.order_by(Chat.updated_at.desc()).offset(skip).limit(limit).all()

        # Manually construct the response to match AdminChat schema
        admin_chats = []
        for row in results:
            chat = row[0] # The Chat object is the first element
            msg_count = row.message_count
            likes = row.likes_count
            dislikes = row.dislikes_count

            admin_chats.append(AdminChat(
                id=chat.id,
                title=chat.title,
                user=UserSchema.from_orm(chat.user) if chat.user else None,
                categories=chat.categories or [],
                subcategories=chat.subcategories or [],
                created_at=chat.created_at,
                updated_at=chat.updated_at,
                message_count=msg_count,
                likes=likes,
                dislikes=dislikes,
            ))

        return PaginatedResponse(items=admin_chats, total=total)

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error getting admin chats: {str(e)}", exc_info=True)
        return PaginatedResponse(items=[], total=0) # Return empty on error


@router.get("/chats/{chat_id}", response_model=AdminChatDetail) # Use AdminChatDetail schema
def get_admin_chat_detail(
        chat_id: UUID,
        db: Session = Depends(get_db),
        current_admin: User = Depends(get_current_admin_user)
):
    """
    Retrieve detailed information for a specific chat by chat_id for admin.
    """
    try:
        # Query the chat with eager loading of all related data
        chat = db.query(Chat).options(
            joinedload(Chat.user),
            selectinload(Chat.messages).options( # Load messages related options inside this
                selectinload(Message.reactions), # Eager load reactions for each message
                selectinload(Message.sources),   # Eager load sources for each message
                selectinload(Message.files).joinedload(MessageFile.file) # Eager load file data via MessageFile
            )
        ).filter(Chat.id == chat_id).first() # Filter and get the single chat

        if not chat:
            logger.warning(f"Admin requested non-existent chat: {chat_id}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

        # Use the AdminChatDetail schema for response validation and serialization
        # The messages will be ordered based on the model definition
        return AdminChatDetail.from_orm(chat)

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error retrieving admin chat detail {chat_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


@router.get("/users", response_model=PaginatedResponse[AdminUser])
def get_admin_users(
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db),
        current_admin: User = Depends(get_current_admin_user),
):
    """
    Get a list of users for admin view.
    """
    try:
        query = db.query(User)
        total = query.count()
        users = query.order_by(User.created_at.desc()).offset(skip).limit(limit).all()

        return PaginatedResponse(items=users, total=total)
    except Exception as e:
        logger.error(f"Error getting admin users: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve users")


@router.get("/users/{user_id}", response_model=AdminUser)
def get_admin_user_detail(
        user_id: UUID,
        db: Session = Depends(get_db),
        current_admin: User = Depends(get_current_admin_user)
):
    """
    Get details for a specific user.
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user
    except Exception as e:
        logger.error(f"Error getting user detail {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve user details")