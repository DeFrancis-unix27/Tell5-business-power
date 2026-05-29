import asyncio
import json
import os
from typing import Any

from google import genai
from google.genai import types

# =========================================================
# Configuration
# =========================================================

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

ALLOWED_CATEGORIES = {
    "order",
    "inquiry",
    "complaint",
    "feedback",
}


# =========================================================
# Gemini Client
# =========================================================

def ai_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def get_client() -> genai.Client:
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# =========================================================
# Prompt Builder
# =========================================================

def build_prompt(message: str) -> str:
    return f"""
You are Tell5, a WhatsApp operations assistant for small businesses.

Classify this customer message and draft a short, friendly WhatsApp reply.

Allowed categories:
- order
- inquiry
- complaint
- feedback

Return ONLY valid JSON in this exact format:

{{
  "category": "order|inquiry|complaint|feedback",
  "reply": "short reply"
}}

Customer message:
{message}
""".strip()


# =========================================================
# Gemini Response
# =========================================================

def _generate_content(prompt: str) -> str | None:
    if not ai_configured():
        return None

    client = get_client()

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=220,
            response_mime_type="application/json",
        ),
    )

    return response.text


# =========================================================
# Validation
# =========================================================

def validate_response(data: dict[str, Any]) -> dict[str, str] | None:
    category = str(data.get("category", "")).lower().strip()
    reply = str(data.get("reply", "")).strip()

    if category not in ALLOWED_CATEGORIES:
        return None

    if not reply:
        return None

    return {
        "category": category,
        "reply": reply[:700],
    }


# =========================================================
# Public Functions
# =========================================================

async def analyze_customer_message(
    message: str,
) -> dict[str, str] | None:
    prompt = build_prompt(message)

    try:
        text = await asyncio.to_thread(
            _generate_content,
            prompt,
        )

        if not text:
            return None

        data = json.loads(text)

        return validate_response(data)

    except Exception:
        return None


async def draft_reply(message: str) -> str | None:
    result = await analyze_customer_message(message)

    if not result:
        return None

    return result["reply"]