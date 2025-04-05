import logging

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Dict, Any
from app.core.dependencies import get_current_admin_user
from app.db.models import Chat, Message, Reaction, User
from app.db.session import get_db
from sqlalchemy import func, case, text

router = APIRouter(prefix="/admin", tags=["Admin"])
logger = logging.getLogger(__name__)

# Hard-coded mappings
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

all_sub_clusters = []
for cluster in sub_clusters.keys():
    all_sub_clusters.extend(sub_clusters[cluster])
all_sub_clusters.append('Бессмысленный запрос')


@router.get("/clusters")
def get_clusters_stats(
        db: Session = Depends(get_db),
        current_admin=Depends(get_current_admin_user),
        parent_cluster: str = None
) -> Dict[str, Any]:
    """
    Get statistics about clusters and sub-clusters used in chats.
    If parent_cluster is provided, returns sub-clusters for that cluster.
    """
    try:
        chats = db.query(Chat).all()

        if parent_cluster:
            # Return subclusters for the specified parent cluster
            if parent_cluster in sub_clusters:
                subcategories = sub_clusters[parent_cluster]
                subcategory_counts = {sub: 0 for sub in subcategories}

                for chat in chats:
                    if chat.subcategories:
                        for sub in chat.subcategories:
                            if sub in subcategory_counts:
                                subcategory_counts[sub] += 1

                sub_stats = [
                    {"name": sub, "requests": count, "color": "#" + format(hash(sub) % 0xFFFFFF, '06x')}
                    for sub, count in subcategory_counts.items()
                ]

                return {
                    "general_clusters": [],
                    "sub_clusters": sub_stats
                }
            else:
                # Return empty list if parent cluster doesn't exist
                return {
                    "general_clusters": [],
                    "sub_clusters": []
                }
        else:
            # Return general clusters
            category_counts = {cat: 0 for cat in general_clusters}
            subcategory_counts = {sub: 0 for sub in all_sub_clusters}

            for chat in chats:
                if chat.categories:
                    for cat in chat.categories:
                        if cat in category_counts:
                            category_counts[cat] += 1
                if chat.subcategories:
                    for sub in chat.subcategories:
                        if sub in subcategory_counts:
                            subcategory_counts[sub] += 1

            # Hard-coded colors for general clusters
            default_colors = {
                'Общие вопросы о работе с системой': "#8884d8",
                'Процессы закупок': "#82ca9d",
                'Работа с контрактами': "#ffc658",
                'Оферты и коммерческие предложения': "#ff8042",
                'Документы': "#0088FE",
                'Работа с категориями продукции': "#00C49F",
                'Техническая поддержка': "#FFBB28",
                'Чаты и обсуждения': "#FF8042",
                'Финансовые операции': "#a4de6c",
                'Новости и обновления': "#d0ed57",
                'Регуляторные и юридические вопросы': "#8884d8",
                'Ошибки и предупреждения': "#82ca9d",
                'Бессмысленный запрос': "#ff8042"
            }

            general_stats = [
                {"name": cat, "requests": count, "color": default_colors.get(cat, "#8884d8")}
                for cat, count in category_counts.items()
            ]

            return {
                "general_clusters": general_stats,
                "sub_clusters": []
            }

    except Exception as e:
        logger.error(f"Error getting cluster stats: {str(e)}", exc_info=True)
        # Return empty data instead of failing
        return {
            "general_clusters": [],
            "sub_clusters": []
        }


@router.get("/cluster-timeseries")
def get_cluster_timeseries(
        start_date: str = Query(..., description="Start date in YYYY-MM-DD"),
        end_date: str = Query(..., description="End date in YYYY-MM-DD"),
        db: Session = Depends(get_db),
        current_admin=Depends(get_current_admin_user)
) -> List[Dict[str, Any]]:
    """
    Returns time series data per day for each general cluster.
    For each day between start_date and end_date, count chats where the cluster is applied.
    """
    # We use a raw SQL query using PostgreSQL's ANY operator.
    query = text("""
        SELECT 
          (created_at::date) as date,
          unnest(categories) as category,
          count(*) as count
        FROM chat
        WHERE created_at >= :start_date AND created_at <= :end_date
        GROUP BY date, category
        ORDER BY date
    """)
    result = db.execute(query, {"start_date": start_date, "end_date": end_date}).fetchall()
    # Build a mapping: date -> { cluster: count, ... }
    timeseries = {}
    for row in result:
        date_str = row['date'].isoformat()
        cat = row['category']
        if cat not in general_clusters:
            continue
        if date_str not in timeseries:
            timeseries[date_str] = {"date": date_str}
        timeseries[date_str][cat] = row['count']
    # Return list sorted by date
    return sorted(timeseries.values(), key=lambda x: x["date"])


@router.get("/chats")
def get_admin_chats(
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db),
        current_admin=Depends(get_current_admin_user)
) -> Dict[str, Any]:
    chats = db.query(Chat).offset(skip).limit(limit).all()
    chat_list = []
    for chat in chats:
        chat_list.append({
            "id": str(chat.id),
            "title": chat.title,
            "user": chat.user.email if chat.user else "",
            "categories": chat.categories or [],
            "subcategories": chat.subcategories or [],
            "created_at": chat.created_at.isoformat() if chat.created_at else None,
            "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
            "message_count": len(chat.messages) if chat.messages else 0,
            "likes": sum(1 for m in chat.messages if
                         m.reactions and any(r.reaction_type.lower() == "like" for r in m.reactions)),
            "dislikes": sum(1 for m in chat.messages if
                            m.reactions and any(r.reaction_type.lower() == "dislike" for r in m.reactions)),
        })
    total = db.query(Chat).count()
    return {"items": chat_list, "total": total}


