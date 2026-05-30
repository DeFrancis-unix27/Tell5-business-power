import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration with validation."""

    # Required in production
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "").strip()
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "").strip()

    # Optional
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", "").strip() or None
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
    ADMIN_EMAIL: Optional[str] = os.getenv("ADMIN_EMAIL", "").strip() or None

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
