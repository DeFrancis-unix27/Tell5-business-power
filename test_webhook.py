#!/usr/bin/env python3
"""
Test script for Tell5 WhatsApp webhook.
Simulates Twilio webhook requests for testing without Twilio Sandbox.
"""

import requests
import json
import os
from datetime import datetime
import sys
from dotenv import load_dotenv
load_dotenv()

# Configuration
WEBHOOK_URL = "http://localhost:8000/webhook/whatsapp"
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")   # Set from .env if validating signatures

# Test messages to simulate different categories
TEST_MESSAGES = [
    {
        "name": "Order",
        "phone": "+1234567890",
        "message": "I'd like to order 2 pizzas please",
        "expected_category": "order"
    },
    {
        "name": "Inquiry",
        "phone": "+1234567891",
        "message": "What's the price for your premium package?",
        "expected_category": "inquiry"
    },
    {
        "name": "Complaint",
        "phone": "+1234567892",
        "message": "I'm very unhappy with my last order, the item arrived damaged",
        "expected_category": "complaint"
    },
    {
        "name": "Feedback",
        "phone": "+1234567893",
        "message": "Thanks so much! Great service and fast delivery!",
        "expected_category": "feedback"
    },
]

def test_webhook(message_data):
    """Test webhook with a single message"""
    payload = {
        "From": f"whatsapp:{message_data['phone']}",
        "Body": message_data['message'],
        "MessageSid": f"SM{datetime.now().timestamp()}",
        "AccountSid": "ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    }

    print(f"\n{'='*60}")
    print(f"Testing: {message_data['name']}")
    print(f"Message: {message_data['message']}")
    print(f"Expected Category: {message_data['expected_category']}")
    print(f"{'='*60}")

    try:
        response = requests.post(WEBHOOK_URL, data=payload)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}")

        if response.status_code == 200:
            print("✓ Webhook accepted")
        else:
            print(f"✗ Webhook returned {response.status_code}")

    except requests.exceptions.ConnectionError:
        print("✗ Could not connect to webhook URL")
        print(f"  Make sure the app is running: uvicorn main:app --reload")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")

def test_api_endpoints():
    """Test API endpoints"""
    endpoints = [
        ("GET", "http://localhost:8000/api/conversations", "Conversations"),
        ("GET", "http://localhost:8000/api/orders", "Orders"),
        ("GET", "http://localhost:8000/api/stats", "Stats"),
        ("GET", "http://localhost:8000/dashboard", "Dashboard"),
    ]

    print(f"\n\n{'='*60}")
    print("Testing API Endpoints")
    print(f"{'='*60}")

    for method, url, name in endpoints:
        try:
            response = requests.request(method, url)
            status = "✓" if response.status_code == 200 else "✗"
            print(f"{status} {method} {name}: {response.status_code}")
        except Exception as e:
            print(f"✗ {method} {name}: {e}")

def run_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("Tell5 Webhook Test Suite")
    print("="*60)
    print("\nMake sure:")
    print("1. Database is running")
    print("2. App is running: uvicorn main:app --reload")
    print("3. .env file is configured")

    # Test webhook with all message types
    for msg in TEST_MESSAGES:
        test_webhook(msg)

    # Test API endpoints
    test_api_endpoints()

    print("\n" + "="*60)
    print("Tests Complete!")
    print("Check http://localhost:8000/dashboard to view results")
    print("="*60 + "\n")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--url":
        WEBHOOK_URL = sys.argv[2] if len(sys.argv) > 2 else WEBHOOK_URL

    run_tests()
