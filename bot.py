from __future__ import annotations

import base64
import json
import logging
import tempfile
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from config import get_settings
from database import SessionLocal, init_db
from logging_config import setup_logging
from models import OrderStatus, Plan, Subscription, User
from repositories import create_order, revenue_total, seed_default_plans, upsert_user
from sigiliopay_client import SigilioPayClient


logger = logging.getLogger(__name__)
settings = get_settings()
WELCOME_MEDIA_DIR = Path("static")
WELCOME_SETTINGS_PATH = Path("welcome_settings.json")
WELCOME_MEDIA_DIR.mkdir(exist_ok=True)
DEFAULT_WELCOME_TEXT = (
    "oii vida...\n\n"
    "Seja bem-vindo ao VIP. Aqui voce recebe acesso ao conteudo privado e aos bonus disponiveis para assinantes.\n\n"
    "Voce vai ter acesso a:\n"
    "- Conteudos exclusivos\n"
    "- Atualizacoes no canal VIP\n"
    "- Midias completas\n"
    "- Bonus para assinantes\n\n"
    "Atencao: conteudo permitido somente para maiores de 18 anos.\n"
    "Escolha um plano abaixo para gerar seu PIX."
)
FALLBACK_WELCOME_MEDIA_FILES = [
    "welcome1.jpg",
    "welcome1.png",
    "welcome1.mp4",
    "welcome2.jpg",
    "welcome2.png",
    "welcome2.mp4",
]


def load_welcome_settings() -> dict:
    if not WELCOME_SETTINGS_PATH.exists():
        return {"text": DEFAULT_WELCOME_TEXT, "media": []}
    try:
        data = json.loads(WELCOME_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to load welcome settings")
        return {"text": DEFAULT_WELCOME_TEXT, "media": []}
    return {
        "text": str(data.get("text") or DEFAULT_WELCOME_TEXT),
        "media": [str(item) for item in data.get("media", []) if isinstance(item, str)],
    }


def save_welcome_settings(data: dict) -> None:
    WELCOME_SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def preview_web_app() -> WebAppInfo:
    return WebAppInfo(url=f"{settings.PUBLIC_BASE_URL.rstrip('/')}/preview")


def get_payment_client() -> SigilioPayClient:
    return SigilioPayClient()


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Assinar VIP", callback_data="age_gate")],
            [InlineKeyboardButton("Ver previa👀", web_app=preview_web_app())],
            [InlineKeyboardButton("Minha assinatura", callback_data="my_plans")],
            [InlineKeyboardButton("Suporte", callback_data="support")],
        ]
    )


def plans_keyboard(plans: list[Plan]) -> InlineKeyboardMarkup:
    buttons = []
    for plan in plans:
        buttons.append([InlineKeyboardButton(f"{plan.name} - R$ {plan.price:.2f}", callback_data=f"plan:{plan.id}")])
    buttons.append([InlineKeyboardButton("Ver previa👀", web_app=preview_web_app())])
    buttons.append([InlineKeyboardButton("Minha assinatura", callback_data="my_plans")])
    buttons.append([InlineKeyboardButton("Suporte", callback_data="support")])
    return InlineKeyboardMarkup(buttons)


def age_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Tenho mais de 18 anos", callback_data="plans")],
            [InlineKeyboardButton("Voltar ao menu", callback_data="menu")],
        ]
    )


async def answer_callback_text(query, text: str, reply_markup: InlineKeyboardMarkup | None = None, parse_mode: str | None = None) -> None:
    if query.message and (query.message.photo or query.message.video):
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        with SessionLocal() as db:
            upsert_user(db, user.id, user.username, user.first_name)

    if update.message:
        await send_welcome_media(update, context)
        await send_welcome_offer(update, context)


async def send_welcome_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    settings_data = load_welcome_settings()
    configured_media = [Path(item) for item in settings_data["media"]]
    fallback_media = [WELCOME_MEDIA_DIR / filename for filename in FALLBACK_WELCOME_MEDIA_FILES]

    for path in configured_media or fallback_media:
        if not path.exists():
            continue

        suffix = path.suffix.lower()
        with path.open("rb") as media:
            if suffix in {".mp4", ".mov"}:
                await update.message.reply_video(video=media)
            else:
                await update.message.reply_photo(photo=media)


