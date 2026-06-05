import logging
from typing import Any

from config import Config

logger = logging.getLogger(__name__)

_runner: Any = None
_agent: Any = None
_adk_available = False

try:
    from google.adk.agents import LlmAgent
    from google.adk.tools import FunctionTool
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    _adk_available = True
except ImportError:
    logger.warning("google-adk not installed. ADK agent unavailable. Install with: pip install google-adk")

async def _lookup_business(name: str) -> str:
    from sqlalchemy import select
    from db import AsyncSessionLocal
    from models import BusinessProfile

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(BusinessProfile).where(BusinessProfile.business_name.ilike(f"%{name}%"))
        )
        bp = result.scalar_one_or_none()
        if not bp:
            return f"No business found matching '{name}'."
        return (
            f"Business: {bp.business_name}\n"
            f"Category: {bp.category or 'N/A'}\n"
            f"Description: {bp.description or 'N/A'}\n"
            f"Address: {bp.address or 'N/A'}"
        )

async def _list_businesses() -> str:
    from sqlalchemy import select
    from db import AsyncSessionLocal
    from models import BusinessProfile

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(BusinessProfile.business_name, BusinessProfile.category)
        )
        rows = result.all()
        if not rows:
            return "No businesses registered yet."
        return "\n".join(
            f"- {name} ({cat or 'uncategorized'})" for name, cat in rows
        )

async def _conversation_context(phone: str) -> str:
    from services.ai.mongodb_tools import get_mongo_provider

    provider = get_mongo_provider()
    if not provider or not provider.is_ready:
        return "MongoDB not available."
    docs = await provider.find_documents(
        "conversations",
        filter={"from_number": phone},
        sort=[("timestamp", -1)],
        limit=5,
    )
    if not docs:
        return f"No recent conversations for {phone}."
    lines = []
    for d in docs:
        lines.append(
            f"[{d.get('timestamp','')}] {d.get('message','')} -> {d.get('reply','')}"
        )
    return "\n".join(lines)

business_lookup_tool = None
business_list_tool = None
conversation_tool = None

if _adk_available:
    business_lookup_tool = FunctionTool(func=_lookup_business)
    business_list_tool = FunctionTool(func=_list_businesses)
    conversation_tool = FunctionTool(func=_conversation_context)

    def make_agent() -> LlmAgent:
        return LlmAgent(
            name="tell5_customer_support",
            model=Config.GEMINI_MODEL,
            instruction=(
                "You are Tell5 Customer Support Agent. "
                "Help users find businesses, look up business details, "
                "and review conversation context. "
                "Always be concise and helpful."
            ),
            tools=[business_lookup_tool, business_list_tool, conversation_tool],
            output_key="adk_response",
        )

    def init_agent():
        global _agent, _runner
        if not Config.GEMINI_API_KEY:
            logger.info("GEMINI_API_KEY not set, skipping ADK agent")
            return
        _agent = make_agent()
        session_service = InMemorySessionService()
        _runner = Runner(
            agent=_agent,
            app_name="tell5",
            session_service=session_service,
        )
        logger.info("ADK agent initialized")

    async def _ensure_session(user_id: str = "anonymous"):
        if not _runner:
            return
        try:
            session_service = _runner.session_service
            try:
                await session_service.get_session(
                    app_name="tell5", user_id=user_id, session_id="tell5-session"
                )
                return
            except Exception:
                pass
            await session_service.create_session(
                app_name="tell5", user_id=user_id, session_id="tell5-session"
            )
        except Exception as e:
            logger.warning("ADK session setup failed: %s", e)

    async def ask_agent(user_message: str, user_id: str = "anonymous") -> str:
        if not _runner:
            return "ADK agent not initialized. Set GEMINI_API_KEY and restart."
        await _ensure_session(user_id)
        events = []
        async for event in _runner.run_async(
            user_id=user_id,
            session_id="tell5-session",
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=user_message)],
            ),
        ):
            events.append(event)
        for ev in reversed(events):
            if ev.content and ev.content.parts:
                for part in ev.content.parts:
                    if part.text:
                        return part.text
        return "No response generated."

    def is_configured() -> bool:
        return _agent is not None and _runner is not None
else:
    def init_agent():
        logger.info("ADK agent unavailable (google-adk not installed)")

    async def ask_agent(user_message: str, user_id: str = "anonymous") -> str:
        return "ADK agent is not available. Install google-adk to enable."

    def is_configured() -> bool:
        return False
