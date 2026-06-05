import json
import os
import tempfile
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def _materialize_google_credentials_json() -> None:
    """Support hosts that store the service-account JSON as an env secret."""
    raw_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
    existing_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

    if not raw_json or existing_path:
        return

    try:
        json.loads(raw_json)
    except json.JSONDecodeError:
        return

    path = os.path.join(tempfile.gettempdir(), "tell5-google-credentials.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path


_materialize_google_credentials_json()


class Config:
    """Application configuration with validation."""

    # Required in production
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "").strip()
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "").strip()

    # AI API Keys
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", "").strip() or None
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview").strip()
    GEMINI_FALLBACK_MODEL: str = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite").strip()
    GROQ_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY", "").strip() or None
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    MISTRAL_API_KEY: Optional[str] = os.getenv("MISTRAL_API_KEY", "").strip() or None
    MISTRAL_MODEL: str = os.getenv("MISTRAL_MODEL", "mistral-large-latest").strip()
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY", "").strip() or None
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free").strip()
    SENTRY_DSN: Optional[str] = os.getenv("SENTRY_DSN", "").strip() or None
    ADMIN_EMAIL: Optional[str] = os.getenv("ADMIN_EMAIL", "").strip() or None
    MDB_MCP_CONNECTION_STRING: Optional[str] = os.getenv("MDB_MCP_CONNECTION_STRING", "").strip() or None
    MDB_MCP_READ_ONLY: bool = os.getenv("MDB_MCP_READ_ONLY", "false").lower() in {"1", "true", "yes"}
    MDB_MCP_DB_NAME: str = os.getenv("MDB_MCP_DB_NAME", "tell5").strip()

    # Google OAuth
    GOOGLE_OAUTH_CLIENT_ID: Optional[str] = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip() or None
    GOOGLE_OAUTH_CLIENT_SECRET: Optional[str] = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip() or None
    OAUTH_REDIRECT_URI: str = os.getenv("OAUTH_REDIRECT_URI", "/api/auth/google/callback").strip()

    # Google Cloud Agent Builder / Discovery Engine
    GOOGLE_APPLICATION_CREDENTIALS_JSON: Optional[str] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip() or None
    GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    AGENT_BUILDER_LOCATION: str = os.getenv("AGENT_BUILDER_LOCATION", "global").strip()
    AGENT_BUILDER_DATA_STORE: Optional[str] = os.getenv("AGENT_BUILDER_DATA_STORE", "").strip() or None

    # Flags
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in {"1", "true", "yes"}
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()

    @classmethod
    def validate(cls) -> list[str]:
        """Validate required configuration. Returns list of errors."""
        errors = []

        if cls.TWILIO_ACCOUNT_SID or cls.TWILIO_AUTH_TOKEN or cls.TWILIO_PHONE_NUMBER:
            if not cls.TWILIO_ACCOUNT_SID:
                errors.append("TWILIO_ACCOUNT_SID is required when using Twilio")
            if not cls.TWILIO_AUTH_TOKEN:
                errors.append("TWILIO_AUTH_TOKEN is required when using Twilio")
            if not cls.TWILIO_PHONE_NUMBER:
                errors.append("TWILIO_PHONE_NUMBER is required when using Twilio")
        if not cls.DATABASE_URL:
            errors.append("DATABASE_URL is required")
        if not cls.SESSION_SECRET:
            errors.append("SESSION_SECRET is required and must be at least 32 characters")
        elif len(cls.SESSION_SECRET) < 32:
            errors.append("SESSION_SECRET must be at least 32 characters")

        # AI Configuration checks
        if cls.GROQ_API_KEY and not cls.GROQ_API_KEY.startswith("gsk_"):
            errors.append("GROQ_API_KEY should start with 'gsk_'")
        if cls.MISTRAL_API_KEY and len(cls.MISTRAL_API_KEY) < 16:
            errors.append("MISTRAL_API_KEY seems too short")

        # Production-specific validation
        if cls.ENVIRONMENT == "production":
            if not cls.COOKIE_SECURE:
                errors.append("COOKIE_SECURE must be True in production")
            if cls.DEBUG:
                errors.append("DEBUG must be False in production")

        return errors

    @classmethod
    def is_valid(cls) -> bool:
        """Check if configuration is valid."""
        return len(cls.validate()) == 0

    @classmethod
    def get_validation_errors(cls) -> str:
        """Get validation errors as formatted string."""
        errors = cls.validate()
        if not errors:
            return "Configuration is valid"
        return "Configuration errors:\n" + "\n".join(f"  - {error}" for error in errors)


# Validate on import
_errors = Config.validate()
if _errors:
    import sys

    print("\n" + "=" * 60)
    print("Configuration validation failed!")
    print("=" * 60)
    for error in _errors:
        print(f"  ✗ {error}")
    print("=" * 60 + "\n")
    sys.exit(1)
