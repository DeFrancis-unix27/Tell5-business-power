import logging

logger = logging.getLogger(__name__)

# Feature definitions grouped by tier
TIER_FEATURES = {
    "free": [
        "ai_categorization",
        "conversation_inbox",
        "order_tracking",
        "basic_dashboard",
        "business_profile",
        "personality_qa_basic",
        "webhook_api",
    ],
    "growth": [
        "ai_categorization",
        "ai_auto_reply",
        "conversation_inbox",
        "order_tracking",
        "full_analytics",
        "business_profile",
        "multiple_numbers",
        "personality_qa_basic",
        "webhook_api",
        "priority_support",
    ],
    "enterprise": [
        "ai_categorization",
        "ai_auto_reply",
        "conversation_inbox",
        "order_tracking",
        "full_analytics",
        "business_profile",
        "multiple_numbers",
        "personality_qa_basic",
        "webhook_api",
        "priority_support",
        "dedicated_adk_agent",
        "mongodb_mcp",
        "custom_integrations",
        "on_premise",
        "sla_guarantee",
    ],
}

_pricing_enabled: bool = False


def set_pricing_enabled(enabled: bool):
    global _pricing_enabled
    _pricing_enabled = enabled


def pricing_enabled() -> bool:
    return _pricing_enabled


def has_feature(tier: str, feature: str) -> bool:
    return feature in TIER_FEATURES.get(tier, [])


def require_feature(feature: str, user_tier: str = "free") -> bool:
    if not _pricing_enabled:
        return True
    return has_feature(user_tier, feature)
