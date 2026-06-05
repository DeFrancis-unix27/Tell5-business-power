import asyncio
import json
import os
from typing import Any, Optional
from google import genai
from google.genai import types

# ==================================================================================================
# Configuration
# ==================================================================================================

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")

ALLOWED_CATEGORIES = {
    "order",
    "inquiry",
    "complaint",
    "feedback",
}


# ==================================================================================================
# Gemini Client
# ==================================================================================================

def ai_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def get_client() -> genai.Client:
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))





# ==================================================================================================
# Ai Cartegorising
# ==================================================================================================


def ai_categorize_message(text: str) -> str:
    if not text.strip():
        return "inquiry"

    client = get_client()

    prompt = f"""
You are the classifier for Tell5 — a business messaging platform.
Classify the customer's primary intent into exactly one category.

Message:
{text}

Categories:
- order
- inquiry
- complaint
- feedback

Definitions:
order: buying, placing, modifying, cancelling, or tracking an order.
inquiry: asking a question or requesting information.
complaint: expressing dissatisfaction, reporting a problem, requesting a refund.
feedback: appreciation, satisfaction, suggestions, general comments.

Return JSON only: {{"category": "order|inquiry|complaint|feedback"}}
""".strip()

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=50,
                response_mime_type="application/json",
            ),
        )

        data = json.loads(response.text)

        category = str(
            data.get("category", "inquiry")
        ).lower().strip()

        if category not in ALLOWED_CATEGORIES:
            return "inquiry"

        return category

    except Exception:
        return "inquiry"


# ==================================================================================================
# Prompt Builder
# ==================================================================================================
TELL5_SYSTEM_KNOWLEDGE = (
    "You are the AI assistant for Tell5 (tell5.app), a WhatsApp business platform. "
    "Tell5 helps businesses manage customer conversations, orders, complaints, and feedback via WhatsApp. "
    "Key facts about Tell5:\n"
    "- Founder: Francis David. He is from Nigeria and also works with Meta on AI and messaging technologies.\n"
    "- Website: https://tell5-business-power.onrender.com\n"
    "- Features: Business profiles, WhatsApp ordering, AI-powered replies, customer management, CSV export.\n"
    "- Tell5 helps small businesses in Africa and beyond manage their entire customer communication.\n"
    "When someone asks about Tell5 itself, confidently answer using this knowledge."
)


def build_prompt(message: str, category: str) -> str:
    return f"""
{TELL5_SYSTEM_KNOWLEDGE}

The customer's message has been categorized as: {category}

Message: {message}

Write a short, helpful WhatsApp reply that addresses their needs.
If the message is about Tell5 or its founder, answer confidently using the Tell5 knowledge above.
If the message is personal chat unrelated to business, politely steer back to business.

Return JSON:
{{"category": "{category}", "reply": "your reply here"}}
""".strip()


# ==================================================================================================
# Gemini Response
# ==================================================================================================

def _generate_content(prompt: str, model: Optional[str] = None) -> str | None:
    if not ai_configured():
        return None

    model_name = model or GEMINI_MODEL
    client = get_client()

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=220,
                response_mime_type="application/json",
            ),
        )
        return response.text
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"Gemini {model_name} generation failed: {exc}")
        return None

def confidence_check(data:dict[str, Any]) -> str | None :
    category = str(data.get("category","")).lower().strip()
    reply = str(data.get("reply","")).strip()
    
    prompt = f"""
    Review the reply below.

    Category:
    {category}

    Reply:
    {reply}

    Tasks:
    1. Determine whether the reply matches the category naturally.
    2. Score confidence from 1-10.
    3. If confidence < 8, improve the reply and score again.
    4. Retry at most 2 times.

    Rules:
    - If final confidence >= 8:
    Return ONLY the approved reply.
    - If final confidence < 8:
    Return EXACTLY:
    We will get back to you soon.
    - Never explain your reasoning.
    - Never output confidence scores.
    """.strip()
    
    client = get_client()
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=220,
            response_mime_type="text/plain",
        ),
    )
    return response.text
    

# ==================================================================================================
# Validation
# ==================================================================================================

def validate_response(data: dict[str, Any]) -> dict[str, str] | None:
    category = str(data.get("category", "")).lower().strip()
    reply = str(data.get("reply", "")).strip()

    if category not in ALLOWED_CATEGORIES:
        return None

    if not reply:
        return None

    return {
        "category": category,
        "reply": reply[:200],
    }


# ==================================================================================================
# Public Functions
# ==================================================================================================

async def analyze_customer_message(
    message: str,
) -> dict[str, str] | None:
    
    category = await asyncio.to_thread(
        ai_categorize_message,
        message
    )
    
    prompt = build_prompt(message, category)

    try:
        text = await asyncio.to_thread(
            _generate_content,
            prompt,
        )

        if not text:
            return None

        data = json.loads(text)
        initial_validate = validate_response(data)
        
        if not initial_validate:
            return None
        review = await asyncio.to_thread(
            confidence_check,
            initial_validate
        )
        
        if not review:
            return None
        
        initial_validate["reply"] = review.strip()
        
        return initial_validate

    except Exception:
        return None


async def draft_reply(message: str) -> str | None:
    result = await analyze_customer_message(message)

    if not result:
        return None

    return result["reply"]
