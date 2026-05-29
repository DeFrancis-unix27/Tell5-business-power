import pytest
from httpx import AsyncClient
from datetime import datetime
import hmac
import hashlib
from urllib.parse import urlencode


@pytest.mark.integration
@pytest.mark.webhook
@pytest.mark.asyncio
class TestWebhookEndpoint:
    """Test Twilio webhook endpoint"""

    def generate_twilio_signature(self, url: str, params: dict, auth_token: str) -> str:
        """Generate a valid Twilio signature for testing"""
        if isinstance(params, dict):
            s = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
        else:
            s = url + params
        return hmac.new(
            auth_token.encode(),
            s.encode(),
            hashlib.sha1,
        ).digest().hex()

    async def test_webhook_missing_from(self, client: AsyncClient):
        """Test webhook with missing From field"""
        response = await client.post(
            "/webhook/whatsapp",
            data={"Body": "test message"},
        )
        assert response.status_code == 400

    async def test_webhook_missing_body(self, client: AsyncClient):
        """Test webhook with missing Body field"""
        response = await client.post(
            "/webhook/whatsapp",
            data={"From": "whatsapp:+1234567890"},
        )
        assert response.status_code == 400

    async def test_webhook_valid_order_message(self, client: AsyncClient):
        """Test webhook with valid order message"""
        from config import Config

        params = {
            "From": "whatsapp:+1234567890",
            "Body": "I would like to order 2 pizzas",
            "MessageSid": f"SM{datetime.now().timestamp()}",
            "AccountSid": Config.TWILIO_ACCOUNT_SID,
        }

        signature = self.generate_twilio_signature(
            "http://test/webhook/whatsapp",
            params,
            Config.TWILIO_AUTH_TOKEN,
        )

        response = await client.post(
            "/webhook/whatsapp",
            data=params,
            headers={"X-Twilio-Signature": signature},
        )
        assert response.status_code == 200

    async def test_webhook_valid_inquiry_message(self, client: AsyncClient):
        """Test webhook with inquiry message"""
        from config import Config

        params = {
            "From": "whatsapp:+1987654321",
            "Body": "What's the price for your premium package?",
            "MessageSid": f"SM{datetime.now().timestamp()}",
            "AccountSid": Config.TWILIO_ACCOUNT_SID,
        }

        signature = self.generate_twilio_signature(
            "http://test/webhook/whatsapp",
            params,
            Config.TWILIO_AUTH_TOKEN,
        )

        response = await client.post(
            "/webhook/whatsapp",
            data=params,
            headers={"X-Twilio-Signature": signature},
        )
        assert response.status_code == 200

    async def test_webhook_valid_complaint_message(self, client: AsyncClient):
        """Test webhook with complaint message"""
        from config import Config

        params = {
            "From": "whatsapp:+1111111111",
            "Body": "I have a complaint about my last order",
            "MessageSid": f"SM{datetime.now().timestamp()}",
            "AccountSid": Config.TWILIO_ACCOUNT_SID,
        }

        signature = self.generate_twilio_signature(
            "http://test/webhook/whatsapp",
            params,
            Config.TWILIO_AUTH_TOKEN,
        )

        response = await client.post(
            "/webhook/whatsapp",
            data=params,
            headers={"X-Twilio-Signature": signature},
        )
        assert response.status_code == 200

    async def test_webhook_valid_feedback_message(self, client: AsyncClient):
        """Test webhook with positive feedback message"""
        from config import Config

        params = {
            "From": "whatsapp:+2222222222",
            "Body": "Thanks so much! Great service and fast delivery!",
            "MessageSid": f"SM{datetime.now().timestamp()}",
            "AccountSid": Config.TWILIO_ACCOUNT_SID,
        }

        signature = self.generate_twilio_signature(
            "http://test/webhook/whatsapp",
            params,
            Config.TWILIO_AUTH_TOKEN,
        )

        response = await client.post(
            "/webhook/whatsapp",
            data=params,
            headers={"X-Twilio-Signature": signature},
        )
        assert response.status_code == 200

    async def test_webhook_invalid_signature(self, client: AsyncClient):
        """Test webhook with invalid signature"""
        params = {
            "From": "whatsapp:+1234567890",
            "Body": "test message",
            "MessageSid": "SM123",
            "AccountSid": "AC123",
        }

        response = await client.post(
            "/webhook/whatsapp",
            data=params,
            headers={"X-Twilio-Signature": "invalid_signature"},
        )
        assert response.status_code == 403

    async def test_webhook_returns_twiml(self, client: AsyncClient):
        """Test that webhook returns valid TwiML"""
        from config import Config

        params = {
            "From": "whatsapp:+1234567890",
            "Body": "order test",
            "MessageSid": f"SM{datetime.now().timestamp()}",
            "AccountSid": Config.TWILIO_ACCOUNT_SID,
        }

        signature = self.generate_twilio_signature(
            "http://test/webhook/whatsapp",
            params,
            Config.TWILIO_AUTH_TOKEN,
        )

        response = await client.post(
            "/webhook/whatsapp",
            data=params,
            headers={"X-Twilio-Signature": signature},
        )
        assert response.status_code == 200
        assert "<?xml" in response.text
        assert "application/xml" in response.headers["content-type"]


