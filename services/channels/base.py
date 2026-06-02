from abc import ABC, abstractmethod
from typing import Any, Optional


class ChannelProvider(ABC):
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def send_message(self, to: str, body: str, **kwargs: Any) -> bool:
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        ...


class ChannelRouter:
    def __init__(self):
        self._providers: dict[str, ChannelProvider] = {}

    def register(self, provider: ChannelProvider):
        self._providers[provider.name()] = provider

    def get(self, channel: str) -> Optional[ChannelProvider]:
        return self._providers.get(channel)

    def available_channels(self) -> list[str]:
        return list(self._providers.keys())

    async def send(self, channel: str, to: str, body: str, **kwargs: Any) -> bool:
        provider = self.get(channel)
        if not provider:
            return False
        return await provider.send_message(to, body, **kwargs)


router = ChannelRouter()
