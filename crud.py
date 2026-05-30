from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from models import Conversation, Order, Notification, User
from datetime import datetime
from typing import List


async def create_conversation(db: AsyncSession, phone: str, message: str, category: str, user_id: int | None = None):
    conv = Conversation(phone=phone, message=message, category=category, user_id=user_id)
    db.add(conv)
    await db.flush()
    return conv


async def create_order(db: AsyncSession, phone: str, item: str, quantity: int = 1, customer_name: str | None = None, user_id: int | None = None):
    order = Order(phone=phone, item=item, quantity=quantity, customer_name=customer_name, status="pending", user_id=user_id)
    db.add(order)
    await db.flush()
    return order


async def create_notification(db: AsyncSession, ntype: str, payload: str | None = None):
    n = Notification(type=ntype, payload=payload)
    db.add(n)
    await db.flush()
    return n


async def list_conversations(db: AsyncSession, user_id: int | None = None) -> List[Conversation]:
    stmt = select(Conversation).order_by(Conversation.timestamp.desc())
    if user_id is not None:
        stmt = stmt.where(Conversation.user_id == user_id)
    q = await db.execute(stmt)
    return q.scalars().all()


async def list_orders(db: AsyncSession, user_id: int | None = None) -> List[Order]:
    stmt = select(Order).order_by(Order.timestamp.desc())
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    q = await db.execute(stmt)
    return q.scalars().all()


async def stats(db: AsyncSession, user_id: int | None = None):
    stmt = select(Conversation.category, func.count(Conversation.id)).group_by(Conversation.category)
    if user_id is not None:
        stmt = stmt.where(Conversation.user_id == user_id)
    q = await db.execute(stmt)
    categories = {row[0]: row[1] for row in q.all()}

    if user_id is not None:
        q2 = await db.execute(select(func.count(Order.id)).where(Order.user_id == user_id))
    else:
        q2 = await db.execute(select(func.count(Order.id)))
    total_orders = q2.scalar() or 0
    return {"categories": categories, "total_orders": total_orders}


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    q = await db.execute(select(User).where(User.email == email.lower()))
    return q.scalar_one_or_none()


async def get_user_by_phone(db: AsyncSession, phone: str) -> User | None:
    normalized = phone.replace("whatsapp:", "").replace(" ", "").strip()
    q = await db.execute(select(User).where(User.phone.in_([phone, normalized])))
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
