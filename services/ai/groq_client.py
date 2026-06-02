import json
from typing import Any, Optional
from config import Config


def groq_configured() -> bool:
    return bool(Config.GROQ_API_KEY)


async def groq_classify(text: str, categories: list[str]) -> Optional[str]:
    if not groq_configured():
        return None
    import httpx

    prompt = f"""Classify the intent of this message into exactly one of: {', '.join(categories)}.

Message: {text}

Return JSON only:
{{"category": "<category>"}}"""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {Config.GROQ_API_KEY}",
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
    message: str, category: str, context: Optional[dict[str, Any]] = None
) -> Optional[str]:
    if not groq_configured():
        return None
    import httpx

    context_str = ""
    if context:
        context_str = f"\nContext: {json.dumps(context)}"

    prompt = f"""You are a customer service agent for a WhatsApp business platform.

Category: {category}
Customer message: {message}{context_str}

Write a short, helpful reply. Return JSON only:
{{"reply": "your reply here"}}"""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {Config.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": Config.GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 220,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return str(parsed.get("reply", "")).strip()
    except Exception:
        return None
