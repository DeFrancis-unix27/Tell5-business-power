import os
import sentry_sdk

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import Response, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from db import engine, Base, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from config import Config
import crud
from ai import ai_configured, analyze_customer_message, draft_reply, ai_categorize_message
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
    generate_csrf_token,
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
import qrcode
from twilio.rest import Client
from twilio.request_validator import RequestValidator
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
if Config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=Config.SENTRY_DSN,
        environment=Config.ENVIRONMENT,
        traces_sample_rate=0.25,
        send_default_pii=False,
    )

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Tell5 - WhatsApp Workflow Agent")
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


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    """CSRF protection middleware for form submissions"""
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
    if any(w in t for w in ["order", "buy", "purchase"]):
        return "order"
    if any(w in t for w in ["price", "how", "info", "details", "when"]):
        return "inquiry"
    if any(w in t for w in ["not", "complain", "complaint", "issue", "bad", "wrong"]):
        return "complaint"
    if any(w in t for w in ["thanks", "thank", "love", "good", "great", "feedback"]):
        return "feedback"
    return "inquiry"


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
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id INTEGER"))
        await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS channel VARCHAR(50) DEFAULT 'whatsapp'"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS user_id INTEGER"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS channel VARCHAR(50) DEFAULT 'whatsapp'"))
        admin_email = (Config.ADMIN_EMAIL or "").strip().lower()
        if admin_email:
            await conn.execute(text("UPDATE users SET is_admin = TRUE WHERE lower(email) = :email"), {"email": admin_email})
        await conn.execute(text("""
            UPDATE users
            SET is_admin = TRUE
            WHERE id = (SELECT id FROM users ORDER BY id ASC LIMIT 1)
            AND NOT EXISTS (SELECT 1 FROM users WHERE is_admin = TRUE)
        """))
    logger.info("Database tables initialized")


def validate_twilio_request(request_url: str, post_data: dict, signature: str) -> bool:
    """Validate that request came from Twilio"""
    return validator.validate(request_url, post_data, signature)


