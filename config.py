from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv


load_dotenv()


def _csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


class Settings:
    """Application settings loaded from environment variables."""

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_PRIVATE_CHANNEL_ID: str = os.getenv("TELEGRAM_PRIVATE_CHANNEL_ID", "")
    ADMIN_IDS: list[int] = _csv_ints(os.getenv("ADMIN_IDS", ""))

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///database.sqlite3")

    PAYMENT_PROVIDER: str = os.getenv("PAYMENT_PROVIDER", "sigiliopay").lower()

    SIGILIOPAY_API_BASE_URL: str = os.getenv("SIGILIOPAY_API_BASE_URL", "https://app.sigilopay.com.br/api/v1")
    SIGILIOPAY_PUBLIC_KEY: str = os.getenv("SIGILIOPAY_PUBLIC_KEY", "")
    SIGILIOPAY_SECRET_KEY: str = os.getenv("SIGILIOPAY_SECRET_KEY", "")
    SIGILIOPAY_WEBHOOK_SECRET: str = os.getenv("SIGILIOPAY_WEBHOOK_SECRET", "")
    SIGILIOPAY_WEBHOOK_HEADER: str = os.getenv("SIGILIOPAY_WEBHOOK_HEADER", "X-SigilioPay-Signature")

    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "https://example.com")
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8000"))

    PIX_EXPIRATION_MINUTES: int = int(os.getenv("PIX_EXPIRATION_MINUTES", "30"))
    INVITE_LINK_EXPIRE_HOURS: int = int(os.getenv("INVITE_LINK_EXPIRE_HOURS", "24"))
    INVITE_LINK_MEMBER_LIMIT: int = int(os.getenv("INVITE_LINK_MEMBER_LIMIT", "1"))

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    def validate_bot(self) -> None:
        missing = []
        if not self.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.TELEGRAM_PRIVATE_CHANNEL_ID:
            missing.append("TELEGRAM_PRIVATE_CHANNEL_ID")
        if missing:
            raise RuntimeError(f"Missing required bot settings: {', '.join(missing)}")

    def validate_payments(self) -> None:
        missing = []
        if self.PAYMENT_PROVIDER != "sigiliopay":
            raise RuntimeError("PAYMENT_PROVIDER must be 'sigiliopay'")
        if not self.SIGILIOPAY_PUBLIC_KEY:
            missing.append("SIGILIOPAY_PUBLIC_KEY")
        if not self.SIGILIOPAY_SECRET_KEY:
            missing.append("SIGILIOPAY_SECRET_KEY")
        if not self.PUBLIC_BASE_URL:
            missing.append("PUBLIC_BASE_URL")
        if missing:
            raise RuntimeError(f"Missing required payment settings: {', '.join(missing)}")

    @property
    def sigiliopay_webhook_url(self) -> str:
        return f"{self.PUBLIC_BASE_URL.rstrip('/')}/webhook/sigiliopay"

    def as_dict(self) -> dict[str, Any]:
        return {
            "database_url": self.DATABASE_URL,
            "payment_provider": self.PAYMENT_PROVIDER,
            "sigiliopay_api_base_url": self.SIGILIOPAY_API_BASE_URL,
            "public_base_url": self.PUBLIC_BASE_URL,
            "webhook_host": self.WEBHOOK_HOST,
            "webhook_port": self.WEBHOOK_PORT,
            "log_level": self.LOG_LEVEL,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
