from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import requests

from config import get_settings
from models import utcnow


logger = logging.getLogger("payments.sigiliopay")


@dataclass(frozen=True)
class PixCharge:
    payment_id: str
    transaction_id: str
    qr_code_url: str | None
    qr_code_base64: str | None
    copy_paste: str
    status: str
    checkout_url: str | None
    raw: dict[str, Any]


class SigilioPayClient:
    """SigilioPay PIX client.

    SigiloPay uses x-public-key and x-secret-key headers for authentication.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.SIGILIOPAY_API_BASE_URL.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "x-public-key": self.settings.SIGILIOPAY_PUBLIC_KEY,
                "x-secret-key": self.settings.SIGILIOPAY_SECRET_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def create_pix_charge(
        self,
        *,
        order_id: int,
        amount: Decimal,
        description: str,
        payer_name: str,
        payer_telegram_id: int,
    ) -> PixCharge:
        self.settings.validate_payments()
        identifier = f"telegram-order-{order_id}"
        payload = {
            "identifier": identifier,
            "amount": float(amount),
            "client": {
                "name": payer_name or f"Telegram {payer_telegram_id}",
                "email": f"telegram-{payer_telegram_id}@example.com",
                "phone": "11999999999",
                "document": "11144477735",
            },
            "products": [
                {
                    "id": f"plan-{order_id}",
                    "name": description,
                    "quantity": 1,
                    "price": float(amount),
                }
            ],
            "dueDate": (utcnow() + timedelta(days=1)).date().isoformat(),
            "metadata": {
                "order_id": str(order_id),
                "telegram_id": str(payer_telegram_id),
            },
            "callbackUrl": self.settings.sigiliopay_webhook_url,
        }

        response = self.session.post(f"{self.base_url}/gateway/pix/receive", json=payload, timeout=30)
        try:
            response.raise_for_status()
        except requests.HTTPError:
            logger.error("SigiloPay PIX creation failed status=%s body=%s", response.status_code, response.text)
            raise

        data = response.json()
        logger.info("SigiloPay charge created order_id=%s response=%s", order_id, data)
        return self._parse_charge(data, fallback_identifier=identifier)

    def _parse_charge(self, data: dict[str, Any], *, fallback_identifier: str) -> PixCharge:
        pix = data.get("pix") if isinstance(data.get("pix"), dict) else {}
        order = data.get("order") if isinstance(data.get("order"), dict) else {}

        payment_id = str(
            data.get("transactionId")
            or data.get("transaction_id")
            or data.get("id")
            or order.get("id")
            or fallback_identifier
        )
        transaction_id = str(order.get("identifier") or data.get("identifier") or fallback_identifier)
        copy_paste = str(
            pix.get("qrCode")
            or pix.get("qrcode")
            or pix.get("qr_code")
            or pix.get("copyPaste")
            or pix.get("copy_paste")
            or pix.get("payload")
            or pix.get("code")
            or ""
        )

        if not payment_id or not copy_paste:
            raise ValueError(f"Unexpected SigiloPay PIX response: {data}")

        return PixCharge(
            payment_id=payment_id,
            transaction_id=transaction_id,
            qr_code_url=pix.get("qrCodeUrl") or pix.get("qr_code_url") or pix.get("imageUrl") or pix.get("image_url"),
            qr_code_base64=pix.get("qrCodeBase64") or pix.get("qr_code_base64") or pix.get("base64"),
            copy_paste=copy_paste,
            status=str(data.get("status") or "PENDING").lower(),
            checkout_url=pix.get("ticketUrl") or pix.get("checkoutUrl") or pix.get("url"),
            raw=data,
        )


def verify_sigiliopay_signature(raw_body: bytes, received_signature: str | None) -> bool:
    settings = get_settings()
    if not settings.SIGILIOPAY_WEBHOOK_SECRET:
        logger.warning("SIGILIOPAY_WEBHOOK_SECRET not set; webhook signature validation is disabled")
        return True
    if not received_signature:
        return False

    normalized = received_signature.removeprefix("sha256=").strip()
    expected = hmac.new(
        settings.SIGILIOPAY_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, normalized)


def normalize_sigiliopay_status(payload: dict[str, Any]) -> str:
    raw = str(
        payload.get("status")
        or payload.get("payment_status")
        or payload.get("paymentStatus")
        or payload.get("event")
        or payload.get("type")
        or ""
    ).lower()

    if raw in {"ok", "paid", "approved", "confirmed", "completed", "settled"} or "paid" in raw or "approved" in raw:
        return "paid"
    if raw in {"canceled", "cancelled", "expired", "refused", "declined", "failed", "refunded", "rejected"}:
        return "canceled"
    return "pending"


def extract_sigiliopay_payment_ids(payload: dict[str, Any]) -> tuple[str | None, str | None, str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    payment_id = data.get("transactionId") or data.get("transaction_id") or data.get("payment_id") or data.get("paymentId") or data.get("id")
    order = data.get("order") if isinstance(data.get("order"), dict) else {}
    transaction_id = data.get("identifier") or order.get("identifier") or data.get("transaction_id") or data.get("transactionId") or data.get("txid")
    event_id = payload.get("event_id") or payload.get("eventId") or payload.get("id") or data.get("id")
    fallback = payment_id or transaction_id or hashlib.sha256(str(payload).encode("utf-8")).hexdigest()
    return (
        str(payment_id) if payment_id else None,
        str(transaction_id) if transaction_id else None,
        str(event_id or fallback),
    )
