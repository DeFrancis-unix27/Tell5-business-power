import json
import logging
from typing import Any, Optional

import httpx

from config import Config

logger = logging.getLogger(__name__)

OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"
FREE_MODELS = [
    "meta-llama/llama-3.1-405b-instruct",
    "mistralai/mistral-large",
    "google/gemini-2.0-flash-exp:free",
]


def openrouter_configured() -> bool:
    return bool(Config.OPENROUTER_API_KEY)


async def _call_openrouter(
    prompt: str,
    model: str = "",
    temperature: float = 0.2,
    max_tokens: int = 220,
) -> Optional[str]:
    if not openrouter_configured():
        return None

    headers = {
        "Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
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


async def openrouter_classify(text: str, categories: list[str]) -> Optional[str]:
    prompt = f"""Classify the intent of this message into exactly one of: {', '.join(categories)}.

Message: {text}

Return JSON only:
{{"category": "<category>"}}"""

    content = await _call_openrouter(prompt, temperature=0.1, max_tokens=50)
    if not content:
        return None

    try:
        parsed = json.loads(content)
        return str(parsed.get("category", "")).lower().strip()
    except (json.JSONDecodeError, TypeError):
        return None


async def openrouter_generate_reply(
    message: str, category: str, context: Optional[dict[str, Any]] = None
) -> Optional[str]:
    context_str = ""
    if context:
        context_str = f"\nContext: {json.dumps(context)}"

    prompt = f"""You are a customer service agent for a WhatsApp business platform.

Category: {category}
Customer message: {message}{context_str}

Write a short, helpful reply. Return JSON only:
{{"reply": "your reply here"}}"""

    content = await _call_openrouter(prompt, temperature=0.2, max_tokens=220)
    if not content:
        return None

    try:
        parsed = json.loads(content)
        return str(parsed.get("reply", "")).strip()
    except (json.JSONDecodeError, TypeError):
        return None


async def openrouter_generate(prompt: str) -> Optional[str]:
    """Direct generation for use as Gemini fallback."""
    return await _call_openrouter(prompt, temperature=0.2, max_tokens=220)
