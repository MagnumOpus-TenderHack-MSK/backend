import os
import logging
from typing import List
from pathlib import Path
from pydantic_settings import BaseSettings

# Project root directory
ROOT_DIR = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    # Application settings
    APP_NAME: str = "Chat Application"
    APP_VERSION: str = "1.0"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True

    # Public facing URL for AI service callbacks
    # If set, this will be used instead of the request base URL for callbacks
    # Example: "https://api.example.com"
    CALLBACK_HOST: str = ""

    # Database settings
    DB_DRIVER: str = "postgresql"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_NAME: str = "chat_db"

    # SQLAlchemy settings - disable echo to reduce logging
    SQLALCHEMY_ECHO: bool = False

    # JWT settings
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Redis settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # Celery settings
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # File upload settings
    UPLOAD_DIR: str = "static/uploads"
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10 MB


    PREVIEW_SERVICE_URL: str
    PREVIEW_SERVICE_API_KEY: str

    # AI service settings
    AI_SERVICE_URL: str
    AI_SERVICE_API_KEY: str
    AI_SERVICE_MAX_TOKENS: int = 2000
    AI_SERVICE_TEMPERATURE: float = 0.7
    AI_SERVICE_STREAM_CHUNKS: bool = True

    @property
    def DATABASE_URL(self) -> str:
        """
        Get the database connection URL.
        """
        return f"{self.DB_DRIVER}://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def REDIS_URL(self) -> str:
        """
        Get the Redis connection URL.
        """
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def UPLOAD_PATH(self) -> Path:
        """
        Get the upload directory path.
        """
        path = ROOT_DIR / self.UPLOAD_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Configure logging
def configure_logging():
    """Configure logging to reduce noise from SQLAlchemy."""
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.orm').setLevel(logging.WARNING)


# Configure logging
configure_logging()

# Create global settings instance
settings = Settings()