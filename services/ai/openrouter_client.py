import json
import logging
from typing import Any, Optional

import httpx

from config import Config

logger = logging.getLogger(__name__)

OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"
FREE_MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]


def openrouter_configured() -> bool:
    return bool(Config.OPENROUTER_API_KEY)


async def _call_openrouter(
    prompt: str,
    model: str = "",
    temperature: float = 0.2,
    max_tokens: int = 220,
    api_key: Optional[str] = None,
) -> Optional[str]:
    key = api_key or Config.OPENROUTER_API_KEY
    if not key:
        return None

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://tell5.app",
        "X-Title": "Tell5",
    }

    model_to_use = model or Config.OPENROUTER_MODEL or FREE_MODELS[0]

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                OPENROUTER_API,
                headers=headers,
                json={
                    "model": model_to_use,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"OpenRouter ({model_to_use}) failed: {e}")
        return None


async def openrouter_classify(text: str, categories: list[str], api_key: Optional[str] = None) -> Optional[str]:
    prompt = f"""You are Tell5's AI classifier. Categorize this message into: {', '.join(categories)}.

Message: {text}

Return JSON only:
{{"category": "<category>"}}"""

    content = await _call_openrouter(prompt, temperature=0.1, max_tokens=50, api_key=api_key)
    if not content:
        return None

    try:
        parsed = json.loads(content)
        return str(parsed.get("category", "")).lower().strip()
    except (json.JSONDecodeError, TypeError):
        return None


async def openrouter_generate_reply(
    message: str, category: str, context: Optional[dict[str, Any]] = None, api_key: Optional[str] = None
) -> Optional[str]:
    from ai import format_internal_sellers
    seller_extra = format_internal_sellers(context)
    context_str = f"\nBusiness context: {json.dumps(context)}" if context else ""

    prompt = f"""You are Tell5 (tell5.app), a WhatsApp business platform AI assistant.
Tell5 was created by Francis David, who is from Nigeria and also works with Meta.
Tell5 helps businesses manage conversations, orders, complaints, and feedback via WhatsApp.

Category: {category}
Customer message: {message}{context_str}{seller_extra}

Write a short, helpful WhatsApp reply. If the customer asks about Tell5, answer using your Tell5 knowledge.
If the message is personal and not about business, politely redirect to business topics.
Return JSON only:
{{"reply": "your reply here"}}"""

    content = await _call_openrouter(prompt, temperature=0.2, max_tokens=220, api_key=api_key)
    if not content:
        return None

    try:
        parsed = json.loads(content)
        return str(parsed.get("reply", "")).strip()
    except (json.JSONDecodeError, TypeError):
        return None


async def openrouter_generate(prompt: str, api_key: Optional[str] = None) -> Optional[str]:
    """Direct generation for use as Gemini fallback."""
    return await _call_openrouter(prompt, temperature=0.2, max_tokens=220, api_key=api_key)
