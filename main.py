from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import Response, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from db import engine, Base, get_db
from sqlalchemy.ext.asyncio import AsyncSession
import crud
from auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    cookie_secure,
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)
import re
import os
import logging
from pathlib import Path
from typing import Optional
from twilio.rest import Client
from twilio.request_validator import RequestValidator
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Twilio configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "whatsapp:+1234567890")

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN else None
validator = RequestValidator(TWILIO_AUTH_TOKEN) if TWILIO_AUTH_TOKEN else None

app = FastAPI(title="Tell5 - WhatsApp Workflow Agent")
templates = Jinja2Templates(directory="templates")

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except RuntimeError:
    logger.warning("static directory not found, skipping mount")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
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
    }


def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


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
    logger.info("Database tables initialized")


def validate_twilio_request(request_url: str, post_data: dict, signature: str) -> bool:
    """Validate that request came from Twilio"""
    if not validator:
        logger.warning("Twilio Auth Token not configured, skipping signature validation")
        return True
    return validator.validate(request_url, post_data, signature)


@app.post("/webhook/whatsapp")
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
    body: Optional[str] = form.get("Body")

    if not from_number or not body:
        raise HTTPException(status_code=400, detail="Missing From or Body")

    logger.info(f"Received message from {from_number}: {body}")

    phone = from_number
    category = categorize_message(body)
    conv = await crud.create_conversation(db, phone=phone, message=body, category=category)

    reply = ""
    if category == "order":
        item, qty = parse_order(body)
        order = await crud.create_order(db, phone=phone, item=item, quantity=qty)
        await crud.create_notification(db, ntype="new_order", payload=f"order:{order.id}")
        reply = "We've received your order. We'll confirm shortly."
        logger.info(f"Order created: {order.id} from {phone}")
    elif category == "inquiry":
        reply = "Thanks for reaching out. A team member will respond soon."
    elif category == "complaint":
        reply = "Sorry about that. We've escalated your complaint."
    else:
        reply = "Thanks for your message. We'll get back to you."

    await db.commit()

    # Send auto-reply via Twilio if client is available
    if twilio_client:
        try:
            twilio_client.messages.create(
                from_=TWILIO_PHONE_NUMBER,
                body=reply,
                to=from_number
            )
            logger.info(f"Auto-reply sent to {from_number}")
        except Exception as e:
            logger.error(f"Failed to send Twilio message: {e}")

    # Respond with empty TwiML (Twilio messages sent via API)
    twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    return Response(content=twiml, media_type="application/xml")


@app.post("/api/auth/signup")
async def signup(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    first_name = str(data.get("first_name", "")).strip()
    last_name = str(data.get("last_name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not first_name or not last_name or not phone or not email or not password:
        raise HTTPException(status_code=400, detail="Please fill in all fields.")
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    existing = await crud.get_user_by_email(db, email)
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = await crud.create_user(
        db,
        email=email,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        password_hash=hash_password(password),
    )
    await db.commit()

    response = JSONResponse(content={"user": public_user(user)})
    set_auth_cookie(response, user.id)
    return response


@app.post("/api/auth/login")
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


@app.get("/api/conversations")
async def get_conversations(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    convs = await crud.list_conversations(db)
    return JSONResponse(content=[{
        "id": c.id,
        "phone": c.phone,
        "message": c.message,
        "category": c.category,
        "timestamp": c.timestamp.isoformat() if c.timestamp else None
    } for c in convs])


@app.get("/api/orders")
async def get_orders(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    orders = await crud.list_orders(db)
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
    s = await crud.stats(db)
    return s


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    if not user_id or not await crud.get_user_by_id(db, user_id):
        return RedirectResponse(url="/")
    dashboard_html = Path("templates/dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(content=dashboard_html)

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