async def send_welcome_offer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    with SessionLocal() as db:
        plans = db.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.price.asc())).all()

    text = load_welcome_settings()["text"]

    if plans:
        await update.message.reply_text(text, reply_markup=plans_keyboard(plans))
    else:
        await update.message.reply_text(
            "Nenhum plano esta disponivel no momento. Chame o suporte para mais detalhes.",
            reply_markup=main_menu(),
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    if data == "age_gate":
        await answer_callback_text(
            query,
            "Este conteudo e exclusivo para maiores de 18 anos.\n\n"
            "Confirme sua idade para continuar.",
            reply_markup=age_menu(),
        )
    elif data == "plans":
        await show_plans(update, context)
    elif data.startswith("plan:"):
        await select_plan(update, context, int(data.split(":", 1)[1]))
    elif data == "my_plans":
        await show_my_plans(update, context)
    elif data == "support":
        await answer_callback_text(
            query,
            "Suporte\n\n"
            "Chame o administrador ou responda aqui contando o que aconteceu.",
            reply_markup=main_menu(),
        )
    elif data == "menu":
        await answer_callback_text(query, "Menu principal:", reply_markup=main_menu())
    elif data == "exit":
        await answer_callback_text(query, "Tudo bem. Quando quiser voltar, use /start.", reply_markup=main_menu())


async def show_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    with SessionLocal() as db:
        plans = db.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.price.asc())).all()

    if not plans:
        await query.edit_message_text("Nenhum plano esta disponivel no momento.", reply_markup=main_menu())
        return

    lines = ["Escolha seu plano VIP:\n"]
    buttons = []
    for plan in plans:
        lines.append(f"*{plan.name}* - R$ {plan.price:.2f}\n{plan.description}\nDuracao: {plan.duration_days} dias\n")
        buttons.append([InlineKeyboardButton(f"{plan.name} - R$ {plan.price:.2f}", callback_data=f"plan:{plan.id}")])
    buttons.append([InlineKeyboardButton("Ver previa👀", web_app=preview_web_app())])
    buttons.append([InlineKeyboardButton("Voltar", callback_data="exit")])
    await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))


async def select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_id: int) -> None:
    query = update.callback_query
    telegram_user = update.effective_user
    if not query or not telegram_user:
        return

    await query.edit_message_text("Gerando seu PIX. Aguarde alguns segundos...")

    with SessionLocal() as db:
        user = upsert_user(db, telegram_user.id, telegram_user.username, telegram_user.first_name)
        plan = db.get(Plan, plan_id)
        if not plan or not plan.active:
            await query.edit_message_text("Plano indisponivel no momento.", reply_markup=main_menu())
            return

        order = create_order(db, user, plan)
        try:
            charge = get_payment_client().create_pix_charge(
                order_id=order.id,
                amount=order.amount,
                description=f"Assinatura {plan.name}",
                payer_name=telegram_user.full_name,
                payer_telegram_id=telegram_user.id,
            )
        except Exception:
            logger.exception("Failed to create PIX charge for order_id=%s", order.id)
            order.status = OrderStatus.FAILED.value
            db.commit()
            await query.edit_message_text(
                "Nao foi possivel gerar o PIX agora.\n\n"
                "Tente novamente em alguns instantes ou chame o suporte.",
                reply_markup=main_menu(),
            )
            return

        order.payment_id = charge.payment_id
        order.transaction_id = charge.transaction_id
        order.status = OrderStatus.PENDING.value
        order.pix_qr_code_url = charge.qr_code_url
        order.pix_qr_code_base64 = charge.qr_code_base64
        order.pix_copy_paste = charge.copy_paste
        db.commit()

    payment_text = (
        "*PIX gerado com sucesso*\n\n"
        f"Plano: *{plan.name}*\n"
        f"Valor: *R$ {plan.price:.2f}*\n"
        "Status: *Pendente*\n\n"
        f"Pix copia e cola:\n`{charge.copy_paste}`\n\n"
        "Depois do pagamento, o acesso e liberado automaticamente."
    )

    if charge.qr_code_base64:
        await send_base64_qr(context, telegram_user.id, charge.qr_code_base64, payment_text)
    elif charge.qr_code_url:
        await context.bot.send_photo(chat_id=telegram_user.id, photo=charge.qr_code_url, caption=payment_text, parse_mode=ParseMode.MARKDOWN)
    else:
        await context.bot.send_message(chat_id=telegram_user.id, text=payment_text, parse_mode=ParseMode.MARKDOWN)


async def send_base64_qr(context: ContextTypes.DEFAULT_TYPE, chat_id: int, qr_base64: str, caption: str) -> None:
    data = qr_base64.split(",", 1)[-1]
    image_bytes = base64.b64decode(data)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = Path(tmp.name)
    try:
        with tmp_path.open("rb") as photo:
            await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, parse_mode=ParseMode.MARKDOWN)
    finally:
        tmp_path.unlink(missing_ok=True)


