import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_mongo_provider = None


def set_mongo_provider(provider):
    global _mongo_provider
    _mongo_provider = provider


def get_mongo_provider():
    return _mongo_provider


async def store_conversation(
    db_name: str,
    from_number: str,
    message: str,
    reply: str,
    category: str,
    user_id: Optional[int] = None,
) -> str:
    p = _mongo_provider
    if not p or not p.is_ready:
        return ""
    doc = {
        "from_number": from_number,
        "user_id": user_id,
        "message": message,
        "reply": reply,
        "category": category,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return await p.insert_one("conversations", doc)


async def get_user_conversations(
    db_name: str,
    from_number: str,
    limit: int = 5,
) -> list[dict]:
    p = _mongo_provider
    if not p or not p.is_ready:
        return []
    return await p.find_documents(
        "conversations",
        filter={"from_number": from_number},
        sort=[("timestamp", -1)],
        limit=limit,
    )


async def store_user_profile(
    db_name: str,
    user_id: int,
    name: str,
    personality_words: str,
    distance_setting: str,
) -> bool:
    p = _mongo_provider
    if not p or not p.is_ready:
        return False
    doc = {
        "user_id": user_id,
        "name": name,
        "personality_words": personality_words,
        "distance_setting": distance_setting,
        "onboarding_complete": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    modified = await p.update_one("user_profiles", {"user_id": user_id}, {"$set": doc})
    if modified == 0:
        doc["created_at"] = datetime.now(timezone.utc).isoformat()
        await p.insert_one("user_profiles", doc)
    return True


async def get_user_profile(db_name: str, user_id: int) -> dict | None:
    p = _mongo_provider
    if not p or not p.is_ready:
        return None
    docs = await p.find_documents("user_profiles", filter={"user_id": user_id}, limit=1)
    return docs[0] if docs else None


async def store_api_key(
    db_name: str,
    user_id: int,
    provider: str,
    api_key: str,
) -> bool:
    p = _mongo_provider
    if not p or not p.is_ready:
        return False
    doc = {
        "user_id": user_id,
        "provider": provider.lower(),
        "api_key": api_key,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    modified = await p.update_one("api_keys", {"user_id": user_id, "provider": provider.lower()}, {"$set": doc})
    if modified == 0:
        doc["created_at"] = datetime.now(timezone.utc).isoformat()
        await p.insert_one("api_keys", doc)
    return True


async def get_api_key(db_name: str, user_id: int, provider: str) -> str | None:
    p = _mongo_provider
    if not p or not p.is_ready:
        return None
    docs = await p.find_documents("api_keys", filter={"user_id": user_id, "provider": provider.lower()}, limit=1)
    return docs[0].get("api_key") if docs else None


async def list_api_keys(db_name: str, user_id: int) -> list[dict]:
    p = _mongo_provider
    if not p or not p.is_ready:
        return []
    docs = await p.find_documents("api_keys", filter={"user_id": user_id})
    return [{"provider": d["provider"], "updated_at": d.get("updated_at")} for d in docs]


async def delete_api_key(db_name: str, user_id: int, provider: str) -> bool:
    p = _mongo_provider
    if not p or not p.is_ready:
        return False
    n = await p.delete_one("api_keys", {"user_id": user_id, "provider": provider.lower()})
    return n > 0


async def build_mongo_context(
    db_name: str,
    from_number: str,
    user_id: Optional[int] = None,
) -> dict:
    ctx = {}
    p = _mongo_provider
    if p and p.is_ready:
        recent = await get_user_conversations(db_name, from_number, limit=3)
        if recent:
            ctx["mongo_conversations"] = [
                {
                    "message": c.get("message", ""),
                    "reply": c.get("reply", ""),
                    "category": c.get("category", ""),
                    "timestamp": c.get("timestamp", ""),
                }
                for c in recent
            ]
            logger.info("Built MongoDB context: %d recent conversations", len(recent))
    return ctx
