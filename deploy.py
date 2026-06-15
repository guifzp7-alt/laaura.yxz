from __future__ import annotations

import logging
import os
import threading
import asyncio
from concurrent.futures import Future

from apscheduler.schedulers.background import BackgroundScheduler
from flask import jsonify, request
from telegram import Update

from bot import build_application
from config import get_settings
from database import SessionLocal, init_db
from logging_config import setup_logging
from repositories import seed_default_plans
from scheduler import expire_subscriptions
from webhook import app as flask_app


logger = logging.getLogger(__name__)
settings = get_settings()
telegram_application = build_application()
telegram_loop = asyncio.new_event_loop()


def bootstrap_database() -> None:
    init_db()
    with SessionLocal() as db:
        seed_default_plans(db)


async def start_telegram_application() -> None:
    webhook_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/telegram/{settings.TELEGRAM_BOT_TOKEN}"
    await telegram_application.initialize()
    await telegram_application.start()
    await telegram_application.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)
    logger.info("Telegram webhook configured url=%s", webhook_url)


def run_telegram_loop() -> None:
    asyncio.set_event_loop(telegram_loop)
    telegram_loop.run_forever()


def start_bot_webhook() -> None:
    threading.Thread(target=run_telegram_loop, name="telegram-loop", daemon=True).start()
    asyncio.run_coroutine_threadsafe(start_telegram_application(), telegram_loop).result(timeout=30)


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
    start_bot_webhook()


setup_logging()
bootstrap_database()
start_background_services()

app = flask_app


def log_update_result(future: Future) -> None:
    try:
        future.result()
    except Exception:
        logger.exception("Failed to process Telegram update")


@app.post("/telegram/<path:token>")
def telegram_webhook(token: str):
    if token != settings.TELEGRAM_BOT_TOKEN:
        return jsonify({"error": "forbidden"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid json"}), 400

    update = Update.de_json(payload, telegram_application.bot)
    future = asyncio.run_coroutine_threadsafe(telegram_application.process_update(update), telegram_loop)
    future.add_done_callback(log_update_result)
    return jsonify({"ok": True})
