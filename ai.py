import asyncio
import json
import os
from typing import Any

import requests

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")


def ai_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts") or []
    return "\n".join(str(part.get("text", "")) for part in parts).strip()


def _call_gemini(prompt: str) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    url = GEMINI_API_URL.format(model=os.getenv("GEMINI_MODEL", GEMINI_MODEL))
    response = requests.post(
        url,
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 220,
                "responseMimeType": "application/json",
            },
        },
        timeout=12,
    )
    response.raise_for_status()
    return _extract_text(response.json())


async def analyze_customer_message(message: str) -> dict[str, str] | None:
    prompt = f"""
You are Tell5, a WhatsApp operations assistant for small businesses.
Classify this customer message and draft a short, friendly WhatsApp reply.

Allowed categories: order, inquiry, complaint, feedback.
Return only JSON in this shape:
{{"category":"order|inquiry|complaint|feedback","reply":"short reply"}}

Customer message:
{message}
""".strip()

    try:
        text = await asyncio.to_thread(_call_gemini, prompt)
        if not text:
            return None
        data = json.loads(text)
        category = str(data.get("category", "")).lower()
        reply = str(data.get("reply", "")).strip()
        if category not in {"order", "inquiry", "complaint", "feedback"} or not reply:
            return None
        return {"category": category, "reply": reply[:700]}
    except Exception:
        return None


async def draft_reply(message: str) -> str | None:
    result = await analyze_customer_message(message)
    return result["reply"] if result else None
