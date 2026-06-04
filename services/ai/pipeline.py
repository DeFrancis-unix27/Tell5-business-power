import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional

from ai import ai_categorize_message, _generate_content, build_prompt, validate_response
from services.ai.mcp_router import router
from services.ai.circuit_breaker import circuit_breaker
from services.ai.metrics import metrics
from services.ai import mongodb_tools
from config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
BASE_TIMEOUT = 25
TIMEOUT_PER_TIER: dict[str, int] = {
    "gemini": 20,
    "groq": 25,
    "mistral": 25,
}
RETRY_DELAYS = [1.0, 2.0, 4.0]


class PipelineResult:
    def __init__(self):
        self.message_id: Optional[str] = None
        self.category: Optional[str] = None
        self.reply: Optional[str] = None
        self.adk_reply: Optional[str] = None
        self.tier_outputs: dict[int, Any] = {}
        self.errors: list[str] = []
        self.completed_at: Optional[datetime] = None
        self.success: bool = False


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------
async def _call_with_retry(
    provider: str,
    label: str,
    fn,
    *args,
    timeout: int = BASE_TIMEOUT,
    **kwargs,
) -> Optional[Any]:
    if circuit_breaker.is_open(provider):
        logger.warning(f"Circuit breaker open for {provider}, skipping {label}")
        return None

    last_error = ""
    for attempt in range(1, MAX_RETRIES + 1):
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
            elapsed = (time.monotonic() - start) * 1000
            circuit_breaker.record_success(provider)
            metrics.record(provider, True, elapsed)
            return result
        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            last_error = f"timeout after {timeout}s"
            logger.warning(f"{label} timeout (attempt {attempt}/{MAX_RETRIES})")
            metrics.record(provider, False, elapsed, last_error)
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            last_error = str(e)[:120]
            logger.warning(f"{label} failed (attempt {attempt}/{MAX_RETRIES}): {e}")
            metrics.record(provider, False, elapsed, last_error)
            circuit_breaker.record_failure(provider)

        if attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_DELAYS[attempt - 1])

    circuit_breaker.record_failure(provider)
    logger.error(f"{label} failed after {MAX_RETRIES} attempts: {last_error}")
    return None


