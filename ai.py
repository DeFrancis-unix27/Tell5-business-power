import asyncio
import json
import logging
from typing import Any, Optional

from config import Config

logger = logging.getLogger(__name__)

_genai = None
_types = None

def _get_genai():
    global _genai
    if _genai is None:
        from google import genai as _g
        _genai = _g
    return _genai

def _get_types():
    global _types
    if _types is None:
        from google.genai import types as _t
        _types = _t
    return _types

# ==================================================================================================
# Configuration
# ==================================================================================================

GEMINI_MODEL = Config.GEMINI_MODEL
GEMINI_FALLBACK_MODEL = Config.GEMINI_FALLBACK_MODEL

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
    return bool(Config.GEMINI_API_KEY)


def get_client():
    return _get_genai().Client(api_key=Config.GEMINI_API_KEY)





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
            config=_get_types().GenerateContentConfig(
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
    "You are a warm, human-like AI sales assistant on WhatsApp.\n\n"
    "--- YOUR VOICE ---\n"
    "- Represent the business, not Tell5. Introduce yourself as from the business.\n"
    "- Warm, natural, human. Like chatting with a helpful friend who knows the business.\n"
    "- Short sentences. Ask questions. Show genuine interest.\n"
    "- No robot speak. No corporate jargon. Be yourself.\n"
    "- Adapt to the customer's mood — casual with greetings, helpful with inquiries.\n\n"
    "--- ABOUT TELL5 (the platform) ---\n"
    "Do NOT mention Tell5 unless the customer asks. Focus on the business you represent.\n"
    "If asked: Tell5 is a WhatsApp business platform. Founder: Francis David from Nnewi, Nigeria.\n"
    "Help page: https://tell5-business-power.onrender.com/help\n\n"
    "--- CONVERSATION CONTINUITY ---\n"
    "Below is recent conversation history. Use it to pick up where you left off, "
    "avoid repeats, and show you remember them. Never say \"as we discussed\" — just naturally include it.\n\n"
    "--- CUSTOMER TRACKING ---\n"
    "Build a mental profile: name, preferences, past interests, mood. "
    "Personalise every reply. Make each customer feel like a valued regular.\n"
)


def format_business_hours(context: Optional[dict] = None) -> str:
    if not context:
        return ""
    hours = context.get("business_hours")
    open_now = context.get("business_open_now")
    if not hours:
        return ""
    if open_now is False:
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

    # Build business context
    biz_context = ""
    biz_name = context.get("business_name", "") if context else ""
    owner_name = context.get("owner_name", "") if context else ""
    services = context.get("services", "") if context else ""
    price_range = context.get("price_range", "") if context else ""
    words = context.get("personality_words", "") if context else ""
    distance = context.get("distance_setting", "") if context else ""

    if biz_name and owner_name:
        biz_context += f"You are the AI sales assistant for {biz_name}, owned by {owner_name}."
    elif biz_name:
        biz_context += f"You are the AI sales assistant for {biz_name}."
    elif owner_name:
        biz_context += f"You are representing {owner_name}'s business."
    else:
        biz_context += "Note: No business profile is set up yet. Gently encourage them to complete their business setup."

    if services:
        biz_context += f"\n{owner_name or 'The owner'} offers these services: {services}"
    if price_range:
        biz_context += f"\nPrice range: {price_range}"
    if words:
        biz_context += f"\nPersonality: {words}"
    if distance:
        biz_context += f"\nService area: {distance}"

    if biz_name:
        biz_context += (
            "\n\nYOUR JOB:"
            f"\n1. Represent {biz_name} and {owner_name or 'the owner'} professionally"
            "\n2. Do NOT pitch Tell5 unless asked"
            f"\n3. Introduce yourself as from {biz_name}"
            "\n\nCONVERSATION FLOW:"
            "\n- Start by greeting the customer warmly"
            "\n- Ask what they need help with"
            "\n- If they want a service, ask follow-up questions to understand their specific needs"
            "\n- Give recommendations based on their answers"
            "\n- Guide the conversation step by step, don't dump all info at once"
            "\n- When you have enough info, give a price estimate and timeline"
            "\n- Offer to check with the owner and get back to them"
            "\n- Keep the tone warm, human, and conversational"
            "\n- Remember what the customer said earlier in the conversation"
            "\n\nEXAMPLE FLOW:"
            "\nCustomer: 'I want a website'"
            "\nYou: 'Nice! What kind of website are you thinking? An online store, a business site, or a personal portfolio?'"
            "\nCustomer: 'Business site'"
            "\nYou: 'Got it. What features should it have? Contact form, gallery, booking system?'"
            "\nCustomer: 'Contact form and gallery'"
            "\nYou: 'Perfect. I can recommend a 5-page business website with a gallery and contact form. That usually goes for around [PRICE_RANGE]. When would you like it ready?'"
            "\nCustomer: 'In 2 weeks'"
            "\nYou: 'Let me confirm with [OWNER_NAME] and get back to you with a full quote. Give me a bit!'"
        )

    kb = context.get("business_knowledge", []) if context else []
    if kb:
        biz_context += "\n\n--- Business Knowledge Base ---\n"
        for e in kb:
            biz_context += f"- {e['content']}\n"

    # Recent conversation history from MongoDB
    history = ""
    if context:
        mongo = context.get("mongodb", {})
        convos = mongo.get("mongo_conversations", [])
        if convos:
            history += "\n\n--- Recent Conversation History ---\n"
            for c in reversed(convos):
                ts = c.get("timestamp", "")[:16] if c.get("timestamp") else ""
                msg = c.get("message", "")
                reply = c.get("reply", "")
                if msg:
                    history += f"  Customer ({ts}): {msg}\n"
                if reply:
                    history += f"  You ({ts}): {reply}\n"

    return f"""
{TELL5_SYSTEM_KNOWLEDGE}

{biz_context}
{history}

The customer's message category: {category}

Message: {message}
{extra}

Write a natural WhatsApp reply. Be conversational and human.
Recommend products or services when it fits naturally.
If the conversation is casual, that's fine — engage naturally.

Return JSON:
{{"category": "{category}", "reply": "your reply here"}}
""".strip()


# ==================================================================================================
# Gemini Response
# ==================================================================================================

def _generate_content(prompt: str, model: Optional[str] = None, api_key: Optional[str] = None) -> str | None:
    key = api_key or Config.GEMINI_API_KEY
    if not key:
        return None

    model_name = model or GEMINI_MODEL
    client = _get_genai().Client(api_key=key)

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=_get_types().GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=300,
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
        config=_get_types().GenerateContentConfig(
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
