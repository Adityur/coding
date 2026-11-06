"""Market-data provider abstraction shared by the demo and SAMCO providers."""
from __future__ import annotations

import abc
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

TIMEFRAME_MINUTES = {"5m": 5, "15m": 15, "1h": 60}


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


@dataclass(frozen=True)
class Quote:
    symbol: str
    ltp: float
    open: float | None
    high: float | None
    low: float | None
    prev_close: float | None
    change: float | None
    change_pct: float | None
    volume: float | None
    ts: datetime
    data_source: str
    is_live: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


class ProviderError(Exception):
    """Raised when a provider cannot serve data. Messages must never contain credentials."""

    def __init__(self, message: str, *, code: str = "provider_error", status: int = 502):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class ProviderNotConfigured(ProviderError):
    def __init__(self, message: str):
        super().__init__(message, code="provider_not_configured", status=503)


class MarketDataProvider(abc.ABC):
    name: str = "base"
    is_live: bool = False

    @abc.abstractmethod
    async def get_quote(self, symbol: str) -> Quote: ...

    @abc.abstractmethod
    async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]: ...

    @abc.abstractmethod
    async def get_benchmark_candles(self, timeframe: str = "1d") -> list[Candle]: ...

    async def status(self) -> dict:
        return {"provider": self.name, "is_live": self.is_live, "connected": True}

    async def close(self) -> None:
        return None
