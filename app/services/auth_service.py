import logging

from datetime import timedelta
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.config import settings
from app.db.models import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.user import UserCreate

logger = logging.getLogger(__name__)


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """
    Authenticate a user by username and password.
    Returns the user if authentication is successful, None otherwise.
    """
    user = db.query(User).filter(User.username == username).first()

    if not user:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user


def login(db: Session, login_data: LoginRequest) -> dict:
    """
    Login a user and return access token.
    """
    user = authenticate_user(
        db=db,
        username=login_data.username,
        password=login_data.password
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }


def register(db: Session, register_data: RegisterRequest) -> dict:
    try:
        # Check if username already exists
        user_by_username = db.query(User).filter(User.username == register_data.username).first()
        if user_by_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already registered"
            )

        # Check if email already exists
        user_by_email = db.query(User).filter(User.email == register_data.email).first()
        if user_by_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

        # Create new user data
        try:
            user_data = UserCreate(
                username=register_data.username,
                email=register_data.email,
                password=register_data.password,
                full_name=register_data.full_name
            )
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e)
            )

        # Create user in DB
        db_user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=get_password_hash(user_data.password),
            full_name=user_data.full_name,
            is_active=True,
            is_admin=False
        )

        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        # Create access token
        access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(db_user.id)},
            expires_delta=access_token_expires
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": db_user
        }
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error in register service: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during registration"
        )