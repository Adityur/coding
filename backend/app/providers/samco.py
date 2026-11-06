"""SAMCO StockNote REST provider.

Credentials come only from Settings (environment). The session token is held in memory, sent only
in the x-session-token header, and never logged or returned. Response parsing is tolerant because
field names should be verified against a live account (see FINAL_STATUS.md).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import httpx

from ..config import Settings
from .base import IST, TIMEFRAME_MINUTES, Candle, MarketDataProvider, ProviderError, ProviderNotConfigured, Quote

log = logging.getLogger("swing.samco")

BENCHMARK_INDEX = "NIFTY 50"
LOOKBACK_DAYS = {"1d": 420, "1h": 45, "15m": 14, "5m": 6}
SESSION_ERROR_HINTS = ("session", "token", "login", "unauthori", "expired")


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _find(obj, *keys):
    """Return the first value found for any of keys, searching nested dicts breadth-first."""
    queue = [obj]
    while queue:
        cur = queue.pop(0)
        if isinstance(cur, dict):
            for k in keys:
                if k in cur and cur[k] not in (None, ""):
                    return cur[k]
            queue.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            queue.extend(v for v in cur if isinstance(v, (dict, list)))
    return None


def _parse_ts(raw: str) -> datetime:
    raw = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S",
                "%d-%m-%Y", "%d/%m/%Y %H:%M:%S", "%d %b %Y %H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            if fmt in ("%Y-%m-%d", "%d-%m-%Y"):
                dt = dt.replace(hour=15, minute=30)
            return dt.replace(tzinfo=IST)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp format: {raw!r}")


def parse_candles(payload: dict, list_keys: tuple[str, ...]) -> list[Candle]:
    rows = None
    for k in list_keys:
        rows = _find(payload, k)
        if isinstance(rows, list):
            break
    if not isinstance(rows, list):
        return []
    out: list[Candle] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_raw = row.get("dateTime") or row.get("date") or row.get("time") or row.get("timestamp")
        o, h, l, c = (_num(row.get(k)) for k in ("open", "high", "low", "close"))
        if c is None:
            c = _num(row.get("ltp"))
        if ts_raw is None or None in (o, h, l, c):
            continue
        try:
            ts = _parse_ts(ts_raw)
        except ValueError:
            continue
        out.append(Candle(ts, o, h, l, c, _num(row.get("volume")) or 0.0))
    out.sort(key=lambda x: x.ts)
    return out


class SamcoProvider(MarketDataProvider):
    name = "SAMCO"
    is_live = True

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        if not settings.samco_configured:
            raise ProviderNotConfigured(
                "SAMCO credentials are not configured. Set SAMCO_USER_ID, SAMCO_PASSWORD and SAMCO_YOB "
                "in your local .env file, or set DEMO_MODE=true."
            )
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.samco_base_url,
            timeout=httpx.Timeout(settings.samco_timeout_seconds),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            transport=transport,
        )
        self._token: str | None = None
        self._login_lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(settings.samco_max_concurrency)
        self._last_error: str | None = None
        self._last_success: datetime | None = None

    async def _login(self) -> None:
        async with self._login_lock:
            if self._token:
                return
            body = {"userId": self._settings.samco_user_id, "password": self._settings.samco_password,
                    "yob": self._settings.samco_yob}
            try:
                resp = await self._client.post("/login", json=body)
            except httpx.TimeoutException as exc:
                raise ProviderError("SAMCO login timed out", code="provider_timeout", status=504) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"SAMCO login failed: network error ({type(exc).__name__})") from exc
            data = self._json(resp)
            token = data.get("sessionToken") if isinstance(data, dict) else None
            if resp.status_code != 200 or not token:
                msg = data.get("statusMessage") if isinstance(data, dict) else None
                raise ProviderError(f"SAMCO login rejected ({resp.status_code}): {self._safe(msg) or 'no session token'}",
                                    code="provider_auth_failed", status=502)
            self._token = token
            log.info("SAMCO session established")

    def _safe(self, text) -> str:
        """Strip anything that might echo a credential back into an error message."""
        if text is None:
            return ""
        s = str(text)[:200]
        for secret in (self._settings.samco_password, self._settings.samco_user_id, self._settings.samco_yob, self._token):
            if secret:
                s = s.replace(secret, "***")
        return s

    @staticmethod
    def _json(resp: httpx.Response):
        try:
            return resp.json()
        except ValueError:
            return {}

    async def _get(self, path: str, params: dict) -> dict:
        async with self._sem:
            for attempt in range(3):
                await self._login()
                try:
                    resp = await self._client.get(path, params=params, headers={"x-session-token": self._token or ""})
                except httpx.TimeoutException as exc:
                    if attempt == 2:
                        self._last_error = "timeout"
                        raise ProviderError(f"SAMCO request timed out ({path})", code="provider_timeout", status=504) from exc
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                except httpx.HTTPError as exc:
                    if attempt == 2:
                        self._last_error = type(exc).__name__
                        raise ProviderError(f"SAMCO network error ({type(exc).__name__}) on {path}") from exc
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                data = self._json(resp)
                status_msg = str(data.get("statusMessage", "")) if isinstance(data, dict) else ""
                failed = resp.status_code in (401, 403) or (
                    isinstance(data, dict) and str(data.get("status", "")).lower() == "failure"
                    and any(h in status_msg.lower() for h in SESSION_ERROR_HINTS))
                if failed and attempt < 2:
                    self._token = None
                    continue
                if resp.status_code >= 400 or (isinstance(data, dict) and str(data.get("status", "")).lower() == "failure"):
                    self._last_error = f"HTTP {resp.status_code}"
                    raise ProviderError(f"SAMCO error on {path} ({resp.status_code}): {self._safe(status_msg) or 'request failed'}")
                self._last_error = None
                self._last_success = datetime.now(IST)
                return data if isinstance(data, dict) else {"data": data}
        raise ProviderError(f"SAMCO request failed ({path})")

    async def get_quote(self, symbol: str) -> Quote:
        data = await self._get("/quote/getQuote", {"symbolName": symbol, "exchange": "NSE"})
        ltp = _num(_find(data, "lastTradedPrice", "ltp", "lastPrice"))
        if ltp is None:
            raise ProviderError(f"SAMCO quote for {symbol} had no last traded price", code="provider_bad_data")
        prev = _num(_find(data, "previousClose", "closeValue", "prevClose"))
        change = _num(_find(data, "changeValue", "change"))
        if change is None and prev:
            change = round(ltp - prev, 2)
        change_pct = _num(_find(data, "changePercentage", "percentChange", "pChange"))
        if change_pct is None and prev:
            change_pct = round((ltp - prev) / prev * 100, 2)
        ts_raw = _find(data, "lastTradedTime", "lastTradeTime")
        try:
            ts = _parse_ts(ts_raw) if ts_raw else datetime.now(IST)
        except ValueError:
            ts = datetime.now(IST)
        return Quote(symbol=symbol, ltp=ltp, open=_num(_find(data, "openValue", "open")),
                     high=_num(_find(data, "highValue", "high")), low=_num(_find(data, "lowValue", "low")),
                     prev_close=prev, change=change, change_pct=change_pct,
                     volume=_num(_find(data, "totalTradedVolume", "volume")), ts=ts,
                     data_source="SAMCO", is_live=True)

    def _range(self, timeframe: str) -> tuple[str, str]:
        now = datetime.now(IST)
        start = now - timedelta(days=LOOKBACK_DAYS[timeframe])
        if timeframe == "1d":
            return start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")
        return start.strftime("%Y-%m-%d 09:15:00"), now.strftime("%Y-%m-%d %H:%M:%S")

    async def get_candles(self, symbol: str, timeframe: str) -> list[Candle]:
        if timeframe not in LOOKBACK_DAYS:
            raise ProviderError(f"Unsupported timeframe '{timeframe}'", code="bad_timeframe", status=400)
        frm, to = self._range(timeframe)
        if timeframe == "1d":
            data = await self._get("/history/candleData",
                                   {"symbolName": symbol, "exchange": "NSE", "fromDate": frm, "toDate": to})
            return parse_candles(data, ("historicalCandleData", "candleData"))
        data = await self._get("/intraday/candleData", {"symbolName": symbol, "exchange": "NSE", "fromDate": frm,
                                                        "toDate": to, "interval": str(TIMEFRAME_MINUTES[timeframe])})
        return parse_candles(data, ("intradayCandleData", "candleData"))

    async def get_benchmark_candles(self, timeframe: str = "1d") -> list[Candle]:
        frm, to = self._range(timeframe)
        if timeframe == "1d":
            data = await self._get("/history/indexCandleData", {"indexName": BENCHMARK_INDEX, "fromDate": frm, "toDate": to})
            return parse_candles(data, ("indexCandleData", "historicalCandleData"))
        data = await self._get("/intraday/indexCandleData", {"indexName": BENCHMARK_INDEX, "fromDate": frm, "toDate": to,
                                                             "interval": str(TIMEFRAME_MINUTES[timeframe])})
        return parse_candles(data, ("indexIntraDayCandleData", "intradayCandleData"))

    async def status(self) -> dict:
        return {"provider": self.name, "is_live": True, "connected": self._token is not None,
                "last_success": self._last_success.isoformat() if self._last_success else None,
                "last_error": self._last_error}

    async def close(self) -> None:
        await self._client.aclose()
