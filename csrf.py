import secrets
import hashlib
import hmac
import json
import time
from typing import Optional
from config import Config


CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TOKEN_LENGTH = 32
CSRF_TOKEN_EXPIRY = 60 * 60 * 24  # 24 hours


def generate_csrf_token() -> str:
    """Generate a new CSRF token"""
    return secrets.token_urlsafe(CSRF_TOKEN_LENGTH)


def create_csrf_token_with_expiry() -> tuple[str, str]:
    """Create a CSRF token with expiry and return token and signature

    Returns:
        Tuple of (token, signed_token)
    """
    token = generate_csrf_token()
    expiry = int(time.time()) + CSRF_TOKEN_EXPIRY

    # Create signed token with expiry
    payload = f"{token}:{expiry}"
    signature = hmac.new(
        Config.SESSION_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    signed_token = f"{payload}:{signature}"
    return token, signed_token


def verify_csrf_token(token: str, signed_token: str) -> bool:
    """Verify CSRF token signature and expiry

    Args:
        token: The token from the form/request
        signed_token: The signed token from cookie

    Returns:
        True if valid, False otherwise
    """
    try:
        parts = signed_token.split(":")
        if len(parts) != 3:
            return False

        stored_token, expiry_str, signature = parts

        # Verify token matches
        if not hmac.compare_digest(token, stored_token):
            return False

        # Check expiry
        expiry = int(expiry_str)
        if int(time.time()) > expiry:
            return False

        # Verify signature
        payload = f"{stored_token}:{expiry_str}"
        expected_signature = hmac.new(
            Config.SESSION_SECRET.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature, expected_signature)

    except (ValueError, IndexError, AttributeError):
        return False


def extract_csrf_token_from_request(form_data: dict) -> Optional[str]:
    """Extract CSRF token from form data or headers

    Args:
        form_data: Request form data dictionary

    Returns:
        CSRF token string or None
    """
    # Check form data first
    token = form_data.get("csrf_token")
    if token:
        return str(token).strip()

    return None


def extract_csrf_token_from_headers(headers: dict) -> Optional[str]:
    """Extract CSRF token from request headers

    Args:
        headers: Request headers dictionary

    Returns:
        CSRF token string or None
    """
    token = headers.get(CSRF_HEADER_NAME) or headers.get("x-csrf-token")
    if token:
        return str(token).strip()

    return None
