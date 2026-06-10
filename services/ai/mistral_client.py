import json
from typing import Any, Optional
from config import Config


def mistral_configured() -> bool:
    return bool(Config.MISTRAL_API_KEY)


async def mistral_orchestrate(
    original_message: str,
    gemini_output: Optional[dict[str, Any]],
    groq_output: Optional[dict[str, Any]],
) -> Optional[str]:
    if not mistral_configured():
        return None
    import httpx

    prompt = f"""You are the final orchestrator for a WhatsApp business AI pipeline.

Original customer message: {original_message}

Tier 1 (Gemini) analysis: {json.dumps(gemini_output or {})}
Tier 2 (Groq) analysis: {json.dumps(groq_output or {})}

Your task:
1. Reconcile any differences between the analyses.
2. Ensure the response is coherent, helpful, and matches the customer's intent.
3. Format a final reply.

Return JSON only:
{{"category": "<category>", "reply": "<final reply>", "confidence": <1-10>}}"""

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {Config.MISTRAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": Config.MISTRAL_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 300,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content
    except Exception:
        return None


async def mistral_format_final(
    reply: str, category: str
) -> Optional[dict[str, Any]]:
    if not mistral_configured():
        return {"category": category, "reply": reply}

    import httpx

    prompt = f"""Review and improve this WhatsApp reply if needed.

Category: {category}
Draft reply: {reply}

Rules:
- Make it sound natural and human, not robotic.
- Match the category tone.
- Keep it conversational.

Return JSON only:
{{"reply": "<improved reply>", "category": "{category}"}}"""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {Config.MISTRAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": Config.MISTRAL_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return {
                "category": str(parsed.get("category", category)),
                "reply": str(parsed.get("reply", reply))[:200],
            }
    except Exception:
        return {"category": category, "reply": reply}