async def show_my_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    with SessionLocal() as db:
        db_user = db.scalar(select(User).where(User.telegram_id == user.id))
        if not db_user:
            await query.edit_message_text("Voce ainda nao possui cadastro. Use /start para comecar.", reply_markup=main_menu())
            return
        subscriptions = db.scalars(
            select(Subscription).where(Subscription.user_id == db_user.id).order_by(Subscription.expire_date.desc())
        ).all()

    if not subscriptions:
        await query.edit_message_text("Voce ainda nao possui assinatura ativa.", reply_markup=main_menu())
        return

    lines = ["Sua assinatura:\n"]
    for subscription in subscriptions:
        status = "Ativa" if subscription.active else "Vencida"
        lines.append(
            f"{subscription.plan.name}: {status}\n"
            f"Inicio: {subscription.start_date:%d/%m/%Y}\n"
            f"Vencimento: {subscription.expire_date:%d/%m/%Y}\n"
        )
    await query.edit_message_text("\n".join(lines), reply_markup=main_menu())


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id if update.effective_user else None
        if user_id not in settings.ADMIN_IDS:
            if update.message:
                await update.message.reply_text("Acesso negado.")
            return
        await func(update, context)

    return wrapper


@admin_only
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Painel administrativo:\n"
        "/clientes - listar clientes\n"
        "/pedidos - listar pedidos recentes\n"
        "/assinaturas - listar assinaturas ativas\n"
        "/receita - receita aprovada\n"
        "/planos - listar planos e IDs\n"
        "/addplano Nome | descricao | preco | dias\n"
        "/editarplano ID | Nome | descricao | preco | dias\n"
        "/removerplano ID\n\n"
        "Mensagem inicial:\n"
        "/previewinicio - ver como o cliente recebe\n"
        "/setinicio texto - trocar texto inicial\n"
        "/addmidia - responda uma foto/video com esse comando\n"
        "/midias - listar midias cadastradas\n"
        "/limparmidia - remover todas as midias iniciais"
    )


@admin_only
async def clientes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.created_at.desc()).limit(30)).all()
    text = "Clientes recentes:\n" + "\n".join(f"{u.id} | {u.telegram_id} | @{u.username or '-'} | {u.first_name or '-'}" for u in users)
    await update.message.reply_text(text or "Nenhum cliente encontrado.")


@admin_only
async def pedidos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from models import Order

    with SessionLocal() as db:
        orders = db.scalars(select(Order).order_by(Order.created_at.desc()).limit(30)).all()
    text = "Pedidos recentes:\n" + "\n".join(
        f"#{o.id} | user={o.user.telegram_id} | {o.plan.name} | R$ {o.amount:.2f} | {o.status}" for o in orders
    )
    await update.message.reply_text(text or "Nenhum pedido encontrado.")


@admin_only
async def assinaturas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with SessionLocal() as db:
        subs = db.scalars(select(Subscription).where(Subscription.active.is_(True)).order_by(Subscription.expire_date.asc())).all()
    text = "Assinaturas ativas:\n" + "\n".join(
        f"#{s.id} | user={s.user.telegram_id} | {s.plan.name} | vence {s.expire_date:%d/%m/%Y}" for s in subs
    )
    await update.message.reply_text(text or "Nenhuma assinatura ativa.")


