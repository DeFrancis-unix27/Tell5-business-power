import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

SESSION_COOKIE_NAME = "tell5_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
PASSWORD_ITERATIONS = 260_000


def _session_secret() -> bytes:
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        secret = os.getenv("TWILIO_AUTH_TOKEN") or "tell5-local-dev-secret"
    return secret.encode("utf-8")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _b64decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(_b64encode(digest), expected)
    except (TypeError, ValueError):
        return False


def create_session_token(user_id: int) -> str:
    payload: dict[str, Any] = {
        "sub": user_id,
        "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS,
        "nonce": secrets.token_urlsafe(12),
    }
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_session_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64encode(signature)}"


def verify_session_token(token: str) -> int | None:
    try:
        payload_b64, signature_b64 = token.split(".", 1)
        expected_signature = hmac.new(_session_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64encode(expected_signature), signature_b64):
            return None
        payload = json.loads(_b64decode(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def cookie_secure() -> bool:
    return os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}
