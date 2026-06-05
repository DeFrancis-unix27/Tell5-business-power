from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete as sa_delete
from models import Conversation, Order, Notification, User
from datetime import datetime
from typing import List


async def create_conversation(db: AsyncSession, phone: str, message: str, category: str, user_id: int | None = None, channel: str | None = None, ai_response: str | None = None, contact_name: str | None = None, profile_pic_url: str | None = None):
    conv = Conversation(phone=phone, message=message, category=category, user_id=user_id, channel=channel or "whatsapp", ai_response=ai_response, contact_name=contact_name, profile_pic_url=profile_pic_url)
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


async def get_conversation(db: AsyncSession, conv_id: int) -> Conversation | None:
    from sqlalchemy import select
    q = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    return q.scalar_one_or_none()


async def update_conversation_category(db: AsyncSession, conv_id: int, new_category: str) -> bool:
    from sqlalchemy import update
    r = await db.execute(update(Conversation).where(Conversation.id == conv_id).values(category=new_category))
    return r.rowcount > 0


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

async def get_user_profile_pg(db: AsyncSession, user_id: int) -> "UserProfile | None":
    from models import UserProfile
    q = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    return q.scalar_one_or_none()


async def upsert_user_profile_pg(db: AsyncSession, user_id: int, name: str, personality_words: str, distance_setting: str) -> "UserProfile":
    from models import UserProfile
    existing = await get_user_profile_pg(db, user_id)
    if existing:
        existing.name = name
        existing.personality_words = personality_words
        existing.distance_setting = distance_setting
    else:
        existing = UserProfile(
            user_id=user_id,
            name=name,
            personality_words=personality_words,
            distance_setting=distance_setting,
        )
        db.add(existing)
    await db.flush()
    return existing


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
    phone: str | None = None,
    hours: str | None = None,
    website: str | None = None,
    logo_url: str | None = None,
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
        phone=phone,
        hours=hours,
        website=website,
        logo_url=logo_url,
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


async def search_businesses(db: AsyncSession, query: str, limit: int = 5) -> list[dict]:
    from models import BusinessProfile, Product
    from sqlalchemy import or_
    q = await db.execute(
        select(BusinessProfile).where(
            BusinessProfile.is_public == True,
            or_(
                BusinessProfile.business_name.ilike(f"%{query}%"),
                BusinessProfile.description.ilike(f"%{query}%"),
                BusinessProfile.category.ilike(f"%{query}%"),
            )
        ).limit(limit)
    )
    profiles = q.scalars().all()
    result = []
    for p in profiles:
        products = await db.execute(
            select(Product).where(
                Product.business_id == p.id,
                Product.is_available == True
            )
        )
        product_list = products.scalars().all()
        result.append({
            "id": p.id,
            "business_name": p.business_name,
            "description": p.description,
            "category": p.category,
            "address": p.address,
            "phone": p.phone,
            "website": p.website,
            "logo_url": p.logo_url,
            "products": [{"name": pr.name, "price": pr.price, "currency": pr.currency} for pr in product_list[:3]],
        })
    return result


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


async def list_knowledge(db: AsyncSession, user_id: int) -> list:
    from models import KnowledgeEntry
    q = await db.execute(select(KnowledgeEntry).where(KnowledgeEntry.user_id == user_id).order_by(KnowledgeEntry.created_at.desc()))
    return q.scalars().all()


async def add_knowledge(db: AsyncSession, user_id: int, content: str, category: str | None = None) -> "KnowledgeEntry":
    from models import KnowledgeEntry
    entry = KnowledgeEntry(user_id=user_id, content=content, category=category)
    db.add(entry)
    await db.flush()
    return entry


async def delete_knowledge(db: AsyncSession, entry_id: int, user_id: int) -> bool:
    from models import KnowledgeEntry
    q = await db.execute(select(KnowledgeEntry).where(KnowledgeEntry.id == entry_id, KnowledgeEntry.user_id == user_id))
    entry = q.scalar_one_or_none()
    if not entry:
        return False
    await db.delete(entry)
    await db.flush()
    return True