@admin_only
async def receita(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with SessionLocal() as db:
        total = revenue_total(db)
    await update.message.reply_text(f"Receita aprovada: R$ {total:.2f}")


@admin_only
async def planos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with SessionLocal() as db:
        items = db.scalars(select(Plan).order_by(Plan.id.asc())).all()

    if not items:
        await update.message.reply_text("Nenhum plano cadastrado.")
        return

    lines = ["Planos cadastrados:"]
    for plan in items:
        status = "ativo" if plan.active else "inativo"
        lines.append(
            f"ID {plan.id} | {plan.name} | R$ {plan.price:.2f} | {plan.duration_days} dias | {status}\n"
            f"{plan.description}"
        )
    await update.message.reply_text("\n\n".join(lines))


@admin_only
async def previewinicio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_welcome_media(update, context)
    await send_welcome_offer(update, context)


@admin_only
async def setinicio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    raw_text = update.message.text or ""
    command_parts = raw_text.split(maxsplit=1)
    text = command_parts[1].strip() if len(command_parts) > 1 else ""
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text.strip()

    if not text:
        await update.message.reply_text(
            "Uso:\n"
            "/setinicio seu texto aqui\n\n"
            "Dica: para manter o texto bonito, mande a mensagem pronta primeiro e responda ela com /setinicio."
        )
        return

    data = load_welcome_settings()
    data["text"] = text
    save_welcome_settings(data)
    await update.message.reply_text("Mensagem inicial atualizada. Use /previewinicio para conferir.")


@admin_only
async def addmidia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    replied = update.message.reply_to_message
    if not replied or (not replied.photo and not replied.video):
        await update.message.reply_text("Responda uma foto ou video com /addmidia para adicionar na entrada do bot.")
        return

    data = load_welcome_settings()
    media_count = len(data["media"]) + 1

    if replied.video:
        telegram_file = await replied.video.get_file()
        suffix = ".mp4"
    else:
        telegram_file = await replied.photo[-1].get_file()
        suffix = ".jpg"

    path = WELCOME_MEDIA_DIR / f"welcome_admin_{media_count}{suffix}"
    await telegram_file.download_to_drive(custom_path=path)
    data["media"].append(str(path))
    save_welcome_settings(data)
    await update.message.reply_text("Midia adicionada. Use /previewinicio para conferir.")


@admin_only
async def midias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_welcome_settings()
    if not data["media"]:
        await update.message.reply_text("Nenhuma midia personalizada cadastrada.")
        return
    lines = ["Midias cadastradas:"]
    for index, item in enumerate(data["media"], start=1):
        lines.append(f"{index}. {item}")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def limparmidia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_welcome_settings()
    removed = 0
    for item in data["media"]:
        path = Path(item)
        if path.exists() and path.is_file() and WELCOME_MEDIA_DIR.resolve() in path.resolve().parents:
            path.unlink()
            removed += 1
    data["media"] = []
    save_welcome_settings(data)
    await update.message.reply_text(f"Midias removidas: {removed}.")


@admin_only
async def addplano(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args)
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) != 4:
        await update.message.reply_text("Uso: /addplano Nome | descricao | preco | dias")
        return
    name, description, price, days = parts
    with SessionLocal() as db:
        plan = Plan(name=name, description=description, price=Decimal(price.replace(",", ".")), duration_days=int(days), active=True)
        db.add(plan)
        db.commit()
    await update.message.reply_text(f"Plano criado: {name}")


@admin_only
async def editarplano(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args)
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) != 5:
        await update.message.reply_text("Uso: /editarplano ID | Nome | descricao | preco | dias")
        return

    plan_id, name, description, price, days = parts
    with SessionLocal() as db:
        plan = db.get(Plan, int(plan_id))
        if not plan:
            await update.message.reply_text("Plano nao encontrado. Use /planos para ver os IDs.")
            return

        plan.name = name
        plan.description = description
        plan.price = Decimal(price.replace(",", "."))
        plan.duration_days = int(days)
        plan.active = True
        db.commit()

    await update.message.reply_text(f"Plano atualizado: {name}")


@admin_only
async def removerplano(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Uso: /removerplano ID")
        return
    with SessionLocal() as db:
        plan = db.get(Plan, int(context.args[0]))
        if not plan:
            await update.message.reply_text("Plano nao encontrado.")
            return
        plan.active = False
        db.commit()
    await update.message.reply_text(f"Plano removido: {plan.name}")


def build_application() -> Application:
    settings.validate_bot()
    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("clientes", clientes))
    application.add_handler(CommandHandler("pedidos", pedidos))
    application.add_handler(CommandHandler("assinaturas", assinaturas))
    application.add_handler(CommandHandler("receita", receita))
    application.add_handler(CommandHandler("planos", planos))
    application.add_handler(CommandHandler("previewinicio", previewinicio))
    application.add_handler(CommandHandler("setinicio", setinicio))
    application.add_handler(CommandHandler("addmidia", addmidia))
    application.add_handler(CommandHandler("midias", midias))
    application.add_handler(CommandHandler("limparmidia", limparmidia))
    application.add_handler(CommandHandler("addplano", addplano))
    application.add_handler(CommandHandler("editarplano", editarplano))
    application.add_handler(CommandHandler("removerplano", removerplano))
    application.add_handler(CallbackQueryHandler(handle_callback))
    return application


def run_bot() -> None:
    setup_logging()
    init_db()
    with SessionLocal() as db:
        seed_default_plans(db)
    application = build_application()
    logger.info("Starting Telegram bot")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run_bot()
