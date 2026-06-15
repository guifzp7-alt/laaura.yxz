from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Order, OrderStatus, Plan, Subscription, User, utcnow


DEFAULT_PLANS = [
    {
        "name": "VIP Mensal",
        "description": "Acesso VIP por 30 dias aos conteúdos privados.",
        "price": Decimal("29.90"),
        "duration_days": 30,
    },
    {
        "name": "VIP Trimestral",
        "description": "Acesso VIP por 90 dias com melhor custo-benefício.",
        "price": Decimal("79.90"),
        "duration_days": 90,
    },
    {
        "name": "VIP Anual",
        "description": "Acesso VIP por 365 dias com preço promocional.",
        "price": Decimal("249.90"),
        "duration_days": 365,
    },
]


def seed_default_plans(db: Session) -> None:
    if db.scalar(select(func.count(Plan.id))) > 0:
        return
    for plan_data in DEFAULT_PLANS:
        db.add(Plan(**plan_data))
    db.commit()


def upsert_user(db: Session, telegram_id: int, username: str | None, first_name: str | None) -> User:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(telegram_id=telegram_id, username=username, first_name=first_name)
        db.add(user)
    else:
        user.username = username
        user.first_name = first_name
    db.commit()
    db.refresh(user)
    return user


def create_order(db: Session, user: User, plan: Plan) -> Order:
    order = Order(user_id=user.id, plan_id=plan.id, amount=plan.price, status=OrderStatus.PENDING.value)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def activate_subscription(db: Session, order: Order) -> Subscription:
    now = utcnow()
    for current in db.scalars(
        select(Subscription).where(Subscription.user_id == order.user_id, Subscription.active.is_(True))
    ):
        current.active = False

    subscription = Subscription(
        user_id=order.user_id,
        plan_id=order.plan_id,
        order_id=order.id,
        start_date=now,
        expire_date=now + timedelta(days=order.plan.duration_days),
        active=True,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def revenue_total(db: Session) -> Decimal:
    total = db.scalar(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == OrderStatus.PAID.value))
    return Decimal(str(total))
