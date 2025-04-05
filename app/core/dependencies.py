from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.security import get_current_user
from app.db.models import User, Chat
from app.db.session import get_db


async def get_current_active_user(
        current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency to get the current active user.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


async def get_chat_by_id(
        chat_id: UUID,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user),
) -> Chat:
    """
    Dependency to get a chat by ID and check if the current user has access.
    """
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

    return chat

async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Get current user and verify they have admin privileges.
    For development, we'll allow all users to access admin features.
    In production, uncomment the check for is_admin.
    """
    # DEVELOPMENT MODE: Allow all users to access admin features
    # PRODUCTION MODE: Uncomment the next lines to enforce admin access
    # if not current_user.is_admin:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Admin privileges required"
    #     )
    return current_user