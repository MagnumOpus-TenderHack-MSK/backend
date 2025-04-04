import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.db.models import User
from app.schemas.auth import (
    LoginRequest, LoginResponse, RegisterRequest, RegisterResponse
)
from app.schemas.user import User as UserSchema
from app.services import auth_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
def login(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Login with username and password.
    """
    result = auth_service.login(db=db, login_data=login_data)
    return result


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(
        register_data: RegisterRequest,
        db: Session = Depends(get_db)
):
    """
    Register a new user.
    """
    try:
        # Validate password length here at API level
        if len(register_data.password) < 8:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password must be at least 8 characters long"
            )

        result = auth_service.register(db=db, register_data=register_data)
        return result
    except HTTPException:
        # Re-raise HTTP exceptions from service
        raise
    except Exception as e:
        logger.error(f"Unexpected registration error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed due to an unexpected error"
        )


@router.get("/me", response_model=UserSchema)
def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    Get current user information.
    """
    return current_user