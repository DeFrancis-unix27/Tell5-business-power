import logging
from typing import Optional

logger = logging.getLogger(__name__)

_qa_cache: list[dict] | None = None

BUSINESS_KEYWORDS = [
    "order", "buy", "price", "product", "service", "business", "shop",
    "delivery", "pay", "payment", "refund", "return", "stock",
    "catalog", "menu", "offer", "discount", "transaction",
    "complaint", "complain", "complaints", "feedback", "review",
    "support", "help", "problem", "issue", "damage", "wrong",
    "want", "need", "looking for", "interested", "quote",
    "available", "how much", "cost", "price list", "brochure",
    "appointment", "booking", "reservation", "hours", "location",
    "contact", "phone", "address", "open", "close",
]

TELL5_KEYWORDS = [
    "tell5", "tell 5", "what can you do", "recommend", "suggestion",
    "what is tell5", "how does tell5 work", "tell5 features",
    "what do you offer", "capabilities", "help me",
    "who created tell5", "who made tell5", "tell5 founder",
    "francis", "francis david", "tell5 owner",
    "tell5 pricing", "tell5 plan", "tell5 platform",
]

PERSONAL_KEYWORDS = [
    "how are you", "who are you", "what is your name", "your name",
    "hello", "hi", "hey", "good morning", "good evening",
    "how's it going", "what's up", "how do you do",
]


async def load_qa_cache(db_session):
    global _qa_cache
    from crud import list_personality_qa
    qa_list = await list_personality_qa(db_session)
    _qa_cache = [
        {"id": q.id, "question": q.question.lower(), "answer": q.answer, "mode": q.mode}
        for q in qa_list
    ]
    logger.info("Loaded %d personality Q&A pairs", len(_qa_cache))


def _simple_match(message: str, question: str) -> bool:
    msg = message.lower().strip().rstrip("?.!")
    q = question.lower().strip().rstrip("?.!")
    return msg == q or msg.startswith(q) or q in msg


def match_qa(message: str) -> Optional[dict]:
    if not _qa_cache:
        return None
    for qa in _qa_cache:
        if _simple_match(message, qa["question"]):
            return qa
    return None


def detect_mode(message: str) -> str:
    msg = message.lower()
    biz_score = sum(1 for kw in BUSINESS_KEYWORDS if kw in msg)
    tell5_score = sum(1 for kw in TELL5_KEYWORDS if kw in msg)
    per_score = sum(1 for kw in PERSONAL_KEYWORDS if kw in msg)
    if biz_score > per_score or tell5_score > 0:
        return "business"
    elif per_score > biz_score:
        return "personal"
    biz_exact = any(kw in msg.split() for kw in ["order", "buy", "price", "pay"])
    if biz_exact:
        return "business"
    return "unknown"


def should_block_message(message: str) -> bool:
    """Block only clearly non-business personal chat."""
    msg = message.lower().strip()
    pure_personal = [
        "i am", "i'm", "i feel", "i think", "my name is",
    ]
    return any(msg.startswith(p) for p in pure_personal) and not any(kw in msg for kw in BUSINESS_KEYWORDS + TELL5_KEYWORDS)
