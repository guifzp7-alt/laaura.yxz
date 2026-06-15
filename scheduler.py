from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from database import SessionLocal, init_db
from logging_config import setup_logging
from models import Subscription, utcnow
from repositories import seed_default_plans
from telegram_service import expire_access


logger = logging.getLogger(__name__)


def expire_subscriptions() -> None:
    now = utcnow()
    with SessionLocal() as db:
        expired = db.scalars(
            select(Subscription).where(Subscription.active.is_(True), Subscription.expire_date <= now)
        ).all()
        for subscription in expired:
            subscription.active = False
            db.commit()
            logger.info("Expiring subscription_id=%s user_id=%s", subscription.id, subscription.user_id)
            expire_access(subscription.user.telegram_id)


def run_scheduler() -> None:
    setup_logging()
    init_db()
    with SessionLocal() as db:
        seed_default_plans(db)

    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(expire_subscriptions, "cron", hour=3, minute=0, id="expire_subscriptions", replace_existing=True)
    scheduler.add_job(expire_subscriptions, "date", id="expire_subscriptions_on_start", replace_existing=True)
    logger.info("Starting subscription scheduler")
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()
