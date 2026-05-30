from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import Response, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from db import engine, Base, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from config import Config
import crud
from ai import ai_configured, analyze_customer_message, draft_reply
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
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS user_id INTEGER"))
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


@app.post("/webhook/whatsapp")
@limiter.limit("100/minute")
async def whatsapp_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    # Get signature for validation
    signature = request.headers.get("X-Twilio-Signature", "")

    # Get form data
    form = await request.form()
    form_dict = dict(form)

    # Validate Twilio request
    request_url = str(request.url)
    if not validate_twilio_request(request_url, form_dict, signature):
        logger.warning(f"Invalid Twilio signature from {form.get('From')}")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    from_number: Optional[str] = form.get("From")
    to_number: Optional[str] = form.get("To")
    body: Optional[str] = form.get("Body")

    if not from_number or not body:
        raise HTTPException(status_code=400, detail="Missing From or Body")

    logger.info(f"Received message from {from_number} to {to_number}: {body}")

    target_user_id = None
    if to_number:
        normalized_to = str(to_number).replace("whatsapp:", "").replace(" ", "").strip()
        target_user = await crud.get_user_by_phone(db, normalized_to)
        if target_user:
            target_user_id = target_user.id

    phone = from_number
    ai_result = await analyze_customer_message(body)
    category = ai_result["category"] if ai_result else categorize_message(body)
    conv = await crud.create_conversation(db, phone=phone, message=body, category=category, user_id=target_user_id)

    reply = ""
    if category == "order":
        item, qty = parse_order(body)
        order = await crud.create_order(db, phone=phone, item=item, quantity=qty, user_id=target_user_id)
        await crud.create_notification(db, ntype="new_order", payload=f"order:{order.id}")
        reply = ai_result["reply"] if ai_result else "We've received your order. We'll confirm shortly."
        logger.info(f"Order created: {order.id} from {phone}")
    elif category == "inquiry":
        reply = ai_result["reply"] if ai_result else "Thanks for reaching out. A team member will respond soon."
    elif category == "complaint":
        reply = ai_result["reply"] if ai_result else "Sorry about that. We've escalated your complaint."
    else:
        reply = ai_result["reply"] if ai_result else "Thanks for your message. We'll get back to you."

    await db.commit()

    # Send auto-reply via Twilio if client is available and a Twilio sender is configured
    if twilio_client and Config.TWILIO_PHONE_NUMBER:
        try:
            twilio_client.messages.create(
                from_=Config.TWILIO_PHONE_NUMBER,
                body=reply,
                to=from_number
            )
            logger.info(f"Auto-reply sent to {from_number}")
        except Exception as e:
            logger.error(f"Failed to send Twilio message: {e}")

    # Respond with empty TwiML (Twilio messages sent via API)
    twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    return Response(content=twiml, media_type="application/xml")


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
    return {
        "stats": s,
        "total_users": len(users),
        "total_conversations": len(convs),
        "total_orders": len(orders),
        "ai_enabled": ai_configured(),
        "twilio_configured": is_twilio_enabled(),
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
    return JSONResponse(content=[{
        "id": c.id,
        "phone": c.phone,
        "message": c.message,
        "category": c.category,
        "timestamp": c.timestamp.isoformat() if c.timestamp else None
    } for c in convs])


@app.get("/api/orders")
async def get_orders(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
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
    if is_twilio_enabled():
        raise HTTPException(status_code=404, detail="Twilio is configured")
    state = get_whatsapp_qr_state()
    if state["connected"]:
        return {"connected": True, "message": "WhatsApp is connected."}
    if not state["qr"]:
        return {"connected": False, "qr_image": None, "message": state["message"]}
    return {
        "connected": False,
        "qr_image": generate_qr_data_url(state["qr"]),
        "message": state["message"],
    }


@app.get("/whatsapp-connect", response_class=HTMLResponse)
async def whatsapp_connect(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    user = await crud.get_user_by_id(db, user_id) if user_id else None
    if not user:
        return RedirectResponse(url="/")
    if is_twilio_enabled():
        return RedirectResponse(url="/dashboard")
    if is_baileys_connected():
        return RedirectResponse(url="/dashboard")
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

