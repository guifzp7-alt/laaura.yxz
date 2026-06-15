from __future__ import annotations

import json
import logging

from flask import Flask, jsonify, render_template, request
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from config import get_settings
from database import SessionLocal, init_db
from logging_config import setup_logging
from models import Order, OrderStatus, WebhookEvent, utcnow
from repositories import activate_subscription, seed_default_plans
from sigiliopay_client import extract_sigiliopay_payment_ids, normalize_sigiliopay_status, verify_sigiliopay_signature
from telegram_service import send_access_invite


setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()
app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/preview")
def preview():
    return render_template("preview.html")


@app.post("/webhook/sigiliopay")
def sigiliopay_webhook():
    raw_body = request.get_data()
    signature = request.headers.get(settings.SIGILIOPAY_WEBHOOK_HEADER)
    if not verify_sigiliopay_signature(raw_body, signature):
        logger.warning("Invalid SigilioPay webhook signature")
        return jsonify({"error": "invalid signature"}), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid json"}), 400

    payment_id, transaction_id, event_id = extract_sigiliopay_payment_ids(payload)
    normalized_status = normalize_sigiliopay_status(payload)
    logger.info(
        "SigilioPay webhook received event_id=%s payment_id=%s transaction_id=%s status=%s",
        event_id,
        payment_id,
        transaction_id,
        normalized_status,
    )

    with SessionLocal() as db:
        event = WebhookEvent(
            provider="sigiliopay",
            event_id=event_id,
            payment_id=payment_id,
            payload=json.dumps(payload, ensure_ascii=False),
        )
        db.add(event)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.info("Duplicate webhook ignored event_id=%s", event_id)
            return jsonify({"status": "duplicate"}), 200

        order = db.scalar(
            select(Order).where(
                or_(
                    Order.payment_id == payment_id if payment_id else False,
                    Order.transaction_id == transaction_id if transaction_id else False,
                )
            )
        )
        if not order:
            event.processed = True
            db.commit()
            logger.warning("Payment not found for webhook event_id=%s", event_id)
            return jsonify({"status": "payment_not_found"}), 404

        if order.status == OrderStatus.PAID.value:
            event.processed = True
            order.webhook_event_id = event_id
            db.commit()
            return jsonify({"status": "already_paid"}), 200

        if normalized_status == "paid":
            order.status = OrderStatus.PAID.value
            order.paid_at = utcnow()
            order.webhook_event_id = event_id
            subscription = activate_subscription(db, order)
            event.processed = True
            db.commit()
            send_access_invite(subscription)
            return jsonify({"status": "paid"}), 200

        if normalized_status == "canceled":
            order.status = OrderStatus.CANCELED.value
            order.canceled_at = utcnow()
        else:
            order.status = OrderStatus.PENDING.value
        order.webhook_event_id = event_id
        event.processed = True
        db.commit()

    return jsonify({"status": normalized_status}), 200


def create_app() -> Flask:
    init_db()
    with SessionLocal() as db:
        seed_default_plans(db)
    return app


if __name__ == "__main__":
    create_app()
    app.run(host=settings.WEBHOOK_HOST, port=settings.WEBHOOK_PORT)
