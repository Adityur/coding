"""Deterministic synthetic market data for DEMO_MODE.

Values are generated from a seeded random walk per (symbol, date) so they are stable within a
day and reproducible in tests. Every payload built from this provider is labelled data_source=DEMO.
"""
from __future__ import annotations

import math
import random
import zlib
from datetime import date, datetime, time, timedelta

from .base import IST, Candle, MarketDataProvider, ProviderError, Quote

BENCHMARK_SYMBOL = "NIFTY 50"
DAILY_SESSIONS = 300
INTRADAY_SESSIONS = 30
BARS_PER_SESSION_5M = 75  # 09:15 -> 15:30
SESSION_OPEN = time(9, 15)


def _seed(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode())


def _trading_days(end: date, count: int) -> list[date]:
    days: list[date] = []
    d = end
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


def _last_session(now: datetime) -> date:
    d = now.date()
    if now.time() < SESSION_OPEN:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


class _Series:
    def __init__(self, daily: list[Candle], intraday_5m: list[Candle]):
        self.daily = daily
        self.m5 = intraday_5m


class DemoProvider(MarketDataProvider):
    name = "DEMO"
    is_live = False

    def __init__(self, now_fn=None):
        self._now_fn = now_fn or (lambda: datetime.now(IST))
        self._cache: dict[tuple[str, date], _Series] = {}

    def _series(self, symbol: str) -> _Series:
        end = _last_session(self._now_fn())
        key = (symbol, end)
        if key not in self._cache:
            if len(self._cache) > 500:
                self._cache.clear()
            self._cache[key] = self._generate(symbol, end)
        return self._cache[key]

    def _generate(self, symbol: str, end: date) -> _Series:
        persona = random.Random(_seed("persona", symbol))
        is_index = symbol == BENCHMARK_SYMBOL
        base = 24000.0 if is_index else persona.uniform(150, 4000)
        drift = persona.uniform(-0.0012, 0.0022) if not is_index else 0.0005
        vol = persona.uniform(0.011, 0.024) if not is_index else 0.008
        base_volume = 0.0 if is_index else persona.uniform(4e5, 8e6)

        rng = random.Random(_seed("series", symbol, end.isoformat()))
        days = _trading_days(end, DAILY_SESSIONS)
        regime_len = rng.randint(40, 90)
        regime_drift = drift
        price = base
        daily: list[Candle] = []
        for i, d in enumerate(days):
            if i % regime_len == 0:
                regime_drift = drift + rng.uniform(-0.002, 0.002)
            ret = rng.gauss(regime_drift, vol)
            open_ = price * (1 + rng.gauss(0, vol / 4))
            close = max(1.0, price * math.exp(ret))
            hi = max(open_, close) * (1 + abs(rng.gauss(0, vol / 2)))
            lo = min(open_, close) * (1 - abs(rng.gauss(0, vol / 2)))
            spike = 2.5 if rng.random() < 0.06 else 1.0
            volume = 0.0 if is_index else base_volume * math.exp(rng.gauss(0, 0.35)) * spike * (1.4 if ret > 0 else 1.0)
            daily.append(Candle(datetime.combine(d, time(15, 30), IST), round(open_, 2), round(hi, 2),
                                round(lo, 2), round(close, 2), round(volume)))
            price = close

        m5: list[Candle] = []
        for idx in range(len(daily) - INTRADAY_SESSIONS, len(daily)):
            bar = daily[idx]
            session_bars = self._bridge(rng, bar, vol, is_index)
            m5.extend(session_bars)
            hi = max(c.high for c in session_bars)
            lo = min(c.low for c in session_bars)
            volume = sum(c.volume for c in session_bars)
            daily[idx] = Candle(bar.ts, bar.open, round(hi, 2), round(lo, 2), bar.close, round(volume))
        return _Series(daily, m5)

    @staticmethod
    def _bridge(rng: random.Random, bar: Candle, vol: float, is_index: bool) -> list[Candle]:
        n = BARS_PER_SESSION_5M
        step_vol = vol / math.sqrt(n) * 0.9
        path = [0.0]
        for _ in range(n):
            path.append(path[-1] + rng.gauss(0, step_vol))
        log_open, log_close = math.log(bar.open), math.log(bar.close)
        prices = [math.exp(log_open + p - (k / n) * (path[-1] - (log_close - log_open))) for k, p in enumerate(path)]
        start = datetime.combine(bar.ts.date(), SESSION_OPEN, IST)
        out: list[Candle] = []
        for k in range(n):
            o, c = prices[k], prices[k + 1]
            wiggle = abs(rng.gauss(0, step_vol / 2))
            u_shape = 1.8 - 1.6 * math.sin(math.pi * (k + 0.5) / n)
            v = 0.0 if is_index else max(1.0, bar.volume / n * u_shape * math.exp(rng.gauss(0, 0.3)))
            out.append(Candle(start + timedelta(minutes=5 * k), round(o, 2), round(max(o, c) * (1 + wiggle), 2),
                              round(min(o, c) * (1 - wiggle), 2), round(c, 2), round(v)))
        return out

    @staticmethod
    def _aggregate(m5: list[Candle], minutes: int) -> list[Candle]:
        group = minutes // 5
        out: list[Candle] = []
        bucket: list[Candle] = []
        current_day = None
        for c in m5:
            if c.ts.date() != current_day:
                if bucket:
                    out.append(DemoProvider._merge(bucket))
                bucket, current_day = [], c.ts.date()
            bucket.append(c)
            if len(bucket) == group:
                out.append(DemoProvider._merge(bucket))
                bucket = []
        if bucket:
            out.append(DemoProvider._merge(bucket))
        return out

    @staticmethod
    def _merge(bars: list[Candle]) -> Candle:
        return Candle(bars[0].ts, bars[0].open, max(b.high for b in bars), min(b.low for b in bars),
                      bars[-1].close, sum(b.volume for b in bars))

    async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        series = self._series(symbol)
        if timeframe == "1d":
            return list(series.daily)
        if timeframe == "5m":
            return series.m5[-500:]
        if timeframe == "15m":
            return self._aggregate(series.m5, 15)
        if timeframe == "1h":
            return self._aggregate(series.m5, 60)
        raise ProviderError(f"Unsupported timeframe '{timeframe}'", code="bad_timeframe", status=400)

    async def get_benchmark_candles(self, timeframe: str = "1d") -> list[Candle]:
        return await self.get_candles(BENCHMARK_SYMBOL, timeframe)

    async def get_quote(self, symbol: str) -> Quote:
        series = self._series(symbol)
        today = series.daily[-1]
        prev = series.daily[-2]
        last = series.m5[-1]
        change = round(today.close - prev.close, 2)
        return Quote(
            symbol=symbol, ltp=today.close, open=today.open, high=today.high, low=today.low,
            prev_close=prev.close, change=change, change_pct=round(change / prev.close * 100, 2),
            volume=today.volume, ts=last.ts + timedelta(minutes=5), data_source="DEMO", is_live=False,
        )

    async def status(self) -> dict:
        return {"provider": self.name, "is_live": False, "connected": True,
                "message": "Synthetic deterministic demo data. Not real market prices."}
