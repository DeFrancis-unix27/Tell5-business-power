import sentry_sdk
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import Response, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from db import engine, Base, get_db, AsyncSessionLocal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from config import Config
import crud
from ai import ai_configured, draft_reply
from services.ai.mongodb_mcp import MongoDBProvider
from services.ai import mongodb_tools
from auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    cookie_secure,
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)
from csrf import (
    create_csrf_token_with_expiry,
    verify_csrf_token,
    extract_csrf_token_from_request,
    extract_csrf_token_from_headers,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
)
import re
import logging
import base64
import io
import json
import uuid
from pathlib import Path
from typing import Optional
import csv
import qrcode
from twilio.rest import Client
from twilio.request_validator import RequestValidator
from starlette.middleware.sessions import SessionMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Configure logging
logging.basicConfig(level=logging.INFO if not Config.DEBUG else logging.DEBUG)
logger = logging.getLogger(__name__)

# Twilio client initialization with validated config
if Config.TWILIO_ACCOUNT_SID and Config.TWILIO_AUTH_TOKEN:
    twilio_client = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
    validator = RequestValidator(Config.TWILIO_AUTH_TOKEN)
else:
    twilio_client = None
    validator = None

# Sentry error tracking (only in production)
if Config.SENTRY_DSN and Config.ENVIRONMENT == "production":
    sentry_sdk.init(
        dsn=Config.SENTRY_DSN,
        environment=Config.ENVIRONMENT,
        traces_sample_rate=0.25,
        send_default_pii=False,
    )

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)

is_production = Config.ENVIRONMENT == "production"
app = FastAPI(
    title="Tell5 - WhatsApp Workflow Agent",
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
)
app.add_middleware(SessionMiddleware, secret_key=Config.SESSION_SECRET)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse(
    status_code=429,
    content={"detail": "Rate limit exceeded. Too many requests."},
))
templates = Jinja2Templates(directory="templates")

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except RuntimeError:
    logger.warning("static directory not found, skipping mount")


@app.get("/favicon.ico")
async def favicon():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/tell5-icon.svg")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://apis.google.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https:; connect-src 'self' https:; frame-src 'self' https://accounts.google.com")
    return response


@app.middleware("http")
async def error_logging(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        logger.error(f"Unhandled error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )


CSRF_SKIP_PATHS = {
    "/webhook/whatsapp", "/webhook/whatsapp/status",
    "/api/baileys/webhook",
    "/api/auth/signup", "/api/auth/login", "/api/auth/send-reset", "/api/auth/logout",
    "/api/csrf-token",
    "/api/cron/cleanup",
    "/healthz",
}


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    """CSRF protection middleware for form submissions"""
    path = request.url.path.rstrip("/") or "/"

    # Validate CSRF on mutating requests (skip whitelisted paths)
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and path not in CSRF_SKIP_PATHS:
        ctype = request.headers.get("content-type", "")
        # JSON APIs are inherently CSRF-safe — a <form> cannot set application/json
        if "application/json" in ctype:
            pass
        else:
            csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
            if not csrf_cookie:
                return JSONResponse(status_code=403, content={"detail": "Missing CSRF cookie"})
            try:
                csrf_token = extract_csrf_token_from_headers(dict(request.headers))
                if not csrf_token:
                    if "multipart" in ctype:
                        form = await request.form()
                        csrf_token = extract_csrf_token_from_request(dict(form))
                if not csrf_token or not verify_csrf_token(csrf_token, csrf_cookie):
                    return JSONResponse(status_code=403, content={"detail": "Invalid CSRF token"})
            except Exception as e:
                logger.warning("CSRF validation error: %s", e)
                return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})

    response = await call_next(request)

    # Add CSRF token to GET requests that return HTML
    if request.method == "GET" and "text/html" in response.headers.get("content-type", ""):
        _, signed_token = create_csrf_token_with_expiry()
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=signed_token,
            max_age=60 * 60 * 24,
            httponly=True,
            secure=cookie_secure(),
            samesite="lax",
            path="/",
        )

    return response

def categorize_message(text: str) -> str:
    if not text or len(text) < 1:
        return None
    t = text.lower()
    if any(w in t for w in ["complain", "complaint", "issue", "damaged", "bad", "wrong", "refund", "return", "broken", "defective", "poor", "unsatisfied", "disappointed", "frustrated", "annoyed", "terrible", "worst", "not working", "doesn't work", "not good"]):
        return "complaint"
    if any(w in t for w in ["thanks", "thank", "love", "great", "excellent", "feedback", "appreciate", "amazing", "awesome", "wonderful", "good", "nice", "well done", "suggestion"]):
        return "feedback"
    if any(w in t for w in ["order", "buy", "purchase", "delivery", "shipping", "track", "cancel order", "place order", "cart", "checkout"]):
        return "order"
    if any(w in t for w in ["price", "how", "info", "details", "when", "cost", "what", "describe", "tell me", "available", "stock", "offer", "discount", "promo", "location", "address", "open", "close", "hours"]):
        return "inquiry"
    return "pending"


WA_QR_STATE_FILE = Path("services/whatsapp/qr-state.json")


def is_twilio_enabled() -> bool:
    return bool(Config.TWILIO_ACCOUNT_SID and Config.TWILIO_AUTH_TOKEN and Config.TWILIO_PHONE_NUMBER)


def _load_whatsapp_state() -> dict:
    if not WA_QR_STATE_FILE.exists():
        return {}
    try:
        return json.loads(WA_QR_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Unable to read WhatsApp QR state: {exc}")
        return {}


def is_baileys_connected() -> bool:
    state = _load_whatsapp_state()
    return bool(state.get("connected"))


def get_whatsapp_qr_state() -> dict:
    state = _load_whatsapp_state()
    return {
        "connected": bool(state.get("connected")),
        "qr": state.get("qr"),
        "message": state.get("message", "Scan the QR code with WhatsApp to connect."),
    }


def generate_qr_data_url(qr_text: str) -> str:
    img = qrcode.make(qr_text)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def parse_order(text: str) -> tuple[str, int]:
    # crude extractor: look for number + item, or last word as item
    m = re.search(r"(\d+)\s+([a-zA-Z]+)", text)
    if m:
        return m.group(2), int(m.group(1))
    # fallback: first noun-like word after 'order' or entire body
    words = re.findall(r"[a-zA-Z]+", text)
    if not words:
        return ("item", 1)
    return (words[-1], 1)


def public_user(user) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "is_admin": bool(user.is_admin),
        "ai_reply_enabled": bool(getattr(user, "ai_reply_enabled", True)),
        "ai_enabled": bool(getattr(user, "ai_enabled", True)),
        "has_google": bool(getattr(user, "google_id", None)),
    }


def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


