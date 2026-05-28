from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from models import Conversation, Order, Notification, User
from datetime import datetime
from typing import List


async def create_conversation(db: AsyncSession, phone: str, message: str, category: str):
    conv = Conversation(phone=phone, message=message, category=category)
    db.add(conv)
    await db.flush()
    return conv


async def create_order(db: AsyncSession, phone: str, item: str, quantity: int = 1, customer_name: str | None = None):
    order = Order(phone=phone, item=item, quantity=quantity, customer_name=customer_name, status="pending")
    db.add(order)
    await db.flush()
    return order


async def create_notification(db: AsyncSession, ntype: str, payload: str | None = None):
    n = Notification(type=ntype, payload=payload)
    db.add(n)
    await db.flush()
    return n


async def list_conversations(db: AsyncSession) -> List[Conversation]:
    q = await db.execute(select(Conversation).order_by(Conversation.timestamp.desc()))
    return q.scalars().all()


async def list_orders(db: AsyncSession) -> List[Order]:
    q = await db.execute(select(Order).order_by(Order.timestamp.desc()))
    return q.scalars().all()


async def stats(db: AsyncSession):
    q = await db.execute(select(Conversation.category, func.count(Conversation.id)).group_by(Conversation.category))
    categories = {row[0]: row[1] for row in q.all()}
    q2 = await db.execute(select(func.count(Order.id)))
    total_orders = q2.scalar() or 0
    return {"categories": categories, "total_orders": total_orders}


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    q = await db.execute(select(User).where(User.email == email.lower()))
    return q.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    q = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    return q.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    email: str,
    first_name: str,
    last_name: str,
    phone: str,
    password_hash: str,
    is_admin: bool = False,
) -> User:
    user = User(
        email=email.lower(),
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        password_hash=password_hash,
        is_admin=is_admin,
    )
    db.add(user)
    await db.flush()
    return user


async def count_users(db: AsyncSession) -> int:
    q = await db.execute(select(func.count(User.id)))
    return q.scalar() or 0


async def list_users(db: AsyncSession) -> List[User]:
    q = await db.execute(select(User).order_by(User.created_at.desc()))
    return q.scalars().all()
