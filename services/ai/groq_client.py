import json
from typing import Any, Optional
from config import Config


def groq_configured() -> bool:
    return bool(Config.GROQ_API_KEY)


async def groq_classify(text: str, categories: list[str], api_key: Optional[str] = None) -> Optional[str]:
    key = api_key or Config.GROQ_API_KEY
    if not key:
        return None
    import httpx

    prompt = f"""You are Tell5's AI classifier. Categorize this message into: {', '.join(categories)}.

Message: {text}

Return JSON only:
{{"category": "<category>"}}"""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": Config.GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 50,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return str(parsed.get("category", "")).lower().strip()
    except Exception:
        return None


async def groq_generate_reply(
    message: str, category: str, context: Optional[dict[str, Any]] = None, api_key: Optional[str] = None
) -> Optional[str]:
    key = api_key or Config.GROQ_API_KEY
    if not key:
        return None
    from ai import format_internal_sellers, format_business_hours
    seller_extra = format_internal_sellers(context) + format_business_hours(context)
    import httpx

    context_str = f"\nBusiness context: {json.dumps(context)}" if context else ""

    prompt = f"""You are a friendly WhatsApp business assistant.
You help customers with products, orders, and inquiries.
Be warm, natural, and conversational — like a helpful friend who knows the business.

Category: {category}
Customer message: {message}{context_str}{seller_extra}

Write a natural WhatsApp reply. Be human. Recommend products when it fits.
Keep it friendly and conversational. Only talk about Tell5 if the customer asks.
Return JSON only:
{{"reply": "your reply here"}}"""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": Config.GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 300,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return str(parsed.get("reply", "")).strip()
    except Exception:
        return None