async def _process_incoming_message(
    db: AsyncSession,
    from_number: str,
    body: str,
    to_number: str | None = None,
    channel: str = "whatsapp",
) -> dict:
    """Shared message processing for both Twilio and Baileys"""
    target_user_id = None
    if to_number:
        normalized_to = str(to_number).replace("whatsapp:", "").replace(" ", "").strip()
        target_user = await crud.get_user_by_phone(db, normalized_to)
        if target_user:
            target_user_id = target_user.id

    phone = from_number

    from services.ai.pipeline import run_pipeline
    import uuid
    message_id = str(uuid.uuid4())
    pipeline_result = await run_pipeline(body, message_id=message_id)
    category = pipeline_result.category or categorize_message(body)
    ai_reply = pipeline_result.reply

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

    ai_result = {"category": category, "reply": ai_reply} if ai_reply else None
    conv = await crud.create_conversation(db, phone=phone, message=body, category=category, user_id=target_user_id)

    reply = ""
    if category == "order":
        item, qty = parse_order(body)
        order = await crud.create_order(db, phone=phone, item=item, quantity=qty, user_id=target_user_id)
        await crud.create_notification(db, ntype="new_order", payload=f"order:{order.id}")
        reply = ai_result["reply"] if ai_result else "We've received your order. We'll confirm shortly."
    elif category == "inquiry":
        reply = ai_result["reply"] if ai_result else "Thanks for reaching out. A team member will respond soon."
    elif category == "complaint":
        reply = ai_result["reply"] if ai_result else "Sorry about that. We've escalated your complaint."
    else:
        reply = ai_result["reply"] if ai_result else "Thanks for your message. We'll get back to you."

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
async def baileys_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receives messages forwarded from the Baileys WhatsApp bot"""
    data = await request.json()
    from_number = str(data.get("from", "")).strip()
    body = str(data.get("body", "")).strip()

    if not from_number or not body:
        raise HTTPException(status_code=400, detail="Missing from or body")

    logger.info(f"Baileys message from {from_number}: {body[:80]}")

    result = await _process_incoming_message(db, from_number, body, channel="baileys")

    return {"reply": result["reply"], "to": from_number, "category": result["category"]}


@app.get("/api/baileys/status")
async def baileys_status():
    """Check if the Baileys bot is running and connected"""
    bot_port = os.getenv("BOT_PORT", "3001")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"http://127.0.0.1:{bot_port}/health")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {"ok": False, "connected": False}


@app.get("/api/pipeline/metrics")
async def pipeline_metrics():
    """Returns pipeline performance metrics for monitoring"""
    from services.ai.metrics import metrics
    return metrics.snapshot()


@app.get("/api/pipeline/circuit-breaker")
async def circuit_breaker_status():
    """Returns circuit breaker state for each provider"""
    from services.ai.circuit_breaker import circuit_breaker
    import time
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
    token, _ = create_csrf_token_with_expiry()
    return {
        "csrf_token": token,
        "header_name": CSRF_HEADER_NAME,
    }


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


@app.get("/api/admin/summary")
async def admin_summary(db: AsyncSession = Depends(get_db), user=Depends(get_admin_user)):
    convs = await crud.list_conversations(db)
    orders = await crud.list_orders(db)
    users = await crud.list_users(db)
    s = await crud.stats(db)
    from services.ai.groq_client import groq_configured
    from services.ai.mistral_client import mistral_configured
    from models import PipelineLog, BusinessProfile
    from sqlalchemy import select, func
    pl_q = await db.execute(select(func.count(PipelineLog.id)))
    pipeline_count = pl_q.scalar() or 0
    bp_q = await db.execute(select(func.count(BusinessProfile.id)))
    biz_count = bp_q.scalar() or 0
    return {
        "stats": s,
        "total_users": len(users),
        "total_conversations": len(convs),
        "total_orders": len(orders),
        "ai_enabled": ai_configured(),
        "groq_enabled": groq_configured(),
        "mistral_enabled": mistral_configured(),
        "twilio_configured": is_twilio_enabled(),
        "pipeline_runs": pipeline_count,
        "business_profiles": biz_count,
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
    convs = await crud.list_conversations(db, user.id)
    if not convs and user.is_admin:
        convs = await crud.list_conversations(db, None)
    return JSONResponse(content=[{
        "id": c.id,
        "phone": c.phone,
        "message": c.message,
        "category": c.category,
        "channel": c.channel,
        "timestamp": c.timestamp.isoformat() if c.timestamp else None
    } for c in convs])


@app.get("/api/orders")
async def get_orders(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    orders = await crud.list_orders(db, user.id)
    if not orders and user.is_admin:
        orders = await crud.list_orders(db, None)
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
    s = await crud.stats(db, user.id)
    return s


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    if not user_id or not await crud.get_user_by_id(db, user_id):
        return RedirectResponse(url="/")
    if not is_twilio_enabled() and not is_baileys_connected():
        return RedirectResponse(url="/whatsapp-connect")
    dashboard_html = Path("templates/dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(content=dashboard_html)


@app.get("/api/whatsapp/qr")
async def whatsapp_qr():
    """Returns status of both WhatsApp channels (Twilio + Baileys)"""
    twilio_active = bool(Config.TWILIO_ACCOUNT_SID and Config.TWILIO_AUTH_TOKEN)
    state = get_whatsapp_qr_state()
    return {
        "twilio": {"configured": twilio_active, "phone": Config.TWILIO_PHONE_NUMBER or None},
        "baileys": {
            "connected": state["connected"],
            "qr": state["qr"],
            "qr_image": generate_qr_data_url(state["qr"]) if state["qr"] else None,
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
    connect_html = Path("templates/connect.html").read_text(encoding="utf-8")
    return HTMLResponse(content=connect_html)


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    user = await crud.get_user_by_id(db, user_id) if user_id else None
    if not user:
        return RedirectResponse(url="/")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    admin_html = Path("templates/admin.html").read_text(encoding="utf-8")
    return HTMLResponse(content=admin_html)

@app.get("/", response_class=HTMLResponse)
async def basepage(request: Request):
    landingpage_html = Path("templates/landingpage.html").read_text(encoding="utf-8")
    return HTMLResponse(content=landingpage_html)


@app.get("/terms", response_class=HTMLResponse)
async def terms():
    return HTMLResponse(content="""
    <!doctype html>
    <html lang="en">
      <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Tell5 Terms</title></head>
      <body style="font-family:Arial,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;line-height:1.6">
        <h1>Terms of Service</h1>
        <p>This is a placeholder Terms of Service page for Tell5. Replace it with your reviewed business terms before production launch.</p>
        <p><a href="/">Back to Tell5</a></p>
      </body>
    </html>
    """)


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
async def trigger_pipeline(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    message = str(data.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    from services.ai.pipeline import run_pipeline
    message_id = str(uuid.uuid4())
    result = await run_pipeline(message, message_id=message_id)

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

    from services.ai.pipeline import run_pipeline
    import uuid
    message_id = str(uuid.uuid4())
    result = await run_pipeline(message, message_id=message_id)

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

    conv = await crud.create_conversation(
        db,
        phone=f"chat:{user.id}",
        message=message,
        category=result.category or "inquiry",
        user_id=user.id,
        channel="dashboard",
    )
    await db.commit()

    return {
        "reply": result.reply,
        "category": result.category,
        "success": result.success,
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
        "currency": profile.currency,
        "is_public": profile.is_public,
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
        if "is_public" in data:
            existing.is_public = bool(data["is_public"])
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
        is_public=bool(data.get("is_public", True)),
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


@app.get("/business-profile/{profile_id}", response_class=HTMLResponse)
async def business_profile_page(profile_id: int, db: AsyncSession = Depends(get_db)):
    from models import BusinessProfile
    from sqlalchemy import select
    q = await db.execute(select(BusinessProfile).where(BusinessProfile.id == profile_id))
    profile = q.scalar_one_or_none()
    if not profile:
        return HTMLResponse(content="<h1>Profile not found</h1>", status_code=404)
    html = Path("templates/business_profile.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/discover", response_class=HTMLResponse)
async def discover_page():
    html = Path("templates/discover.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


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


@app.get("/api/channels")
async def list_channels():
    from services.channels.base import router
    return {"channels": router.available_channels()}


@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return HTMLResponse(content="""
    <!doctype html>
    <html lang="en">
      <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Tell5 Privacy</title></head>
      <body style="font-family:Arial,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;line-height:1.6">
        <h1>Privacy Policy</h1>
        <p>This is a placeholder Privacy Policy page for Tell5. Replace it with your reviewed privacy policy before production launch.</p>
        <p><a href="/">Back to Tell5</a></p>
      </body>
    </html>
    """)

