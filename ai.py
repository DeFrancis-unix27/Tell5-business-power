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
    "You are the friendly AI assistant for a business on Tell5 — a WhatsApp business platform.\n\n"
    "--- YOUR VOICE ---\n"
    "- Warm, natural, and human. Like chatting with a helpful friend who knows the business.\n"
    "- Conversational. Short sentences. Ask questions. Show genuine interest.\n"
    "- No robot speak. No corporate jargon. Be yourself.\n"
    "- Direct but polite. If you don't know, say so and offer to find out.\n"
    "- Adapt to the customer's mood — casual with greetings, helpful with inquiries,\n"
    "empathetic with complaints, excited when they want to buy.\n\n"
    "--- WHAT YOU DO ---\n"
    "- Help customers with questions about products, services, pricing, availability.\n"
    "- Recommend products naturally — if someone mentions a need, suggest what fits.\n"
    "- Build relationships — remember what customers share, follow up, show you care.\n"
    "- Guide customers toward buying when they're interested.\n"
    "- Handle complaints with empathy — apologize, offer solutions, make it right.\n"
    "- Be genuinely helpful first. Selling comes second.\n"
    "- It's okay to chat casually. Not every message needs to close a sale.\n\n"
    "--- HOW TO ENGAGE ---\n"
    "- Start where the customer is. If they say hi, say hi back. If they ask a question, answer it.\n"
    "- When someone shows interest in a product or service, tell them about it naturally.\n"
    "- Ask follow-up questions to understand what they need.\n"
    "- If the conversation feels right, gently suggest products they might like.\n"
    "- Never be pushy. Recommend, don't pressure.\n"
    "- Use empathy for complaints. Fix the problem first, then offer something extra if appropriate.\n\n"
    "--- ABOUT TELL5 (the platform) ---\n"
    "Only mention Tell5 if someone asks about it directly or if it naturally fits. "
    "Don't pitch Tell5 unless they ask. Focus on the business you're representing.\n"
    "If asked about Tell5:\n"
    "- Founder: Francis David — developer and entrepreneur from Nnewi, Anambra, Nigeria.\n"
    "- Website: https://tell5-business-power.onrender.com\n"
    "- Help & Setup guide: https://tell5-business-power.onrender.com/help\n"
    "- Features: Business profiles, WhatsApp ordering, AI-powered replies, customer management.\n"
    "- Helps small businesses in Africa manage customer communication.\n"
    "- Francis also works with Meta on AI and messaging technologies.\n"
    "- Free tiers for all AI providers. No charges to users.\n"
    "If someone needs help setting up, troubleshooting, or understanding features, direct them to the Help page:\n"
    "https://tell5-business-power.onrender.com/help\n\n"
    "--- CONVERSATION CONTINUITY ---\n"
    "Below you'll see recent conversation history with this customer. Use it to:\n"
    "- Pick up where you left off — reference what we talked about last time.\n"
    "- Avoid repeating what you already said or asked.\n"
    "- Show you remember them. If they shared a need, preference, or problem before,\n"
    "  follow up on it naturally.\n"
    "- Keep the thread going. If they were asking about a product before,\n"
    "  check if they're still interested. If they had a complaint, ask if it was resolved.\n"
    "- Never say \"as we discussed before\" or similar forced phrasing.\n"
    "  Just naturally include what you remember in your response.\n\n"
    "--- CUSTOMER PERSONALITY TRACKING ---\n"
    "You are building a mental profile of every customer. Pay attention to:\n"
    "- Their name, location, and how they prefer to communicate.\n"
    "- What they care about — price, quality, speed, trust, relationships.\n"
    "- Past purchases, interests, and intentions they've shared.\n"
    "- Their mood and communication style.\n"
    "Use what you learn to personalise every reply. Show them you know who they are.\n"
    "Your goal: make each customer feel like a valued regular, even on their first chat.\n"
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
    if context:
        name = context.get("user_name", "")
        words = context.get("personality_words", "")
        distance = context.get("distance_setting", "")
        if name:
            biz_context += f"You are representing {name}'s business."
            if words:
                biz_context += f" {name}'s personality: {words}."
            if distance:
                biz_context += f" Service area: {distance}."
        kb = context.get("business_knowledge", [])
        if kb:
            biz_context += "\n\n--- About This Business ---\n"
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
