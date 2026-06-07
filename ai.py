import asyncio
import json
import logging
import os
from typing import Any, Optional
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

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
    "pending",
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


def ai_categorize_message(text: str) -> str | None:
    if not text.strip():
        return None

    client = get_client()

    prompt = f"""
You are the classifier for Tell5 — a business messaging platform.
Classify the customer's primary intent into exactly ONE category.

Message:
{text}

Categories:
- order: buying, placing, modifying, cancelling, or tracking an order — anything about a purchase or delivery.
- inquiry: asking a question or requesting information about products, prices, availability, business hours, etc.
- complaint: expressing dissatisfaction, reporting a problem, requesting a refund, damaged/wrong items, poor service.
- feedback: appreciation, satisfaction, suggestions, general comments, thanks.
- pending: the message is unclear, too short, or doesn't fit the other categories. Needs human review.

Return JSON only: {{"category": "order"|"inquiry"|"complaint"|"feedback"|"pending"}}
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
        category = str(data.get("category", "")).lower().strip()
        if category not in ALLOWED_CATEGORIES:
            logger.warning("AI returned invalid category '%s' for: %.60s", category, text)
            return None
        return category
    except Exception as e:
        logger.warning("AI categorization failed: %s", e)
        return None


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
    "\nWhatsApp Connection:\n"
    "- Two methods: Twilio (official WhatsApp API, reliable, no phone needed) and Baileys (free, scan QR code, phone must stay online).\n"
    "- Twilio setup: sign up at twilio.com/whatsapp, get Account SID/Auth Token/number, set webhook to /api/twilio/webhook.\n"
    "- Baileys setup: go to Connections page, click Start Baileys Bot, scan QR code from WhatsApp → Linked Devices → Link a Device.\n"
    "- Both can work side by side. Baileys may disconnect on Render free tier after inactivity; reload to reconnect.\n"
    "- Reset Baileys: delete services/whatsapp/auth/ folder and restart.\n"
    "\nAI Pipeline:\n"
    "- Every message is classified (order, inquiry, complaint, feedback, pending), then context is built, a reply is generated, optionally enriched by ADK, and stored.\n"
    "- Toggle AI on/off in Settings. When off, messages are stored for manual reply.\n"
    "- Categories: order (buying/tracking/delivery), inquiry (products/prices/hours), complaint (problems/refunds/returns), feedback (thanks/suggestions), pending (unclear — can be reclassified by clicking Mark as Resolved in conversation modal).\n"
    "- Training: Knowledge Base (business facts, pricing, policies), Personality Q&A (admin Q&A pairs), Onboarding (name, personality words, distance setting).\n"
    "\nFAQ:\n"
    "- All AI providers free tiers (Gemini, Groq, OpenRouter). No charges.\n"
    "- CSV export available on dashboard. Conversations older than 7 days auto-deleted.\n"
    "- Render free tier sleeps after inactivity; first request gets 404, reload fixes it.\n"
    "\nWhen someone asks about Tell5 itself, confidently answer using this knowledge."
)


def format_business_hours(context: Optional[dict] = None) -> str:
    if not context:
        return ""
    hours = context.get("business_hours")
    open_now = context.get("business_open_now")
    if not hours:
        return ""
    if open_now is False:
        msg = context.get("business_hours_message", "We're currently closed.")
        return f"\n\nNOTE: Business is currently CLOSED. Hours: {hours}. Inform the customer and let them know you'll get back to them when open."
    return ""


def format_internal_sellers(context: Optional[dict] = None) -> str:
    """Format internal seller recommendations from pipeline context."""
    if not context:
        return ""
    sellers = context.get("internal_sellers")
    if not sellers:
        return ""
    lines = []
    for s in sellers[:3]:
        prods = "; ".join(f"{p['name']} ({p['currency'] or 'NGN'} {p['price'] or '—'})" for p in s.get("products", []))
        line = f"- {s['business_name']} ({s.get('category', '')}) — {s.get('description', '')[:120]}"
        if prods:
            line += f"\n  Products: {prods}"
        lines.append(line)
    return (
        "\n\n--- Internal sellers on Tell5 matching this request ---\n" +
        "\n".join(lines) +
        "\n\nIMPORTANT: First recommend the best internal seller(s) above (up to 3). "
        "Only suggest external options if none of these fit the request."
    )


def build_prompt(message: str, category: str, context: Optional[dict] = None) -> str:
    extra = format_internal_sellers(context) + format_business_hours(context)

    return f"""
{TELL5_SYSTEM_KNOWLEDGE}

The customer's message has been categorized as: {category}

Message: {message}
{extra}

Write a short, helpful WhatsApp reply that addresses their needs.
If the message is about Tell5 or its founder, answer confidently using the Tell5 knowledge above.
If the message is personal chat unrelated to business, politely steer back to business.

Return JSON:
{{"category": "{category}", "reply": "your reply here"}}
""".strip()


# ==================================================================================================
# Gemini Response
# ==================================================================================================

def _generate_content(prompt: str, model: Optional[str] = None, api_key: Optional[str] = None) -> str | None:
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        return None

    model_name = model or GEMINI_MODEL
    client = genai.Client(api_key=key)

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
        logger.warning("Gemini %s generation failed: %s", model_name, exc)
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