@pytest.mark.unit
class TestMessageCategorization:
    """Test message categorization logic"""

    def test_categorize_order_messages(self):
        """Test that order keywords are recognized"""
        from api.index import categorize_message

        messages = [
            "I'd like to order 2 pizzas",
            "Can I buy some items?",
            "I want to purchase 5 units",
        ]
        for msg in messages:
            assert categorize_message(msg) == "order"

    def test_categorize_inquiry_messages(self):
        """Test that inquiry keywords are recognized"""
        from api.index import categorize_message

        messages = [
            "What's the price?",
            "How much does it cost?",
            "Can you tell me more details?",
            "When is it available?",
        ]
        for msg in messages:
            assert categorize_message(msg) == "inquiry"

    def test_categorize_complaint_messages(self):
        """Test that complaint keywords are recognized"""
        from api.index import categorize_message

        messages = [
            "I have a complaint",
            "There's an issue with my order",
            "The product arrived damaged",
            "This is all wrong!",
        ]
        for msg in messages:
            assert categorize_message(msg) == "complaint"

    def test_categorize_feedback_messages(self):
        """Test that feedback keywords are recognized"""
        from api.index import categorize_message

        messages = [
            "Thanks for the quick service",
            "I love this product",
            "Great work!",
            "This is excellent",
        ]
        for msg in messages:
            assert categorize_message(msg) == "feedback"

    def test_categorize_default_to_inquiry(self):
        """Test that unknown messages default to inquiry"""
        from api.index import categorize_message

        messages = [
            "Hello there",
            "Good morning",
            "xyz abc 123",
        ]
        for msg in messages:
            assert categorize_message(msg) == "inquiry"


@pytest.mark.unit
class TestOrderParsing:
    """Test order parsing logic"""

    def test_parse_order_with_quantity(self):
        """Test parsing order with quantity and item"""
        from api.index import parse_order

        item, qty = parse_order("I want 5 pizzas")
        assert qty == 5
        assert item == "pizzas"

    def test_parse_order_without_quantity(self):
        """Test parsing order without explicit quantity"""
        from api.index import parse_order

        item, qty = parse_order("I want pizza")
        assert qty == 1
        assert isinstance(item, str)

    def test_parse_order_empty_message(self):
        """Test parsing empty order message"""
        from api.index import parse_order

        item, qty = parse_order("")
        assert qty == 1
        assert item == "item"

    def test_parse_order_multiple_numbers(self):
        """Test parsing order with multiple numbers"""
        from api.index import parse_order

        item, qty = parse_order("2024 units of product")
        assert qty == 2024
