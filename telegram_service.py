from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from telegram import Bot
from telegram.error import TelegramError

from config import get_settings
from models import Subscription, utcnow


logger = logging.getLogger(__name__)


async def _send_access(subscription: Subscription) -> None:
    settings = get_settings()
    bot = Bot(settings.TELEGRAM_BOT_TOKEN)
    expire_date = utcnow() + timedelta(hours=settings.INVITE_LINK_EXPIRE_HOURS)
    invite = await bot.create_chat_invite_link(
        chat_id=settings.TELEGRAM_PRIVATE_CHANNEL_ID,
        expire_date=expire_date,
        member_limit=settings.INVITE_LINK_MEMBER_LIMIT,
        creates_join_request=False,
    )
    await bot.send_message(
        chat_id=subscription.user.telegram_id,
        text=(
            "Pagamento aprovado.\n"
            "Seu acesso VIP foi liberado.\n\n"
            f"Entre pelo link: {invite.invite_link}\n"
            f"Vencimento do plano: {subscription.expire_date:%d/%m/%Y}"
        ),
    )


def send_access_invite(subscription: Subscription) -> None:
    try:
        asyncio.run(_send_access(subscription))
    except TelegramError:
        logger.exception("Failed to send access invite subscription_id=%s", subscription.id)


async def _expire_access(telegram_id: int) -> None:
    settings = get_settings()
    bot = Bot(settings.TELEGRAM_BOT_TOKEN)
    try:
        await bot.ban_chat_member(chat_id=settings.TELEGRAM_PRIVATE_CHANNEL_ID, user_id=telegram_id)
        await bot.unban_chat_member(chat_id=settings.TELEGRAM_PRIVATE_CHANNEL_ID, user_id=telegram_id, only_if_banned=True)
    finally:
        await bot.send_message(
            chat_id=telegram_id,
            text="Sua assinatura VIP expirou. Para voltar, assine novamente pelo menu /start.",
        )


def expire_access(telegram_id: int) -> None:
    try:
        asyncio.run(_expire_access(telegram_id))
    except TelegramError:
        logger.exception("Failed to expire Telegram access telegram_id=%s", telegram_id)