async def validate_csrf(request: Request) -> bool:
    """Validate CSRF token from request

    Checks both form data and headers for CSRF token.
    """
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if not csrf_cookie:
        return False

    try:
        form = await request.form()
        csrf_token = extract_csrf_token_from_request(dict(form))

        if not csrf_token:
            csrf_token = extract_csrf_token_from_headers(dict(request.headers))

        if not csrf_token:
            return False

        return verify_csrf_token(csrf_token, csrf_cookie)
    except Exception as e:
        logger.warning(f"CSRF validation error: {e}")
        return False


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = verify_session_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = await crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_admin_user(user=Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def verify_baileys_webhook(request: Request):
    if Config.BAILEYS_WEBHOOK_SECRET:
        header_secret = request.headers.get("X-Baileys-Secret", "")
        if header_secret != Config.BAILEYS_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
    return True


async def verify_cron(request: Request):
    secret = request.headers.get("X-Cron-Secret", "") or request.query_params.get("secret", "")
    # Also check raw URL to handle + in secrets (query_params decodes + as space)
    if not secret and Config.CRON_SECRET:
        import re as _re
        m = _re.search(r"[?&]secret=([^&]+)", str(request.url))
        if m:
            secret = m.group(1)
    if Config.CRON_SECRET and secret != Config.CRON_SECRET:
        raise HTTPException(status_code=403, detail="Invalid cron secret")
    return True


def set_auth_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(user_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


@app.on_event("startup")
async def startup():
    # create tables if missing
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name != "postgresql":
            logger.info("Database tables initialized")
            return
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id INTEGER"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS channel VARCHAR(50) DEFAULT 'whatsapp'"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS user_id INTEGER"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS channel VARCHAR(50) DEFAULT 'whatsapp'"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_reply_enabled BOOLEAN NOT NULL DEFAULT TRUE"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255) UNIQUE"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS pricing_tier VARCHAR(20) NOT NULL DEFAULT 'free'"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_enabled BOOLEAN NOT NULL DEFAULT TRUE"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS ai_response TEXT"))
        await conn.execute(text("ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS phone VARCHAR(30)"))
        await conn.execute(text("ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS hours VARCHAR(200)"))
        await conn.execute(text("ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS website VARCHAR(255)"))
        await conn.execute(text("ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS logo_url TEXT"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS contact_name VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS profile_pic_url TEXT"))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS site_config (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS personality_qa (
                id SERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                mode VARCHAR(20) NOT NULL DEFAULT 'business',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        admin_email = (Config.ADMIN_EMAIL or "").strip().lower()
        if admin_email:
            await conn.execute(text("UPDATE users SET is_admin = TRUE WHERE lower(email) = :email"), {"email": admin_email})
        await conn.execute(text("""
            UPDATE users
            SET is_admin = TRUE
            WHERE id = (SELECT id FROM users ORDER BY id ASC LIMIT 1)
            AND NOT EXISTS (SELECT 1 FROM users WHERE is_admin = TRUE)
        """))
        # Seed personality Q&A about the owner
        owner_qa = [
            ("who is francis", "Francis David is the founder, owner, and lead developer of Tell5. He is based in Nigeria and also works with Meta on AI and messaging technologies. His portfolio: https://francisdave.vercel.app — GitHub: https://github.com/DeFrancis-unix27", "personal"),
            ("who created tell5", "Tell5 was created and is owned by Francis David — a Nigerian AI/tech entrepreneur who also collaborates with Meta. Portfolio: https://francisdave.vercel.app", "personal"),
            ("who owns tell5", "Tell5 is owned by Francis David (aka DeFrancis). He is based in Nigeria and works with Meta on AI-driven messaging. Portfolio: https://francisdave.vercel.app", "personal"),
            ("who made you", "I was built by Francis David as part of the Tell5 AI platform. He is a Nigerian developer who also contributes to Meta's AI initiatives. More at https://francisdave.vercel.app", "personal"),
            ("tell me about francis", "Francis David is the founder and developer of Tell5, based in Nigeria. He works with Meta on messaging and AI technologies. Portfolio: https://francisdave.vercel.app — GitHub: https://github.com/DeFrancis-unix27", "personal"),
            ("what is francis david portfolio", "Francis David's portfolio is at https://francisdave.vercel.app. He is the founder of Tell5 and works with Meta.", "personal"),
            ("what is defrancis github", "DeFrancis-unix27 is Francis David's GitHub handle. Visit https://github.com/DeFrancis-unix27", "personal"),
            ("does francis work with meta", "Yes, Francis David works with Meta on AI and messaging platform technologies, alongside building Tell5.", "personal"),
            ("where is francis from", "Francis David is from Nigeria. He is the founder of Tell5 and works with Meta.", "personal"),
        ]
        for q, a, m in owner_qa:
            try:
                result = await conn.execute(
                    text("SELECT 1 FROM personality_qa WHERE LOWER(question) = LOWER(:q)"),
                    {"q": q},
                )
                if not result.fetchone():
                    await conn.execute(
                        text("INSERT INTO personality_qa (question, answer, mode) VALUES (:q, :a, :m)"),
                        {"q": q, "a": a, "m": m},
                    )
            except Exception:
                pass
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS knowledge_entries (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) NOT NULL,
                content TEXT NOT NULL,
                category VARCHAR(50),
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                personality_words VARCHAR(500) NOT NULL,
                distance_setting VARCHAR(50) NOT NULL,
                onboarding_complete BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
    logger.info("Database tables initialized")

    # --- Start MongoDB provider ---
    if Config.MDB_MCP_CONNECTION_STRING:
        try:
            provider = MongoDBProvider(
                connection_string=Config.MDB_MCP_CONNECTION_STRING,
                db_name=Config.MDB_MCP_DB_NAME,
                read_only=Config.MDB_MCP_READ_ONLY,
                model_api_keys=Config.MDB_MCP_MODEL_API_KEYS,
            )
            await provider.start()
            mongodb_tools.set_mongo_provider(provider)
            app.state.mongo_provider = provider
            logger.info("MongoDB provider started (db=%s)", Config.MDB_MCP_DB_NAME)
        except Exception as e:
            logger.warning("Failed to start MongoDB provider: %s", e)
            app.state.mongo_provider = None
    else:
        logger.info("MDB_MCP_CONNECTION_STRING not set, skipping MongoDB")

    # --- Start Discovery Engine client ---
    from services.ai.discovery_engine import DiscoveryEngineClient, set_client
    de_client = DiscoveryEngineClient()
    await de_client.start()
    set_client(de_client)
    app.state.discovery_engine = de_client

    # --- Load pricing mode ---
    try:
        async with AsyncSessionLocal() as sess:
            from models import SiteConfig
            from sqlalchemy import select
            q = await sess.execute(select(SiteConfig).where(SiteConfig.key == "pricing_enabled"))
            cfg = q.scalar_one_or_none()
            if cfg and cfg.value == "true":
                from services.billing import set_pricing_enabled
                set_pricing_enabled(True)
    except Exception as e:
        logger.warning("Failed to load pricing config: %s", e)

    # --- Init personality Q&A cache ---
    try:
        from services.ai.personality import load_qa_cache
        async with AsyncSessionLocal() as sess:
            await load_qa_cache(sess)
            app.state._qa_cache_loaded = True
    except Exception as e:
        logger.warning("Failed to load personality Q&A cache: %s", e)
        app.state._qa_cache_loaded = False

    # --- Init ADK agent ---
    from services.ai.adk_agent import init_agent
    init_agent()

    # --- Weekly conversation cleanup (keep last 7 days) ---
    try:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        async with AsyncSessionLocal() as sess:
            await sess.execute(
                text("DELETE FROM conversations WHERE timestamp < :cutoff"),
                {"cutoff": cutoff},
            )
            await sess.commit()
            logger.info("Cleaned up conversations older than 7 days")
    except Exception as e:
        logger.warning("Failed to clean up old conversations: %s", e)


@app.on_event("shutdown")
async def shutdown():
    mcp = getattr(app.state, "mongo_provider", None)
    if mcp:
        await mcp.close()
        logger.info("MongoDB provider stopped")
    de = getattr(app.state, "discovery_engine", None)
    if de:
        await de.close()
        logger.info("Discovery Engine client stopped")
    # Dispose SQLAlchemy engine to avoid stale connections on reload
    try:
        from db import engine
        await engine.dispose()
        logger.info("Database engine disposed")
    except Exception:
        pass


def validate_twilio_request(request_url: str, post_data: dict, signature: str) -> bool:
    """Validate that request came from Twilio"""
    return validator.validate(request_url, post_data, signature)


async def _get_onboarding_profile(db: AsyncSession | None, user_id: int) -> dict | None:
    from services.ai.mongodb_tools import get_user_profile
    if Config.MDB_MCP_CONNECTION_STRING:
        try:
            profile = await get_user_profile(Config.MDB_MCP_DB_NAME, user_id)
            if profile:
                return profile
        except Exception as e:
            logger.warning("Failed to check onboarding in MongoDB: %s", e)
    if db:
        try:
            from crud import get_user_profile_pg
            pg = await get_user_profile_pg(db, user_id)
            if pg:
                return {
                    "name": pg.name,
                    "personality_words": pg.personality_words,
                    "distance_setting": pg.distance_setting,
                }
        except Exception as e:
            logger.warning("Failed to check onboarding in PG: %s", e)
    return None


async def _save_onboarding_profile(db: AsyncSession, user_id: int, name: str, personality_words: str, distance_setting: str) -> bool:
    ok = False
    if Config.MDB_MCP_CONNECTION_STRING:
        try:
            from services.ai.mongodb_tools import store_user_profile
            ok = await store_user_profile(Config.MDB_MCP_DB_NAME, user_id, name, personality_words, distance_setting)
        except Exception as e:
            logger.warning("Failed to store onboarding in MongoDB: %s", e)
    if not ok:
        try:
            from crud import upsert_user_profile_pg
            await upsert_user_profile_pg(db, user_id, name, personality_words, distance_setting)
            ok = True
        except Exception as e:
            logger.warning("Failed to store onboarding in PG: %s", e)
    return ok


async def _process_incoming_message(
    db: AsyncSession,
    from_number: str,
    body: str,
    to_number: str | None = None,
    channel: str = "whatsapp",
    contact_name: str | None = None,
    profile_pic_url: str | None = None,
) -> dict:
    """Shared message processing for both Twilio and Baileys"""
    target_user_id = None
    ai_reply_enabled = True
    ai_pipeline_enabled = True
    if to_number:
        normalized_to = str(to_number).replace("whatsapp:", "").replace(" ", "").split("@")[0].strip()
        target_user = await crud.get_user_by_phone(db, normalized_to)
        if target_user:
            target_user_id = target_user.id
            ai_reply_enabled = bool(getattr(target_user, "ai_reply_enabled", True))
            ai_pipeline_enabled = bool(getattr(target_user, "ai_enabled", True))
    if target_user_id is None and channel == "baileys":
        # Fallback: try to match the sender as the business owner
        normalized_from = from_number.replace("whatsapp:", "").replace(" ", "").split("@")[0].strip()
        if len(normalized_from) > 5:
            target_user = await crud.get_user_by_phone(db, normalized_from)
            if target_user:
                target_user_id = target_user.id
                ai_reply_enabled = bool(getattr(target_user, "ai_reply_enabled", True))
                ai_pipeline_enabled = bool(getattr(target_user, "ai_enabled", True))
    if target_user_id is None:
        # Fallback: grab the first registered user (single-business deployment)
        target_user = await crud.get_first_user(db)
        if target_user:
            target_user_id = target_user.id
            ai_reply_enabled = bool(getattr(target_user, "ai_reply_enabled", True))
            ai_pipeline_enabled = bool(getattr(target_user, "ai_enabled", True))

    phone = from_number

    # Track/update customer profile
    if target_user_id and phone:
        try:
            await crud.get_or_create_customer(db, target_user_id, phone, contact_name)
        except Exception as e:
            logger.warning("Failed to track customer: %s", e)

    # If AI pipeline is disabled for this user, store message without processing
    if not ai_pipeline_enabled:
        category = categorize_message(body) or "pending"
        ack = "Thanks for your message. Noted!"
        await crud.create_conversation(db, phone=phone, message=body, category=category, user_id=target_user_id, channel=channel, ai_response=ack, contact_name=contact_name, profile_pic_url=profile_pic_url)
        await db.commit()
        return {"reply": ack, "category": category, "conv_id": None, "pipeline_success": False, "ai_disabled": True}

    # ── Personality: match Q&A first ──
    from services.ai.personality import match_qa, should_block_message, load_qa_cache
    if not hasattr(app.state, "_qa_cache_loaded") or not app.state._qa_cache_loaded:
        await load_qa_cache(db)
        app.state._qa_cache_loaded = True

    personality_match = match_qa(body)

    # If a personality Q&A matches, use the stored answer directly
    if personality_match:
        category = categorize_message(body) or "inquiry"
        ai_reply = personality_match["answer"]
        await crud.create_conversation(db, phone=phone, message=body, category=category, user_id=target_user_id, channel=channel, ai_response=ai_reply, contact_name=contact_name, profile_pic_url=profile_pic_url)
        await db.commit()
        return {
            "reply": ai_reply,
            "category": category,
            "conv_id": None,
            "pipeline_success": True,
            "personality_mode": personality_match["mode"],
        }

    # Block only clearly non-business chat; acknowledge politely instead of silence
    if should_block_message(body):
        category = categorize_message(body) or "inquiry"
        ack = "Got it! Is there anything about the business I can help you with?"
        await crud.create_conversation(db, phone=phone, message=body, category=category, user_id=target_user_id, channel=channel, ai_response=ack, contact_name=contact_name, profile_pic_url=profile_pic_url)
        await db.commit()
        return {
            "reply": ack,
            "category": category,
            "conv_id": None,
            "pipeline_success": True,
            "personality_mode": "quiet",
        }

    # Load business knowledge base entries to shape AI responses
    knowledge_context = {}
    if target_user_id:
        try:
            from crud import list_knowledge
            entries = await list_knowledge(db, target_user_id)
            if entries:
                knowledge_context["business_knowledge"] = [{"content": e.content, "category": e.category} for e in entries[:20]]
                logger.info("Loaded %d knowledge entries for user %d", len(entries), target_user_id)
        except Exception as e:
            logger.warning("Failed to load knowledge base: %s", e)

    # Load user personality profile to shape AI responses
    personality_context = {}
    if target_user_id:
        try:
            profile = await _get_onboarding_profile(db, target_user_id)
            if profile:
                personality_context = {
                    "user_name": profile.get("name", ""),
                    "personality_words": profile.get("personality_words", ""),
                    "distance_setting": profile.get("distance_setting", ""),
                }
                logger.info("Loaded personality profile for user %d", target_user_id)
        except Exception as e:
            logger.warning("Failed to load personality profile: %s", e)

        # Load business_name so the AI knows which business it represents
        try:
            from crud import get_business_profile
            bp = await get_business_profile(db, target_user_id)
            if bp and bp.business_name:
                personality_context["business_name"] = bp.business_name
                personality_context["services"] = bp.services or ""
                personality_context["price_range"] = bp.price_range or ""
                logger.info("Loaded business name for user %d: %s", target_user_id, bp.business_name)
        except Exception as e:
            logger.warning("Failed to load business name: %s", e)

        # Load owner name from user record
        try:
            owner = await crud.get_user_by_id(db, target_user_id)
            if owner:
                personality_context["owner_name"] = f"{owner.first_name} {owner.last_name}".strip()
        except Exception as e:
            logger.warning("Failed to load owner name: %s", e)

    # Inject Tell5 Q&A knowledge into context for AI awareness
    tell5_qa_context = {}
    try:
        from services.ai.personality import _qa_cache
        if _qa_cache:
            tell5_qa_context["tell5_knowledge"] = [
                {"question": q["question"], "answer": q["answer"], "mode": q["mode"]}
                for q in _qa_cache
            ]
    except Exception:
        pass

    # ── Pipeline processing with safety net ──
    from services.ai.pipeline import run_pipeline, PipelineResult
    import uuid
    message_id = str(uuid.uuid4())
    merged_context = {}
    if personality_context:
        merged_context.update(personality_context)
    if knowledge_context:
        merged_context.update(knowledge_context)
    if tell5_qa_context:
        merged_context.update(tell5_qa_context)
    # Inject founder persona so ADK agent & all AI tiers know the voice
    merged_context["founder_persona"] = {
        "name": "Francis David",
        "role": "Founder & Developer of Tell5",
        "location": "Nnewi, Anambra State, Nigeria",
        "voice": "Warm but direct. Professional but not corporate. No robot speak.",
        "values": "Honesty over hype, simplicity over complexity, reliability over flash, growth through service.",
        "style": "Patient, knowledgeable, proud of what he's building, always improving.",
        "goal": "Every customer should feel like they're talking to the founder himself — someone who genuinely cares about their business success.",
        "background": "Developer and entrepreneur. Built Tell5 to solve real problems for African entrepreneurs. Hands-on from architecture to customer support. Mentors other developers. Believes small businesses deserve enterprise tools without enterprise pricing.",
    }

    pipeline_result = None
    try:
        pipeline_result = await run_pipeline(
            body, message_id=message_id, from_number=phone, user_id=target_user_id,
            context=merged_context if merged_context else None,
            db=db,
        )
    except Exception as e:
        logger.error(f"Pipeline crashed: {e}", exc_info=True)

    if pipeline_result is None:
        pipeline_result = PipelineResult()
        pipeline_result.reply = None
        pipeline_result.category = categorize_message(body) or "inquiry"
        pipeline_result.errors = ["Pipeline crashed"]
        pipeline_result.success = False

    # If AI replies are disabled for this user, clear the auto-generated reply
    if not ai_reply_enabled:
        pipeline_result.reply = None
        pipeline_result.adk_reply = None
    # Prefer ADK agent response over standard pipeline reply
    if pipeline_result.adk_reply:
        ai_reply = pipeline_result.adk_reply
    else:
        ai_reply = pipeline_result.reply
    # Ensure we always have a fallback reply
    if not ai_reply:
        ai_reply = "Thank you for your message. We'll get back to you shortly."
    category = pipeline_result.category or categorize_message(body) or "inquiry"

    if pipeline_result.tier_outputs:
        await crud.create_pipeline_log(
            db,
            message=body,
            category=category,
            gemini_output=str(pipeline_result.tier_outputs.get(1)),
            groq_output=str(pipeline_result.tier_outputs.get(2)),
            mistral_output=str(pipeline_result.tier_outputs.get(3)),
            final_reply=ai_reply,
            errors="; ".join(pipeline_result.errors) if pipeline_result.errors else None,
            success=pipeline_result.success,
        )

    conv = await crud.create_conversation(db, phone=phone, message=body, category=category, user_id=target_user_id, channel=channel, ai_response=ai_reply, contact_name=contact_name, profile_pic_url=profile_pic_url)

    reply = ""
    if category == "order":
        item, qty = parse_order(body)
        order = await crud.create_order(db, phone=phone, item=item, quantity=qty, user_id=target_user_id)
        await crud.create_notification(db, ntype="new_order", payload=f"order:{order.id}")
        reply = ai_reply
    elif category == "inquiry":
        reply = ai_reply
    elif category == "complaint":
        reply = ai_reply
    else:
        reply = ai_reply

    await db.commit()
    return {"reply": reply, "category": category, "conv_id": conv.id, "pipeline_success": pipeline_result.success}


@app.post("/webhook/whatsapp")
@limiter.limit("100/minute")
async def whatsapp_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    signature = request.headers.get("X-Twilio-Signature", "")
    form = await request.form()
    form_dict = dict(form)
    request_url = str(request.url)

    if not validate_twilio_request(request_url, form_dict, signature):
        logger.warning(f"Invalid Twilio signature from {form.get('From')}")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    from_number: Optional[str] = form.get("From")
    to_number: Optional[str] = form.get("To")
    body: Optional[str] = form.get("Body")

    if not from_number or not body:
        raise HTTPException(status_code=400, detail="Missing From or Body")

    logger.info(f"Twilio message from {from_number}: {body[:80]}")

    result = await _process_incoming_message(db, from_number, body, to_number, channel="twilio")

    if twilio_client and Config.TWILIO_PHONE_NUMBER:
        try:
            twilio_client.messages.create(
                from_=Config.TWILIO_PHONE_NUMBER,
                body=result["reply"],
                to=from_number,
            )
        except Exception as e:
            logger.error(f"Twilio send failed: {e}")

    twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    return Response(content=twiml, media_type="application/xml")


@app.post("/api/baileys/webhook")
@limiter.limit("30/minute")
async def baileys_webhook(request: Request, db: AsyncSession = Depends(get_db), _=Depends(verify_baileys_webhook)):
    """Receives messages forwarded from the Baileys WhatsApp bot"""
    data = await request.json()
    from_number = str(data.get("from", "")).strip()
    body = str(data.get("body", "")).strip()
    push_name = str(data.get("push_name", "")).strip() or None
    profile_pic_url = str(data.get("profile_pic_url", "")).strip() or None
    to_number = str(data.get("to", "")).strip() or None

    if not from_number or not body:
        raise HTTPException(status_code=400, detail="Missing from or body")

    logger.info(f"Baileys message from {push_name or from_number}: {body[:80]}")

    result = await _process_incoming_message(
        db, from_number, body, to_number=to_number, channel="baileys",
        contact_name=push_name, profile_pic_url=profile_pic_url,
    )

    return {"reply": result["reply"], "to": from_number, "category": result["category"]}


@app.get("/api/baileys/status")
async def baileys_status(user=Depends(get_current_user)):
    """Check if the Baileys bot is running and connected"""
    # First check local state file (fast)
    state = get_whatsapp_qr_state()
    if state["connected"]:
        return {"ok": True, "connected": True}
    # Then check bot HTTP endpoint
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{Config.BOT_URL}/health")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {"ok": False, "connected": False, "message": state.get("message", "")}


@app.get("/api/pipeline/metrics")
async def pipeline_metrics(user=Depends(get_admin_user)):
    """Returns pipeline performance metrics for monitoring"""
    from services.ai.metrics import metrics
    return metrics.snapshot()


@app.get("/api/pipeline/circuit-breaker")
async def circuit_breaker_status(user=Depends(get_admin_user)):
    """Returns circuit breaker state for each provider"""
    from services.ai.circuit_breaker import circuit_breaker
    providers = ["gemini", "openrouter", "groq", "mistral"]
    return {
        p: {
            "state": circuit_breaker._state.get(p, "closed") if hasattr(circuit_breaker, "_state") else "closed",
            "failures": circuit_breaker._failures.get(p, 0),
        }
        for p in providers
    }


@app.get("/api/csrf-token")
async def get_csrf_token(request: Request):
    """Get a CSRF token for form submissions

    Returns a CSRF token that should be included in form submissions
    or as X-CSRF-Token header in POST requests.
    """
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if csrf_cookie:
        parts = csrf_cookie.split(":")
        if len(parts) == 3:
            token = parts[0]
            return {
                "csrf_token": token,
                "header_name": CSRF_HEADER_NAME,
            }
    token, signed = create_csrf_token_with_expiry()
    resp = JSONResponse({"csrf_token": token, "header_name": CSRF_HEADER_NAME})
    resp.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=signed,
        max_age=3600,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        path="/",
    )
    return resp


@app.post("/api/auth/signup")
@limiter.limit("5/minute")
async def signup(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    first_name = str(data.get("first_name", "")).strip()
    last_name = str(data.get("last_name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not first_name or not last_name or not email or not password:
        raise HTTPException(status_code=400, detail="Please fill in all required fields.")
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    existing = await crud.get_user_by_email(db, email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    is_first_user = await crud.count_users(db) == 0
    user = await crud.create_user(
        db,
        email=email,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        password_hash=hash_password(password),
        is_admin=is_first_user,
    )
    await db.commit()

    response = JSONResponse(content={"user": public_user(user)})
    set_auth_cookie(response, user.id)
    return response


@app.post("/api/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not email or not password:
        raise HTTPException(status_code=400, detail="Please enter your email and password.")

    user = await crud.get_user_by_email(db, email)
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    response = JSONResponse(content={"user": public_user(user)})
    set_auth_cookie(response, user.id)
    return response


@app.post("/api/auth/logout")
async def logout():
    response = JSONResponse(content={"ok": True})
    clear_auth_cookie(response)
    return response


@app.get("/api/auth/me")
async def me(user=Depends(get_current_user)):
    return {"user": public_user(user)}


@app.post("/api/auth/send-reset")
@limiter.limit("3/minute")
async def send_reset(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    email = str(data.get("email", "")).strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    user = await crud.get_user_by_email(db, email)
    if not user:
        return {"ok": True, "message": "If that email exists, a reset link has been sent."}
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await crud.create_password_reset_token(db, user.id, token, expires_at)
    await db.commit()
    reset_url = f"/auth/reset/{token}"
    logger.info(f"Password reset token generated for {email}: {reset_url}")
    return {"ok": True, "redirect": reset_url}


@app.get("/auth/reset/{token}", response_class=HTMLResponse)
async def reset_password_page(token: str, db: AsyncSession = Depends(get_db)):
    record = await crud.get_password_reset_token(db, token)
    if not record:
        return HTMLResponse(content=_get_cached_page("templates/reset_password_invalid.html"))
    return HTMLResponse(
        content=_get_cached_page("templates/reset_password.html")
        .replace("{{TOKEN}}", token)
    )


@app.post("/api/auth/reset-password")
@limiter.limit("3/minute")
async def reset_password(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    token = str(data.get("token", "")).strip()
    password = str(data.get("password", ""))
    if not token or not password:
        raise HTTPException(status_code=400, detail="Token and password are required.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    record = await crud.get_password_reset_token(db, token)
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
    password_hash = hash_password(password)
    await crud.update_user_password(db, record.user_id, password_hash)
    await crud.mark_reset_token_used(db, record.id)
    await db.commit()
    logger.info(f"Password reset completed for user_id={record.user_id}")
    return {"ok": True, "message": "Password reset successfully."}


@app.post("/api/user/ai-reply-toggle")
async def ai_reply_toggle(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user.ai_reply_enabled = not user.ai_reply_enabled
    await db.flush()
    logger.info("User %d AI reply toggled to %s", user.id, user.ai_reply_enabled)
    return {"ok": True, "ai_reply_enabled": bool(user.ai_reply_enabled)}


@app.post("/api/user/ai-toggle")
async def ai_toggle(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user.ai_enabled = not user.ai_enabled
    await db.flush()
    logger.info("User %d AI pipeline toggled to %s", user.id, user.ai_enabled)
    return {"ok": True, "ai_enabled": bool(user.ai_enabled)}


# ── Onboarding ──

@app.get("/api/onboarding/status")
async def onboarding_status(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profile = await _get_onboarding_profile(db, user.id)
    return {"onboarding_complete": profile is not None}


@app.post("/api/onboarding")
async def submit_onboarding(request: Request, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    body = await request.json()
    name = str(body.get("name", "")).strip()
    personality_words = str(body.get("personality_words", "")).strip()
    distance_setting = str(body.get("distance_setting", "")).strip()

    if not name or not personality_words or not distance_setting:
        raise HTTPException(status_code=400, detail="All fields are required")
    if distance_setting not in ("professional & distant", "balanced & friendly", "casual & personal"):
        raise HTTPException(status_code=400, detail="Invalid distance setting")

    ok = await _save_onboarding_profile(db, user.id, name, personality_words, distance_setting)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save onboarding profile")
    await db.commit()
    return {"ok": True}


@app.get("/api/auth/google")
async def google_login(request: Request):
    if not Config.GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    from authlib.integrations.starlette_client import OAuth
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=Config.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=Config.GOOGLE_OAUTH_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    redirect_uri = str(Config.OAUTH_REDIRECT_URI)
    if not redirect_uri.startswith("http"):
        redirect_uri = str(request.base_url).rstrip("/") + redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/api/auth/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    if not Config.GOOGLE_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    from authlib.integrations.starlette_client import OAuth
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=Config.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=Config.GOOGLE_OAUTH_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        logger.warning("Google OAuth callback failed: %s", e)
        raise HTTPException(status_code=400, detail="OAuth authentication failed")
    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = token
    email = str(userinfo.get("email", "")).lower().strip()
    google_id = str(userinfo.get("sub", ""))
    first_name = str(userinfo.get("given_name", userinfo.get("name", "Google")[:100]))
    last_name = str(userinfo.get("family_name", "User")[:100])
    if not email:
        raise HTTPException(status_code=400, detail="Email not provided by Google")
    user = await crud.get_user_by_email(db, email)
    if not user:
        import secrets
        from auth import hash_password
        user = crud.User(
            email=email,
            google_id=google_id,
            first_name=first_name,
            last_name=last_name,
            password_hash=hash_password(secrets.token_urlsafe(32)),
        )
        db.add(user)
        await db.flush()
        logger.info("Created new user via Google OAuth: %s", email)
    else:
        if not user.google_id:
            user.google_id = google_id
            await db.flush()
    response = RedirectResponse(url="/dashboard")
    set_auth_cookie(response, user.id)
    return response


@app.post("/api/ai/draft-reply")
async def ai_draft_reply(request: Request, user=Depends(get_current_user)):
    data = await request.json()
    message = str(data.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    reply = await draft_reply(message)
    if not reply:
        reply = "Thanks for your message. A team member will respond shortly."
    return {"reply": reply, "ai_enabled": ai_configured()}


async def _count_personality_qa(db: AsyncSession) -> int:
    from models import PersonalityQA
    from sqlalchemy import select, func
    q = await db.execute(select(func.count(PersonalityQA.id)))
    return q.scalar() or 0


@app.get("/api/admin/summary")
async def admin_summary(db: AsyncSession = Depends(get_db), user=Depends(get_admin_user)):
    convs = await crud.list_conversations(db)
    orders = await crud.list_orders(db)
    users = await crud.list_users(db)
    s = await crud.stats(db)
    from services.ai.groq_client import groq_configured
    from services.ai.mistral_client import mistral_configured
    from services.ai.discovery_engine import get_client as get_de_client
    from services.ai.adk_agent import is_configured as adk_configured
    from models import PipelineLog, BusinessProfile, ContactMessage
    from sqlalchemy import select, func
    pl_q = await db.execute(select(func.count(PipelineLog.id)))
    pipeline_count = pl_q.scalar() or 0
    bp_q = await db.execute(select(func.count(BusinessProfile.id)))
    biz_count = bp_q.scalar() or 0
    cm_q = await db.execute(select(func.count(ContactMessage.id)))
    contact_count = cm_q.scalar() or 0
    cm_rows = await db.execute(
        select(ContactMessage).order_by(ContactMessage.created_at.desc()).limit(5)
    )
    recent_contacts = [{
        "id": r.id, "name": r.name, "email": r.email,
        "subject": r.subject, "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in cm_rows.scalars()]
    return {
        "stats": s,
        "total_users": len(users),
        "total_conversations": len(convs),
        "total_orders": len(orders),
        "ai_enabled": ai_configured(),
        "groq_enabled": groq_configured(),
        "mistral_enabled": mistral_configured(),
        "twilio_configured": is_twilio_enabled(),
        "discovery_configured": bool(get_de_client() and get_de_client().configured),
        "adk_configured": adk_configured(),
        "personality_qa_count": await _count_personality_qa(db),
        "pipeline_runs": pipeline_count,
        "business_profiles": biz_count,
        "contact_messages": contact_count,
        "recent_contacts": recent_contacts,
        "channels": ["whatsapp"],
        "recent_users": [public_user(u) for u in users[:10]],
        "recent_conversations": [{
            "id": c.id,
            "phone": c.phone,
            "message": c.message,
            "category": c.category,
            "timestamp": c.timestamp.isoformat() if c.timestamp else None,
        } for c in convs[:10]],
    }


@app.get("/api/conversations")
async def get_conversations(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if user.is_admin:
        convs = await crud.list_conversations(db, None)
    else:
        convs = await crud.list_conversations(db, user.id)
    return JSONResponse(content=[{
        "id": c.id,
        "phone": c.phone,
        "contact_name": c.contact_name,
        "profile_pic_url": c.profile_pic_url,
        "message": c.message,
        "category": c.category,
        "channel": c.channel,
        "ai_response": c.ai_response,
        "timestamp": c.timestamp.isoformat() if c.timestamp else None
    } for c in convs])


@app.get("/api/orders")
async def get_orders(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if user.is_admin:
        orders = await crud.list_orders(db, None)
    else:
        orders = await crud.list_orders(db, user.id)
    return JSONResponse(content=[{
        "id": o.id,
        "phone": o.phone,
        "customer_name": o.customer_name,
        "item": o.item,
        "quantity": o.quantity,
        "status": o.status,
        "timestamp": o.timestamp.isoformat() if o.timestamp else None
    } for o in orders])


@app.get("/api/stats")
async def get_stats(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    s = await crud.stats(db, None if user.is_admin else user.id)
    return s


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    if not user_id or not await crud.get_user_by_id(db, user_id):
        return RedirectResponse(url="/")
    if not is_twilio_enabled() and not is_baileys_connected():
        return RedirectResponse(url="/whatsapp-connect")
    return HTMLResponse(content=_get_cached_page("templates/dashboard.html"))


@app.get("/api/whatsapp/pairing-code")
async def request_pairing_code(phone: str = "", user=Depends(get_current_user)):
    if not phone.strip():
        raise HTTPException(status_code=400, detail="Phone number required")
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{Config.BOT_URL}/request-pairing-code", json={"phone": phone.strip()})
        return resp.json()


@app.post("/api/whatsapp/restart")
async def restart_baileys(user=Depends(get_current_user)):
    """Force restart the Baileys bot with fresh auth (clears stale creds)"""
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{Config.BOT_URL}/restart")
        return resp.json()


@app.get("/api/whatsapp/qr")
async def whatsapp_qr(user=Depends(get_current_user)):
    """Returns status of both WhatsApp channels (Twilio + Baileys)"""
    twilio_active = bool(Config.TWILIO_ACCOUNT_SID and Config.TWILIO_AUTH_TOKEN)
    state = get_whatsapp_qr_state()
    return {
        "twilio": {"configured": twilio_active, "phone": Config.TWILIO_PHONE_NUMBER or None},
        "baileys": {
            "connected": state["connected"],
            "qr": state["qr"],
            "qr_image": generate_qr_data_url(state["qr"]) if state["qr"] else None,
            "pairing_code": state.get("pairing_code"),
            "message": state["message"],
            "is_running": state["qr"] is not None or state["connected"],
        },
        "any_connected": twilio_active or state["connected"],
    }


@app.get("/whatsapp-connect", response_class=HTMLResponse)
async def whatsapp_connect(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    user = await crud.get_user_by_id(db, user_id) if user_id else None
    if not user:
        return RedirectResponse(url="/")
    return HTMLResponse(content=_get_cached_page("templates/connect.html"))


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    user = await crud.get_user_by_id(db, user_id) if user_id else None
    if not user:
        return RedirectResponse(url="/")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return HTMLResponse(content=_get_cached_page("templates/admin.html"))

_CACHED_PAGES: dict[str, str] = {}

def _get_cached_page(path: str) -> str:
    if path not in _CACHED_PAGES:
        _CACHED_PAGES[path] = Path(path).read_text(encoding="utf-8")
    return _CACHED_PAGES[path]


@ app.on_event("startup")
async def _preload_pages():
    for p in ["templates/landingpage.html", "templates/about.html", "templates/contact.html",
              "templates/help.html", "templates/privacy.html", "templates/terms.html",
              "templates/dashboard.html", "templates/connect.html", "templates/admin.html",
              "templates/discover.html", "templates/business_setup.html",
              "templates/reset_password.html", "templates/reset_password_invalid.html"]:
        _get_cached_page(p)


@app.get("/about", response_class=HTMLResponse)
async def about_page():
    return HTMLResponse(content=_get_cached_page("templates/about.html"))


@app.get("/contact", response_class=HTMLResponse)
async def contact_page():
    return HTMLResponse(content=_get_cached_page("templates/contact.html"))


@app.get("/", response_class=HTMLResponse)
async def basepage(request: Request):
    return HTMLResponse(content=_get_cached_page("templates/landingpage.html"))


# @app.get("/terms", response_class=HTMLResponse)
# async def terms():
#     return HTMLResponse(content="""
#     <!doctype html>
#     <html lang="en">
#       <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Tell5 Terms</title></head>
#       <body style="font-family:Arial,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;line-height:1.6">
#         <h1>Terms of Service</h1>
#         <p>This is a placeholder Terms of Service page for Tell5. Replace it with your reviewed business terms before production launch.</p>
#         <p><a href="/">Back to Tell5</a></p>
#       </body>
#     </html>
#     """)


@app.get("/pipeline/status/{message_id}")
async def pipeline_status(message_id: str, db: AsyncSession = Depends(get_db)):
    from models import PipelineLog
    from sqlalchemy import select
    q = await db.execute(
        select(PipelineLog).where(PipelineLog.message_id == message_id)
    )
    log = q.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Pipeline log not found")
    return {
        "id": log.id,
        "message": log.message,
        "category": log.category,
        "success": log.success,
        "errors": log.errors,
        "final_reply": log.final_reply,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


@app.post("/pipeline/process")
@limiter.limit("20/minute")
async def trigger_pipeline(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    data = await request.json()
    message = str(data.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    from services.ai.pipeline import run_pipeline
    message_id = str(uuid.uuid4())
    result = await run_pipeline(message, message_id=message_id, db=db)

    await crud.create_pipeline_log(
        db,
        message=message,
        category=result.category,
        gemini_output=str(result.tier_outputs.get(1)),
        groq_output=str(result.tier_outputs.get(2)),
        mistral_output=str(result.tier_outputs.get(3)),
        final_reply=result.reply,
        errors="; ".join(result.errors) if result.errors else None,
        success=result.success,
        message_id=message_id,
    )
    await db.commit()

    return {
        "message_id": message_id,
        "category": result.category,
        "reply": result.reply,
        "success": result.success,
    }


@app.post("/api/chat/send")
@limiter.limit("20/minute")
async def chat_send(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    data = await request.json()
    message = str(data.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    import uuid
    message_id = str(uuid.uuid4())

    # ── Load business context (same as _process_incoming_message) ──
    merged_context = {}
    try:
        from crud import get_business_profile
        bp = await get_business_profile(db, user.id)
        if bp:
            merged_context["business_name"] = bp.business_name
            merged_context["services"] = bp.services or ""
            merged_context["price_range"] = bp.price_range or ""
            if bp.description:
                merged_context["description"] = bp.description
    except Exception as e:
        logger.warning("chat_send: failed to load business profile: %s", e)

    try:
        owner = await crud.get_user_by_id(db, user.id)
        if owner:
            merged_context["owner_name"] = f"{owner.first_name} {owner.last_name}".strip()
    except Exception as e:
        logger.warning("chat_send: failed to load owner name: %s", e)

    try:
        from crud import list_knowledge
        entries = await list_knowledge(db, user.id)
        if entries:
            merged_context["business_knowledge"] = [{"content": e.content, "category": e.category} for e in entries[:20]]
    except Exception as e:
        logger.warning("chat_send: failed to load knowledge: %s", e)

    merged_context["founder_persona"] = {
        "name": "Francis David",
        "role": "Founder & Developer of Tell5",
        "location": "Nnewi, Anambra State, Nigeria",
        "voice": "Warm but direct. Professional but not corporate. No robot speak.",
        "values": "Honesty over hype, simplicity over complexity, reliability over flash, growth through service.",
        "style": "Patient, knowledgeable, proud of what he's building, always improving.",
        "goal": "Every customer should feel like they're talking to the founder himself — someone who genuinely cares about their business success.",
        "background": "Developer and entrepreneur. Built Tell5 to solve real problems for African entrepreneurs. Hands-on from architecture to customer support. Mentors other developers. Believes small businesses deserve enterprise tools without enterprise pricing.",
    }

    # ── Pipeline processing with safety net ──
    from services.ai.pipeline import run_pipeline, PipelineResult
    pipeline_result = None
    try:
        pipeline_result = await run_pipeline(
            message, message_id=message_id, from_number=f"chat:{user.id}",
            user_id=user.id, context=merged_context or None, db=db,
        )
    except Exception as e:
        logger.error(f"chat_send: pipeline crashed: {e}", exc_info=True)

    if pipeline_result is None:
        pipeline_result = PipelineResult()
        pipeline_result.reply = None
        pipeline_result.category = "inquiry"
        pipeline_result.errors = ["Pipeline crashed"]
        pipeline_result.success = False

    ai_reply = pipeline_result.adk_reply or pipeline_result.reply
    if not ai_reply:
        ai_reply = "Thank you for your message. We'll get back to you shortly."

    await crud.create_pipeline_log(
        db,
        message=message,
        category=pipeline_result.category or "inquiry",
        gemini_output=str(pipeline_result.tier_outputs.get(1)),
        groq_output=str(pipeline_result.tier_outputs.get(2)),
        mistral_output=str(pipeline_result.tier_outputs.get(3)),
        final_reply=ai_reply,
        errors="; ".join(pipeline_result.errors) if pipeline_result.errors else None,
        success=pipeline_result.success,
        message_id=message_id,
    )

    conv = await crud.create_conversation(
        db,
        phone=f"chat:{user.id}",
        message=message,
        category=pipeline_result.category or "inquiry",
        user_id=user.id,
        channel="dashboard",
        ai_response=ai_reply,
    )
    await db.commit()

    return {
        "reply": ai_reply,
        "category": pipeline_result.category or "inquiry",
        "success": pipeline_result.success,
        "conv_id": conv.id,
    }


@app.post("/webhook/whatsapp/status")
async def whatsapp_status_webhook(request: Request):
    form = await request.form()
    logger.info(f"Delivery status update: {dict(form)}")
    return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")


@app.get("/api/business/profile")
async def get_my_business_profile(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    profile = await crud.get_business_profile(db, user.id)
    if not profile:
        return None
    return {
        "id": profile.id,
        "business_name": profile.business_name,
        "description": profile.description,
        "category": profile.category,
        "address": profile.address,
        "phone": profile.phone,
        "hours": profile.hours,
        "website": profile.website,
        "logo_url": profile.logo_url,
        "currency": profile.currency,
        "is_public": profile.is_public,
        "services": profile.services,
        "price_range": profile.price_range,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
    }


@app.post("/api/business/profile")
async def create_or_update_business_profile(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    data = await request.json()
    business_name = str(data.get("business_name", "")).strip()
    if not business_name:
        raise HTTPException(status_code=400, detail="Business name is required")

    existing = await crud.get_business_profile(db, user.id)
    if existing:
        existing.business_name = business_name
        existing.description = str(data.get("description", existing.description or "")) or None
        existing.category = str(data.get("category", existing.category or "")) or None
        existing.address = str(data.get("address", existing.address or "")) or None
        existing.phone = str(data.get("phone", existing.phone or "")) or None
        existing.hours = str(data.get("hours", existing.hours or "")) or None
        existing.website = str(data.get("website", existing.website or "")) or None
        existing.logo_url = str(data.get("logo_url", existing.logo_url or "")) or None
        if "is_public" in data:
            existing.is_public = bool(data["is_public"])
        existing.services = str(data.get("services", existing.services or "")) or None
        existing.price_range = str(data.get("price_range", existing.price_range or "")) or None
        await db.flush()
        await db.commit()
        return {"id": existing.id, "business_name": existing.business_name, "updated": True}

    profile = await crud.create_business_profile(
        db,
        user_id=user.id,
        business_name=business_name,
        description=str(data.get("description", "")).strip() or None,
        category=str(data.get("category", "")).strip() or None,
        address=str(data.get("address", "")).strip() or None,
        phone=str(data.get("phone", "")).strip() or None,
        hours=str(data.get("hours", "")).strip() or None,
        website=str(data.get("website", "")).strip() or None,
        logo_url=str(data.get("logo_url", "")).strip() or None,
        is_public=bool(data.get("is_public", True)),
        services=str(data.get("services", "")).strip() or None,
        price_range=str(data.get("price_range", "")).strip() or None,
    )
    await db.commit()
    return {"id": profile.id, "business_name": profile.business_name, "created": True}


@app.get("/api/business/products")
async def list_my_products(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    profile = await crud.get_business_profile(db, user.id)
    if not profile:
        return []
    products = await crud.list_products(db, profile.id)
    return [{
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "price": p.price,
        "currency": p.currency,
        "is_available": p.is_available,
    } for p in products]


@app.post("/api/business/products")
async def create_product(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    profile = await crud.get_business_profile(db, user.id)
    if not profile:
        raise HTTPException(status_code=400, detail="Create a business profile first")
    data = await request.json()
    name = str(data.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Product name is required")
    product = await crud.create_product(
        db,
        business_id=profile.id,
        name=name,
        description=str(data.get("description", "")).strip() or None,
        price=float(data["price"]) if data.get("price") else None,
        currency=str(data.get("currency", "")).strip() or "NGN",
    )
    await db.commit()
    return {"id": product.id, "name": product.name, "created": True}


@app.get("/api/business/{profile_id}/public")
async def get_public_business_profile(profile_id: int, db: AsyncSession = Depends(get_db)):
    from models import BusinessProfile
    from sqlalchemy import select
    q = await db.execute(select(BusinessProfile).where(BusinessProfile.id == profile_id))
    profile = q.scalar_one_or_none()
    if not profile or not profile.is_public:
        raise HTTPException(status_code=404, detail="Business profile not found or not public")
    products = await crud.list_products(db, profile.id)
    return {
        "id": profile.id,
        "business_name": profile.business_name,
        "description": profile.description,
        "category": profile.category,
        "address": profile.address,
        "phone": profile.phone,
        "hours": profile.hours,
        "website": profile.website,
        "currency": profile.currency,
        "is_public": profile.is_public,
        "products": [{
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price": p.price,
            "currency": p.currency,
        } for p in products],
    }


@app.get("/help", response_class=HTMLResponse)
async def help_page():
    return HTMLResponse(content=_get_cached_page("templates/help.html"))


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page():
    return HTMLResponse(content=_get_cached_page("templates/privacy.html"))


@app.get("/terms", response_class=HTMLResponse)
async def terms_page():
    return HTMLResponse(content=_get_cached_page("templates/terms.html"))


@app.get("/business-profile", response_class=HTMLResponse)
async def business_profile_setup(user=Depends(get_current_user)):
    return HTMLResponse(content=_get_cached_page("templates/business_setup.html"))


@app.get("/business-profile/{profile_id}", response_class=HTMLResponse)
async def business_profile_page(profile_id: int, db: AsyncSession = Depends(get_db)):
    from models import BusinessProfile
    from sqlalchemy import select
    q = await db.execute(select(BusinessProfile).where(BusinessProfile.id == profile_id))
    profile = q.scalar_one_or_none()
    if not profile:
        return HTMLResponse(content="<h1>Profile not found</h1>", status_code=404)
    return HTMLResponse(content=_get_cached_page("templates/business_profile.html"))


@app.get("/discover", response_class=HTMLResponse)
async def discover_page():
    return HTMLResponse(content=_get_cached_page("templates/discover.html"))


# ── Reply Templates ─────────────────────────────────────────────────

@app.get("/api/reply-templates")
async def list_templates(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    templates = await crud.list_reply_templates(db, user.id)
    return [{"id": t.id, "title": t.title, "body": t.body, "created_at": t.created_at.isoformat() if t.created_at else None} for t in templates]


@app.post("/api/reply-templates")
async def create_template(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    data = await request.json()
    title = str(data.get("title", "")).strip()
    body = str(data.get("body", "")).strip()
    if not title or not body:
        raise HTTPException(status_code=400, detail="Title and body are required")
    t = await crud.create_reply_template(db, user.id, title, body)
    await db.commit()
    return {"id": t.id, "title": t.title, "body": t.body, "created": True}


@app.put("/api/reply-templates/{template_id}")
async def update_template(template_id: int, request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    data = await request.json()
    title = str(data.get("title", "")).strip()
    body = str(data.get("body", "")).strip()
    if not title or not body:
        raise HTTPException(status_code=400, detail="Title and body are required")
    ok = await crud.update_reply_template(db, template_id, user.id, title, body)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.commit()
    return {"ok": True}


@app.delete("/api/reply-templates/{template_id}")
async def delete_template(template_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    ok = await crud.delete_reply_template(db, template_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.commit()
    return {"ok": True}


# ── Customer Profiles ────────────────────────────────────────────────

@app.get("/api/customers")
async def list_customers(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    customers = await crud.list_customers(db, user.id)
    return [{
        "id": c.id, "phone": c.phone, "name": c.name, "notes": c.notes,
        "message_count": c.message_count,
        "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
    } for c in customers]


@app.patch("/api/customers/{customer_id}")
async def update_customer(customer_id: int, request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    data = await request.json()
    notes = str(data.get("notes", "")).strip()
    ok = await crud.update_customer_notes(db, customer_id, user.id, notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Customer not found")
    await db.commit()
    return {"ok": True}


@app.delete("/api/business/products/{product_id}")
async def delete_product_route(product_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    ok = await crud.delete_product(db, product_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    await db.commit()
    return {"ok": True}


@app.get("/api/business/search")
async def search_businesses_api(q: str = "", db: AsyncSession = Depends(get_db)):
    if not q.strip():
        return []
    results = await crud.search_businesses(db, q.strip(), limit=5)
    return results


@app.get("/api/business/discover")
async def discover_businesses(db: AsyncSession = Depends(get_db)):
    profiles = await crud.get_public_business_profiles(db)
    return [{
        "id": p.id,
        "business_name": p.business_name,
        "description": p.description,
        "category": p.category,
    } for p in profiles]


@app.post("/api/archive/run")
async def trigger_archive(db: AsyncSession = Depends(get_db), user=Depends(get_admin_user)):
    from services.archival import run_weekly_archive
    result = await run_weekly_archive(db)
    return result


@app.post("/api/cron/cleanup")
@app.get("/api/cron/cleanup")
async def cron_cleanup(db: AsyncSession = Depends(get_db), _=Depends(verify_cron)):
    """Called by Render Cron Job weekly — cleans old conversations and runs archive"""
    from datetime import timedelta, timezone, datetime
    from sqlalchemy import text
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    await db.execute(text("DELETE FROM conversations WHERE timestamp < :cutoff"), {"cutoff": cutoff})
    await db.commit()
    logger.info("Cron cleanup: deleted conversations older than 7 days")
    from services.archival import run_weekly_archive
    archive = await run_weekly_archive(db)
    return {"ok": True, "deleted_old_conversations": True, "archive": archive}


@app.get("/api/discovery/status")
async def discovery_engine_status(user=Depends(get_admin_user)):
    from services.ai.discovery_engine import get_client
    client = get_client()
    if not client or not client.configured:
        return {"configured": False, "ready": False, "data_store": None}
    return {
        "configured": True,
        "ready": True,
        "project": Config.GOOGLE_CLOUD_PROJECT,
        "location": Config.AGENT_BUILDER_LOCATION,
        "data_store": Config.AGENT_BUILDER_DATA_STORE,
    }


@app.post("/api/discovery/create-datastore")
async def create_discovery_datastore(user=Depends(get_admin_user)):
    from services.ai.discovery_engine import get_client
    client = get_client()
    if not client:
        raise HTTPException(status_code=501, detail="Discovery Engine not configured")
    store_id = Config.AGENT_BUILDER_DATA_STORE or "tell5-knowledge-base"
    ok = await client.ensure_data_store(store_id, "Tell5 Knowledge Base")
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to create data store")
    return {"ok": True, "data_store_id": store_id}


@app.post("/api/discovery/sync")
async def sync_to_discovery(db: AsyncSession = Depends(get_db), user=Depends(get_admin_user)):
    from services.ai.discovery_engine import get_client, sync_business_profile_to_discovery
    client = get_client()
    if not client or not client.configured:
        raise HTTPException(status_code=501, detail="Discovery Engine not configured")
    from sqlalchemy import select
    from models import BusinessProfile, Product
    profiles = (await db.execute(select(BusinessProfile))).scalars().all()
    synced = 0
    for bp in profiles:
        products = (await db.execute(select(Product).where(Product.business_id == bp.id))).scalars().all()
        prod_list = [{"id": p.id, "name": p.name, "price": p.price, "currency": p.currency} for p in products]
        ok = await sync_business_profile_to_discovery(
            profile_id=bp.id,
            business_name=bp.business_name,
            description=bp.description,
            category=bp.category,
            address=bp.address,
            products=prod_list,
        )
        if ok:
            synced += 1
    return {"ok": True, "synced": synced, "total": len(profiles)}


@app.get("/api/adk/status")
async def adk_status():
    from services.ai.adk_agent import is_configured
    return {"adk_configured": is_configured(), "gemini_key_set": bool(Config.GEMINI_API_KEY)}


@app.post("/api/adk/chat")
async def adk_chat(request: Request):
    from services.ai.adk_agent import ask_agent, is_configured
    if not is_configured():
        raise HTTPException(status_code=501, detail="ADK agent not configured")
    body = await request.json()
    message = body.get("message", "")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    user_id = body.get("user_id", "anonymous")
    reply = await ask_agent(message, user_id=user_id)
    return {"reply": reply}


# ── Personality Q&A ──

@app.get("/api/personality/qa")
async def get_personality_qa(db: AsyncSession = Depends(get_db), user=Depends(get_admin_user)):
    return await crud.list_personality_qa(db)


@app.post("/api/personality/qa")
async def add_personality_qa(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_admin_user)):
    body = await request.json()
    question = body.get("question", "").strip()
    answer = body.get("answer", "").strip()
    mode = body.get("mode", "business")
    if not question or not answer:
        raise HTTPException(status_code=400, detail="question and answer are required")
    if mode not in ("business", "personal"):
        raise HTTPException(status_code=400, detail="mode must be business or personal")
    qa = await crud.add_personality_qa(db, question, answer, mode)
    await db.commit()
    return {"id": qa.id, "question": qa.question, "answer": qa.answer, "mode": qa.mode}


@app.delete("/api/personality/qa/{qa_id}")
async def delete_personality_qa(qa_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_admin_user)):
    ok = await crud.delete_personality_qa(db, qa_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Q&A not found")
    await db.commit()
    return {"ok": True}


@app.post("/api/personality/reload")
async def reload_personality(db: AsyncSession = Depends(get_db), user=Depends(get_admin_user)):
    from services.ai.personality import load_qa_cache
    await load_qa_cache(db)
    return {"ok": True}


# ── Knowledge Base ──────────────────────────────────────────────────────

@app.get("/api/knowledge")
async def list_knowledge(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    entries = await crud.list_knowledge(db, user.id)
    return [{"id": e.id, "content": e.content, "category": e.category, "created_at": e.created_at.isoformat() if e.created_at else None} for e in entries]


@app.post("/api/knowledge")
async def add_knowledge(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    data = await request.json()
    content = str(data.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")
    category = str(data.get("category", "")).strip() or None
    entry = await crud.add_knowledge(db, user.id, content, category)
    await db.commit()
    return {"id": entry.id, "content": entry.content, "category": entry.category, "created_at": entry.created_at.isoformat() if entry.created_at else None}


@app.delete("/api/knowledge/{entry_id}")
async def delete_knowledge(entry_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    ok = await crud.delete_knowledge(db, entry_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Entry not found")
    await db.commit()
    return {"ok": True}


# ── Update Conversation Category ────────────────────────────────────────

@app.patch("/api/conversations/{conv_id}/category")
async def update_conversation_category(conv_id: int, request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    data = await request.json()
    new_category = str(data.get("category", "")).strip().lower()
    if new_category not in ("order", "inquiry", "complaint", "feedback", "pending"):
        raise HTTPException(status_code=400, detail="Invalid category")
    conv = await crud.get_conversation(db, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")
    updated = await crud.update_conversation_category(db, conv_id, new_category)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update")
    await db.commit()
    return {"ok": True, "category": new_category}


@app.get("/api/export/csv")
async def export_csv(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    convs = await crud.list_conversations(db, user.id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Phone", "Message", "Category", "Channel", "AI Response", "Timestamp"])
    for c in convs:
        writer.writerow([c.id, c.phone, c.message, c.category, c.channel, c.ai_response or "", str(c.timestamp or "")])
    filename = f"tell5-conversations-{user.id}-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/contact")
async def contact_form(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    name = (body.get("name") or "").strip()
    email_addr = (body.get("email") or "").strip()
    subject = (body.get("subject") or "").strip()
    message = (body.get("message") or "").strip()
    if not name or not email_addr or not subject or not message:
        raise HTTPException(status_code=400, detail="All fields are required")
    from models import ContactMessage
    db.add(ContactMessage(name=name, email=email_addr, subject=subject, message=message))
    await db.commit()
    logger.info("Contact form submission from %s (%s) — subject: %s", name, email_addr, subject)
    return {"ok": True}


# @app.get("/privacy", response_class=HTMLResponse)
# async def privacy():
#     return HTMLResponse(content="""
#     <!doctype html>
#     <html lang="en">
#       <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Tell5 Privacy</title></head>
#       <body style="font-family:Arial,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;line-height:1.6">
#         <h1>Privacy Policy</h1>
#         <p>This is a placeholder Privacy Policy page for Tell5. Replace it with your reviewed privacy policy before production launch.</p>
#         <p><a href="/">Back to Tell5</a></p>
#       </body>
#     </html>
#     """)