# ---------------------------------------------------------------------------
# Tier runners
# ---------------------------------------------------------------------------
async def _run_gemini_tier(message: str, tier: int) -> Optional[dict[str, Any]]:
    category = await asyncio.to_thread(ai_categorize_message, message)
    prompt = build_prompt(message, category)

    async def _gemini_call():
        return await asyncio.to_thread(_generate_content, prompt)

    text = await _call_with_retry(
        "gemini",
        f"Tier {tier} Gemini generate",
        _gemini_call,
        timeout=TIMEOUT_PER_TIER["gemini"],
    )

    # Fallback to a different Gemini model if primary fails
    if not text:
        from config import Config
        fallback_model = getattr(Config, "GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
        if fallback_model and fallback_model != Config.GEMINI_MODEL:
            logger.info("Gemini primary failed, falling back to %s", fallback_model)
            import ai as _ai

            async def _gemini_fallback():
                return await asyncio.to_thread(_ai._generate_content, prompt, model=fallback_model)

            text = await _call_with_retry(
                "gemini",
                f"Tier {tier} Gemini fallback ({fallback_model})",
                _gemini_fallback,
                timeout=TIMEOUT_PER_TIER["gemini"],
            )

    # Fallback to OpenRouter if all Gemini models fail
    if not text and router.is_configured("openrouter"):
        logger.info("All Gemini models failed, falling back to OpenRouter")
        from services.ai.openrouter_client import openrouter_generate

        async def _or_fallback():
            return await openrouter_generate(prompt)

        text = await _call_with_retry(
            "openrouter",
            f"Tier {tier} OpenRouter fallback generate",
            _or_fallback,
            timeout=25,
        )

    if not text:
        return None

    try:
        data = json.loads(text)
        validated = validate_response(data)
        return validated
    except (json.JSONDecodeError, TypeError):
        return {"category": category, "reply": None}


async def _run_openrouter_tier(
    message: str,
    tier: int,
    context: Optional[dict[str, Any]],
    result: PipelineResult,
) -> Optional[dict[str, Any]]:
    from services.ai.openrouter_client import openrouter_classify, openrouter_generate_reply

    gemini_output = result.tier_outputs.get(1) or {}
    category = (gemini_output.get("category") if isinstance(gemini_output, dict) else None) or "inquiry"

    async def _classify():
        return await openrouter_classify(message, ["order", "inquiry", "complaint", "feedback"])
    async def _generate():
        return await openrouter_generate_reply(message, category, context)

    or_category = await _call_with_retry("openrouter", f"Tier {tier} OpenRouter classify", _classify, timeout=25)
    or_reply = await _call_with_retry("openrouter", f"Tier {tier} OpenRouter generate", _generate, timeout=25)

    return {
        "category": or_category or category,
        "reply": or_reply,
    }


async def _run_groq_tier(
    message: str,
    tier: int,
    context: Optional[dict[str, Any]],
    result: PipelineResult,
) -> Optional[dict[str, Any]]:
    from services.ai.groq_client import groq_classify, groq_generate_reply

    gemini_output = result.tier_outputs.get(1) or {}
    category = gemini_output.get("category", "inquiry") if isinstance(gemini_output, dict) else "inquiry"

    async def classify():
        return await groq_classify(message, ["order", "inquiry", "complaint", "feedback"])

    async def generate():
        return await groq_generate_reply(message, category, context)

    groq_category = await _call_with_retry("groq", f"Tier {tier} Groq classify", classify, timeout=TIMEOUT_PER_TIER["groq"])
    groq_reply = await _call_with_retry("groq", f"Tier {tier} Groq generate", generate, timeout=TIMEOUT_PER_TIER["groq"])

    return {
        "category": groq_category or category,
        "reply": groq_reply,
    }


async def _run_mistral_tier(message: str, result: PipelineResult) -> Optional[dict[str, Any]]:
    from services.ai.mistral_client import mistral_orchestrate, mistral_format_final

    gemini_output = result.tier_outputs.get(1) or {}
    groq_output = result.tier_outputs.get(2) or {}

    orchestrated = await _call_with_retry(
        "mistral",
        "Tier 3 Mistral orchestrate",
        lambda: mistral_orchestrate(message, gemini_output, groq_output),
        timeout=TIMEOUT_PER_TIER["mistral"],
    )

    if orchestrated:
        try:
            data = json.loads(orchestrated)
            return {
                "category": str(data.get("category", result.category or "inquiry")),
                "reply": str(data.get("reply", result.reply or ""))[:200],
            }
        except (json.JSONDecodeError, TypeError):
            pass

    if result.reply:
        formatted = await _call_with_retry(
            "mistral",
            "Tier 3 Mistral format",
            lambda: mistral_format_final(result.reply, result.category or "inquiry"),
            timeout=15,
        )
        return formatted

    return None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
async def run_pipeline(
    message: str,
    message_id: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
    from_number: Optional[str] = None,
    user_id: Optional[int] = None,
) -> PipelineResult:
    result = PipelineResult()
    result.message_id = message_id
    context = context or {}

    # Build MongoDB context and merge into pipeline context
    if Config.MDB_MCP_CONNECTION_STRING and mongodb_tools.get_mongo_provider():
        try:
            mongo_ctx = await mongodb_tools.build_mongo_context(
                Config.MDB_MCP_DB_NAME,
                from_number or "",
                user_id=user_id,
            )
            if mongo_ctx:
                context["mongodb"] = mongo_ctx
                logger.info("Merged MongoDB context (%d keys) into pipeline context", len(mongo_ctx))
        except Exception as e:
            logger.warning("Failed to build MongoDB context: %s", e)

    # Enrich context with Discovery Engine knowledge base search
    if router.is_configured("discovery_engine"):
        try:
            from services.ai.discovery_engine import search_knowledge
            knowledge = await search_knowledge(message, page_size=3)
            if knowledge:
                context["discovery_engine"] = knowledge
                logger.info("Merged %d Discovery Engine results into pipeline context", len(knowledge))
        except Exception as e:
            logger.warning("Failed to search Discovery Engine: %s", e)

    pipeline_order = router.get_pipeline_order()
    start_total = time.monotonic()

    for i, model_name in enumerate(pipeline_order):
        tier = i + 1
        model_info = router._models.get(model_name)
        if not model_info:
            continue

        provider = model_info["provider"]

        if not router.is_configured(provider):
            logger.info(f"Tier {tier} ({provider}) not configured, skipping")
            result.tier_outputs[tier] = {"skipped": True}
            continue

        try:
            if provider == "gemini":
                output = await _run_gemini_tier(message, tier)
            elif provider == "openrouter":
                output = await _run_openrouter_tier(message, tier, context, result)
            elif provider == "groq":
                output = await _run_groq_tier(message, tier, context, result)
            elif provider == "mistral":
                output = await _run_mistral_tier(message, result)
            else:
                output = None

            result.tier_outputs[tier] = output

            if output and output.get("category"):
                result.category = output["category"]
            if output and output.get("reply"):
                result.reply = output["reply"]

        except Exception as e:
            logger.error(f"Tier {tier} ({provider}) unhandled error: {e}", exc_info=True)
            result.errors.append(f"Tier {tier} ({provider}): {e}")

    result.completed_at = datetime.utcnow()
    result.success = len(result.errors) == 0 or result.reply is not None

    if not result.reply:
        result.reply = "Thank you for your message. We will get back to you shortly."

    # Run ADK agent enrichment
    if router.is_configured("adk"):
        try:
            from services.ai.adk_agent import ask_agent, init_agent
            init_agent()
            user_id_str = str(user_id) if user_id else "anonymous"
            adk_reply = await ask_agent(f"User message: {message}\nContext: {json.dumps(context)}", user_id=user_id_str)
            if adk_reply and "ADK agent is not available" not in adk_reply and "ADK agent not initialized" not in adk_reply:
                result.adk_reply = adk_reply
                logger.info("ADK agent produced a response")
        except Exception as e:
            logger.warning("ADK agent enrichment failed: %s", e)

    # Store conversation and analysis in MongoDB via MCP
    if Config.MDB_MCP_CONNECTION_STRING and from_number and mongodb_tools.get_mongo_provider():
        try:
            await mongodb_tools.store_conversation(
                Config.MDB_MCP_DB_NAME,
                from_number,
                message,
                result.reply,
                result.category or "inquiry",
                user_id=user_id,
            )
            logger.info("Stored conversation in MongoDB")
        except Exception as e:
            logger.warning("Failed to store conversation in MongoDB: %s", e)

    total_ms = (time.monotonic() - start_total) * 1000
    logger.info(f"Pipeline completed in {total_ms:.0f}ms, success={result.success}, errors={len(result.errors)}")

    return result
