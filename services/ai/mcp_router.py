from typing import Any, Optional


class MCPRouter:
    def __init__(self):
        self._models: dict[str, dict[str, Any]] = {}

    def register(self, tier: int, name: str, provider: str, config: Optional[dict[str, Any]] = None):
        self._models[name] = {
            "tier": tier,
            "provider": provider,
            "config": config or {},
        }

    def get_models_by_tier(self, tier: int) -> list[dict[str, Any]]:
        return [m for m in self._models.values() if m["tier"] == tier]

    def get_pipeline_order(self) -> list[str]:
        sorted_models = sorted(self._models.items(), key=lambda x: x[1]["tier"])
        return [name for name, _ in sorted_models]

    def is_configured(self, provider: str, user_api_keys: Optional[dict[str, str]] = None) -> bool:
        from config import Config
        key_map = {
            "gemini": bool(Config.GEMINI_API_KEY or (user_api_keys or {}).get("gemini")),
            "groq": bool(Config.GROQ_API_KEY or (user_api_keys or {}).get("groq")),
            "mistral": bool(Config.MISTRAL_API_KEY or (user_api_keys or {}).get("mistral")),
            "openrouter": bool(Config.OPENROUTER_API_KEY or (user_api_keys or {}).get("openrouter")),
            "discovery_engine": bool(Config.AGENT_BUILDER_DATA_STORE),
            "adk": bool(Config.GEMINI_API_KEY or (user_api_keys or {}).get("gemini")),
        }
        return key_map.get(provider, False)


router = MCPRouter()
router.register(tier=1, name="gemini", provider="gemini", config={"model": "gemini-2.5-flash-lite"})
router.register(tier=2, name="groq", provider="groq", config={"model": "llama-3.3-70b-versatile"})

# OpenRouter sits at tier 1.5 — acts as Gemini fallback and standalone provider
router.register(tier=2, name="openrouter", provider="openrouter", config={"model": "google/gemini-2.0-flash-exp:free"})

router.register(tier=3, name="mistral", provider="mistral", config={"model": "mistral-large-latest"})
router.register(tier=4, name="adk", provider="adk", config={"model": "gemini-2.5-flash-lite"})
