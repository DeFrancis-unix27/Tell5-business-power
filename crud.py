from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete as sa_delete
from models import Conversation, Order, Notification, User
from datetime import datetime
from typing import List


async def create_conversation(db: AsyncSession, phone: str, message: str, category: str, user_id: int | None = None, channel: str | None = None):
    conv = Conversation(phone=phone, message=message, category=category, user_id=user_id, channel=channel or "whatsapp")
    db.add(conv)
    await db.flush()
    return conv


async def create_order(db: AsyncSession, phone: str, item: str, quantity: int = 1, customer_name: str | None = None, user_id: int | None = None):
    order = Order(phone=phone, item=item, quantity=quantity, customer_name=customer_name, status="pending", user_id=user_id)
    db.add(order)
    await db.flush()
    return order


async def create_notification(db: AsyncSession, ntype: str, payload: str | None = None):
    n = Notification(notification_type=ntype, payload=payload)
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

async def delete_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    user = await get_user_by_id(db, user_id)
    if user:
        await db.delete(user)
        await db.flush()
    return user

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


async def create_business_profile(
    db: AsyncSession,
    user_id: int,
    business_name: str,
    description: str | None = None,
    category: str | None = None,
    address: str | None = None,
    currency: str = "NGN",
    is_public: bool = False,
) -> "BusinessProfile":
    from models import BusinessProfile
    profile = BusinessProfile(
        user_id=user_id,
        business_name=business_name,
        description=description,
        category=category,
        address=address,
        currency=currency,
        is_public=is_public,
    )
    db.add(profile)
    await db.flush()
    return profile


async def get_business_profile(db: AsyncSession, user_id: int) -> "BusinessProfile | None":
    from models import BusinessProfile
    q = await db.execute(select(BusinessProfile).where(BusinessProfile.user_id == user_id))
    return q.scalar_one_or_none()


async def get_public_business_profiles(db: AsyncSession) -> List["BusinessProfile"]:
    from models import BusinessProfile
    q = await db.execute(
        select(BusinessProfile).where(BusinessProfile.is_public == True)
    )
    return q.scalars().all()


async def create_product(
    db: AsyncSession,
    business_id: int,
    name: str,
    description: str | None = None,
    price: float | None = None,
    currency: str = "NGN",
) -> "Product":
    from models import Product
    product = Product(
        business_id=business_id,
        name=name,
        description=description,
        price=price,
        currency=currency,
    )
    db.add(product)
    await db.flush()
    return product


async def list_products(db: AsyncSession, business_id: int) -> List["Product"]:
    from models import Product
    q = await db.execute(
        select(Product).where(Product.business_id == business_id, Product.is_available == True)
    )
    return q.scalars().all()


async def delete_product(db: AsyncSession, product_id: int) -> bool:
    from models import Product
    q = await db.execute(select(Product).where(Product.id == product_id))
    product = q.scalar_one_or_none()
    if not product:
        return False
    product.is_available = False
    await db.flush()
    return True


async def list_personality_qa(db: AsyncSession) -> List["PersonalityQA"]:
    from models import PersonalityQA
    q = await db.execute(select(PersonalityQA).order_by(PersonalityQA.created_at.desc()))
    return q.scalars().all()


async def add_personality_qa(db: AsyncSession, question: str, answer: str, mode: str = "business") -> "PersonalityQA":
    from models import PersonalityQA
    qa = PersonalityQA(question=question, answer=answer, mode=mode)
    db.add(qa)
    await db.flush()
    return qa


async def delete_personality_qa(db: AsyncSession, qa_id: int) -> bool:
    from models import PersonalityQA
    q = await db.execute(select(PersonalityQA).where(PersonalityQA.id == qa_id))
    qa = q.scalar_one_or_none()
    if not qa:
        return False
    await db.delete(qa)
    await db.flush()
    return True


async def create_pipeline_log(
    db: AsyncSession,
    message: str,
    category: str | None = None,
    gemini_output: str | None = None,
    groq_output: str | None = None,
    mistral_output: str | None = None,
    final_reply: str | None = None,
    errors: str | None = None,
    success: bool = False,
    message_id: str | None = None,
) -> "PipelineLog":
    from models import PipelineLog
    log = PipelineLog(
        message_id=message_id,
        message=message,
        category=category,
        gemini_output=gemini_output,
        groq_output=groq_output,
        mistral_output=mistral_output,
        final_reply=final_reply,
        errors=errors,
        success=success,
    )
    db.add(log)
    await db.flush()
    return log
