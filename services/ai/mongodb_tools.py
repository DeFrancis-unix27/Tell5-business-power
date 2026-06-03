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
