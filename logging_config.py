from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import get_settings


LOG_DIR = Path("logs")


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    settings = get_settings()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        RotatingFileHandler(LOG_DIR / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"),
        RotatingFileHandler(LOG_DIR / "payments.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"),
    ]

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        handlers=handlers,
        force=True,
    )