@router.get("/chats/{chat_id}")
def get_admin_chat(
        chat_id: str,
        db: Session = Depends(get_db),
        current_admin=Depends(get_current_admin_user)
) -> Dict[str, Any]:
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = []
    for msg in chat.messages:
        messages.append({
            "id": str(msg.id),
            "content": msg.content,
            "message_type": msg.message_type.value if hasattr(msg.message_type, "value") else msg.message_type,
            "status": msg.status.value if hasattr(msg.status, "value") else msg.status,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "updated_at": msg.updated_at.isoformat() if msg.updated_at else None,
            "reactions": [
                {
                    "id": str(r.id),
                    "reaction_type": r.reaction_type.value if hasattr(r.reaction_type, "value") else r.reaction_type,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                } for r in msg.reactions
            ],
            "files": [
                {
                    "id": str(f.file.id) if f.file else "",
                    "name": f.file.name if f.file else "",
                    "file_type": f.file.file_type.value if f.file and hasattr(f.file.file_type, "value") else (
                        f.file.file_type if f.file else ""),
                    "preview_url": f.file.preview.url if f.file and f.file.preview else "",
                } for f in msg.files
            ]
        })
    return {
        "id": str(chat.id),
        "title": chat.title,
        "user": {
            "id": str(chat.user.id) if chat.user else "",
            "username": chat.user.username if chat.user else "",
            "email": chat.user.email if chat.user else "",
        },
        "categories": chat.categories or [],
        "subcategories": chat.subcategories or [],
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
        "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
        "messages": messages,
    }


@router.get("/feedback")
def get_feedback_stats(
        from_date: str = Query(None, description="Start date in YYYY-MM-DD"),
        to_date: str = Query(None, description="End date in YYYY-MM-DD"),
        db: Session = Depends(get_db),
        current_admin=Depends(get_current_admin_user)
) -> List[Dict[str, Any]]:
    """
    Returns feedback stats per day.
    """
    try:
        # Set default date range if not provided
        today = datetime.utcnow().date()

        if from_date:
            start_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        else:
            start_date = today - timedelta(days=7)

        if to_date:
            end_date = datetime.strptime(to_date, "%Y-%m-%d").date()
        else:
            end_date = today

        # Generate dates in range
        date_range = []
        current_date = start_date
        while current_date <= end_date:
            date_range.append(current_date)
            current_date += timedelta(days=1)

        # Query for feedback data
        feedback_data = db.query(
            func.date(Message.created_at).label("date"),
            func.sum(case([(Reaction.reaction_type == "like", 1)], else_=0)).label("likes"),
            func.sum(case([(Reaction.reaction_type == "dislike", 1)], else_=0)).label("dislikes")
        ).outerjoin(Reaction, Reaction.message_id == Message.id) \
            .filter(Message.created_at >= start_date) \
            .filter(Message.created_at <= end_date + timedelta(days=1)) \
            .group_by(func.date(Message.created_at)) \
            .order_by(func.date(Message.created_at)).all()

        # Convert to dictionary by date
        data_by_date = {row.date.isoformat(): {
            "date": row.date.isoformat(),
            "likes": int(row.likes or 0),
            "dislikes": int(row.dislikes or 0),
        } for row in feedback_data}

        # Ensure all dates in range have data
        result = []
        for date in date_range:
            date_str = date.isoformat()
            if date_str in data_by_date:
                result.append(data_by_date[date_str])
            else:
                result.append({
                    "date": date_str,
                    "likes": 0,
                    "dislikes": 0,
                })

        return result

    except Exception as e:
        logger.error(f"Error getting feedback stats: {str(e)}", exc_info=True)
        # Return empty array instead of failing
        return []


@router.get("/users")
def get_admin_users(
        skip: int = 0,
        limit: int = 100,
        db: Session = Depends(get_db),
        current_admin=Depends(get_current_admin_user)
) -> Dict[str, Any]:
    users = db.query(User).offset(skip).limit(limit).all()
    user_list = []
    for user in users:
        user_list.append({
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        })
    total = db.query(User).count()
    return {"items": user_list, "total": total}

@router.get("/stats")
def get_admin_stats(
        db: Session = Depends(get_db),
        current_admin=Depends(get_current_admin_user)
) -> Dict[str, Any]:
    """
    Get admin dashboard statistics
    """
    try:
        # Get user count
        total_users = db.query(User).count()

        # Get active chats count (chats from last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        active_chats = db.query(Chat).filter(Chat.updated_at >= week_ago).count()

        # Get reaction counts
        positive_reactions = db.query(Reaction).filter(Reaction.reaction_type == "like").count()
        negative_reactions = db.query(Reaction).filter(Reaction.reaction_type == "dislike").count()

        return {
            "totalUsers": total_users,
            "activeChats": active_chats,
            "positiveReactions": positive_reactions,
            "negativeReactions": negative_reactions,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting admin stats: {str(e)}", exc_info=True)
        # Return default values instead of failing
        return {
            "totalUsers": 0,
            "activeChats": 0,
            "positiveReactions": 0,
            "negativeReactions": 0,
            "timestamp": datetime.utcnow().isoformat()
        }

