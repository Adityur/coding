from __future__ import annotations

from ..config import Settings
from .base import MarketDataProvider, ProviderNotConfigured
from .demo import DemoProvider
from .reference import DemoReference, FileReference


class UnavailableProvider(MarketDataProvider):
    """Used when live mode is requested but the provider cannot be constructed. Every call fails loudly."""

    is_live = True

    def __init__(self, name: str, reason: str):
        self.name = name
        self.reason = reason

    async def get_quote(self, symbol):
        raise ProviderNotConfigured(self.reason)

    async def get_candles(self, symbol, timeframe):
        raise ProviderNotConfigured(self.reason)

    async def get_benchmark_candles(self, timeframe="1d"):
        raise ProviderNotConfigured(self.reason)

    async def status(self) -> dict:
        return {"provider": self.name, "is_live": True, "connected": False, "last_error": self.reason}


def build_provider(settings: Settings) -> MarketDataProvider:
    if settings.demo_mode:
        return DemoProvider()
    if settings.provider == "samco":
        from .samco import SamcoProvider
        try:
            return SamcoProvider(settings)
        except ProviderNotConfigured as exc:
            return UnavailableProvider("SAMCO", exc.message)
    return UnavailableProvider(settings.provider.upper(), f"Unknown MARKET_DATA_PROVIDER '{settings.provider}'. Supported: samco.")


def build_reference(settings: Settings):
    return DemoReference() if settings.demo_mode else FileReference(settings.reference_data_file)
