from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    MONGO_URI: str
    MONGODB_DATABASE: str = "pillars_fc"
    FRONTEND_ORIGIN: str = "http://localhost:3000"
    RESEND_API_KEY: str | None = None
    MAIL_FROM_RESEND: str | None = None
    MAIL_USERNAME: str | None = None
    ADMIN_USERNAME: str | None = None
    ADMIN_PASSWORD_HASH: str | None = None
    ADMIN_SESSION_SECRET: str | None = None
    ADMIN_SESSION_COOKIE_SECURE: bool = True
    ADMIN_SESSION_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    ADMIN_SESSION_TTL_SECONDS: int = 28800
    MEMBER_SESSION_SECRET: str | None = None
    MEMBER_SESSION_TTL_SECONDS: int = 28800
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
