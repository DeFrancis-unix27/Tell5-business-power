import logging
import os
from typing import Any

import httpx

from config import Config
from services.channels.base import ChannelProvider, router

logger = logging.getLogger(__name__)
BOT_PORT = os.getenv("BOT_PORT", "3001")


class TwilioWhatsAppProvider(ChannelProvider):
    def name(self) -> str:
        return "whatsapp"

    async def send_message(self, to: str, body: str, **kwargs: Any) -> bool:
        if not Config.TWILIO_ACCOUNT_SID or not Config.TWILIO_AUTH_TOKEN:
            logger.warning("Twilio not configured")
            return False

        from twilio.rest import Client

        try:
            client = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
            client.messages.create(
                from_=Config.TWILIO_PHONE_NUMBER,
                body=body,
                to=to,
            )
            return True
        except Exception as e:
            logger.error(f"Twilio send failed: {e}")
            return False

    async def is_available(self) -> bool:
        return bool(
            Config.TWILIO_ACCOUNT_SID
            and Config.TWILIO_AUTH_TOKEN
            and Config.TWILIO_PHONE_NUMBER
        )


class BaileysWhatsAppProvider(ChannelProvider):
    def name(self) -> str:
        return "whatsapp_baileys"

    async def send_message(self, to: str, body: str, **kwargs: Any) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"http://127.0.0.1:{BOT_PORT}/send",
                    json={"to": to, "body": body},
                )
                if resp.status_code == 200:
                    return True
                logger.warning(f"Baileys bot returned {resp.status_code}: {resp.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"Baileys send failed: {e}")
            return False

    async def is_available(self) -> bool:
        import json
        from pathlib import Path
        state_file = Path("services/whatsapp/qr-state.json")
        if not state_file.exists():
            return False
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            return bool(state.get("connected"))
        except Exception:
            return False


router.register(TwilioWhatsAppProvider())
router.register(BaileysWhatsAppProvider())
