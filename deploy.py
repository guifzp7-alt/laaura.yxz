from __future__ import annotations

import logging
import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update

from bot import build_application
from database import SessionLocal, init_db
from logging_config import setup_logging
from repositories import seed_default_plans
from scheduler import expire_subscriptions
from webhook import app as flask_app


logger = logging.getLogger(__name__)


def bootstrap_database() -> None:
    init_db()
    with SessionLocal() as db:
        seed_default_plans(db)


def start_bot() -> None:
    application = build_application()
    logger.info("Starting Telegram bot polling")
    application.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)


def start_scheduler() -> None:
    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(expire_subscriptions, "cron", hour=3, minute=0, id="expire_subscriptions", replace_existing=True)
    scheduler.add_job(expire_subscriptions, "date", id="expire_subscriptions_on_start", replace_existing=True)
    scheduler.start()
    logger.info("Subscription scheduler started")


def start_background_services() -> None:
    if os.getenv("START_BACKGROUND_SERVICES", "true").lower() != "true":
        return

    start_scheduler()
    threading.Thread(target=start_bot, name="telegram-bot", daemon=True).start()


setup_logging()
bootstrap_database()
start_background_services()

app = flask_app
